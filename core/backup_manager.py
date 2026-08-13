"""
backup_manager.py
-------------------
Yerel (şifreli ZIP) + Google Drive (Service Account) yedekleme.

Gereksinimler:
    pip install pyzipper pydrive2

Notlar:
  - Yerel yedek: DBManager.backup_db() ile alınan .db dosyası pyzipper
    kullanılarak (opsiyonel parola ile) ZIP'lenir.
  - Google Drive: Service Account JSON anahtarı ile kullanıcı müdahalesi
    olmadan otomatik yükleme yapılır.
  - Ağır işler (yedekleme, upload) QThread üzerinde çalıştırılmalı;
    bu modül UI'dan bağımsızdır, worker sınıfı ui/ katmanında QThread'e sarılır.
"""

import os
import glob
import datetime
import threading

try:
    import pyzipper
except ImportError:
    pyzipper = None

try:
    from pydrive2.auth import ServiceAccountCredentials  # noqa: F401
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
except ImportError:
    GoogleAuth = None
    GoogleDrive = None

from core.db_manager import DBManager, DATA_DIR

YEDEK_DIR = os.path.join(os.path.dirname(DATA_DIR), "Yedekler")


class BackupManager:
    def __init__(self, max_yedek_sayisi: int = 10, zip_parola: str | None = None,
                 gdrive_json_path: str | None = None, gdrive_klasor_id: str | None = None):
        os.makedirs(YEDEK_DIR, exist_ok=True)
        self.max_yedek_sayisi = max_yedek_sayisi
        self.zip_parola = zip_parola.encode("utf-8") if zip_parola else None
        self.gdrive_json_path = gdrive_json_path
        self.gdrive_klasor_id = gdrive_klasor_id

    # ------------------------------------------------------------------
    # Yerel yedekleme
    # ------------------------------------------------------------------
    def yedekle_firma(self, firma_kodu: str, yil: int) -> str:
        """Tek bir firma/yıl veritabanını yedekler, şifreli ZIP döner (dosya yolu)."""
        if pyzipper is None:
            raise RuntimeError("pyzipper kurulu değil: pip install pyzipper")

        db = DBManager(firma_kodu, yil)
        zaman_damgasi = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        gecici_db = os.path.join(YEDEK_DIR, f"_gecici_{firma_kodu}_{yil}.db")
        db.backup_db(gecici_db)  # native SQLite backup() API - dosya kopyalama değil

        zip_yolu = os.path.join(YEDEK_DIR, f"{firma_kodu}_{yil}_{zaman_damgasi}.zip")
        try:
            if self.zip_parola:
                with pyzipper.AESZipFile(
                    zip_yolu, "w", compression=pyzipper.ZIP_LZMA,
                    encryption=pyzipper.WZ_AES,
                ) as zf:
                    zf.setpassword(self.zip_parola)
                    zf.write(gecici_db, arcname=f"{firma_kodu}_{yil}.db")
            else:
                with pyzipper.ZipFile(zip_yolu, "w", compression=pyzipper.ZIP_LZMA) as zf:
                    zf.write(gecici_db, arcname=f"{firma_kodu}_{yil}.db")
        finally:
            if os.path.exists(gecici_db):
                os.remove(gecici_db)

        self._eski_yedekleri_temizle(firma_kodu)
        return zip_yolu

    def yedekle_tum_firmalar(self) -> list[str]:
        """Data/ altındaki tüm *.db dosyalarını tarayıp her biri için yedek alır."""
        sonuclar = []
        for db_dosyasi in glob.glob(os.path.join(DATA_DIR, "*.db")):
            ad = os.path.splitext(os.path.basename(db_dosyasi))[0]  # FIRMA_YIL
            try:
                firma_kodu, yil = ad.rsplit("_", 1)
                sonuclar.append(self.yedekle_firma(firma_kodu, int(yil)))
            except ValueError:
                continue
        return sonuclar

    def _eski_yedekleri_temizle(self, firma_kodu: str):
        """'En fazla X yedek sakla' kuralı: firma bazında en yeni N tanesi kalır."""
        yedekler = sorted(
            glob.glob(os.path.join(YEDEK_DIR, f"{firma_kodu}_*.zip")),
            key=os.path.getmtime, reverse=True,
        )
        for eski in yedekler[self.max_yedek_sayisi:]:
            os.remove(eski)

    # ------------------------------------------------------------------
    # Google Drive (Service Account) yükleme
    # ------------------------------------------------------------------
    def gdrive_yukle(self, dosya_yolu: str) -> str:
        """
        Service Account JSON anahtarı ile Google Drive'a kullanıcı
        müdahalesi olmadan yükleme yapar. Hedef klasör ID'si ayarlardan gelir.
        Döner: Google Drive dosya ID'si.
        """
        if GoogleAuth is None:
            raise RuntimeError("pydrive2 kurulu değil: pip install pydrive2")
        if not self.gdrive_json_path or not os.path.exists(self.gdrive_json_path):
            raise RuntimeError("Google Drive Service Account JSON anahtar dosyası bulunamadı.")

        gauth = GoogleAuth()
        gauth.settings["client_config_backend"] = "service"
        gauth.settings["service_config"] = {
            "client_json_file_path": self.gdrive_json_path,
        }
        gauth.ServiceAuth()
        drive = GoogleDrive(gauth)

        dosya_meta = {"title": os.path.basename(dosya_yolu)}
        if self.gdrive_klasor_id:
            dosya_meta["parents"] = [{"id": self.gdrive_klasor_id}]

        gfile = drive.CreateFile(dosya_meta)
        gfile.SetContentFile(dosya_yolu)
        gfile.Upload()
        return gfile["id"]

    # ------------------------------------------------------------------
    # Arka planda (thread) çalıştırma - UI bloklanmasın
    # ------------------------------------------------------------------
    def arka_planda_tam_yedekle(self, google_drive_de: bool = True,
                                 tamamlaninca=None, hata_olunca=None):
        """
        Tüm firmaları arka planda yedekler ve isteğe bağlı olarak Drive'a yükler.
        tamamlaninca(sonuc_listesi) ve hata_olunca(exception) callback'leri
        UI thread'ine (örn. Qt sinyali ile) güvenli şekilde iletilmelidir;
        bu fonksiyon callback'leri worker thread'inden çağırır.
        """
        def _is():
            try:
                zip_dosyalari = self.yedekle_tum_firmalar()
                drive_sonuclari = []
                if google_drive_de:
                    for z in zip_dosyalari:
                        drive_sonuclari.append(self.gdrive_yukle(z))
                if tamamlaninca:
                    tamamlaninca({"zip_dosyalari": zip_dosyalari, "drive_id_listesi": drive_sonuclari})
            except Exception as e:  # noqa: BLE001
                if hata_olunca:
                    hata_olunca(e)

        t = threading.Thread(target=_is, daemon=True)
        t.start()
        return t
