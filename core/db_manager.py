"""
db_manager.py
--------------
Firma/yıl bazlı SQLAlchemy engine/session yönetimi.

Sorumluluklar:
  - Data/FIRMA_KODU_YIL.db dosyasını açma / gerekirse şemayı (models.py)
    ve varsayılan verileri (hesap planı, sequence'lar) uygulayarak oluşturma
  - session_scope(): tek bir atomic transaction için context manager
  - backup_db(): SQLite native backup() API'si ile güvenli anlık yedek
  - rollover_yil(): Yıl sonu devri
"""

import os
import sqlite3
import datetime
from contextlib import contextmanager

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker, Session

from core.models import (
    YearBase, MuhasebeHesabi, MuhasebeHareketi, Sequence, SiparisBaslik,
    DEFAULT_HESAP_PLANI, DEFAULT_SEQUENCES,
)

# Sabit proje dizini: C:\ENTEGRE_MUHASEBE_2026
# Bu dizin, projenin kendisinin bulunduğu köktür (main.py, core/, ui/ burada durur);
# Data/ ve Yedekler/ alt klasörleri de doğrudan bunun altında oluşturulur.
# (Geliştirme/test ortamında farklı bir işletim sisteminde çalıştırmak için
#  ENTEGRE_MUHASEBE_DIR ortam değişkeni ile override edilebilir; üretimde
#  (Windows) bu değişken tanımlı olmadığından her zaman sabit yol kullanılır.)
BASE_DIR = os.environ.get("ENTEGRE_MUHASEBE_DIR", r"C:\ENTEGRE_MUHASEBE_2026")
DATA_DIR = os.path.join(BASE_DIR, "Data")

GECMIS_YIL_KAR_HESABI = "590"
GECMIS_YIL_ZARAR_HESABI = "591"


class DBManager:
    def __init__(self, firma_kodu: str, yil: int):
        self.firma_kodu = firma_kodu
        self.yil = yil
        os.makedirs(DATA_DIR, exist_ok=True)
        self.db_path = os.path.join(DATA_DIR, f"{firma_kodu}_{yil}.db")

        yeni_mi = not os.path.exists(self.db_path)
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        self._SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False)

        if yeni_mi:
            self._olustur_ve_tohumla()

    # ------------------------------------------------------------------
    def _olustur_ve_tohumla(self):
        YearBase.metadata.create_all(self.engine)
        with self.session_scope() as s:
            for kod, ad, sinif in DEFAULT_HESAP_PLANI:
                s.merge(MuhasebeHesabi(hesap_kodu=kod, hesap_adi=ad, hesap_sinifi=sinif))
            for tur, on_ek in DEFAULT_SEQUENCES:
                s.merge(Sequence(belge_turu=tur, mevcut_deger=0, on_ek=on_ek, basamak_sayisi=6))

    # ------------------------------------------------------------------
    @contextmanager
    def session_scope(self):
        """
        Atomic işlemler için context manager.
        Kullanım:
            with db.session_scope() as s:
                s.add(...)
        Hata durumunda otomatik rollback, başarılıysa otomatik commit yapar.
        """
        session: Session = self._SessionFactory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Dönem kilidi kontrolü
    # ------------------------------------------------------------------
    @staticmethod
    def tarih_kilitli_mi(session: Session, tarih: str) -> bool:
        from core.models import DonemKilit
        son_kilit = session.execute(
            select(DonemKilit.kilit_tarihi).order_by(DonemKilit.kilit_tarihi.desc()).limit(1)
        ).scalar_one_or_none()
        if not son_kilit:
            return False
        return tarih <= son_kilit

    # ------------------------------------------------------------------
    # Audit log yardımcı fonksiyonu
    # ------------------------------------------------------------------
    @staticmethod
    def audit_log(session: Session, tablo_adi: str, kayit_id: int, islem: str,
                  kullanici: str, eski_veri: dict | None, yeni_veri: dict | None):
        import json
        from core.models import AuditLog
        session.add(AuditLog(
            tablo_adi=tablo_adi, kayit_id=kayit_id, islem=islem, kullanici=kullanici,
            tarih=datetime.datetime.now(),
            eski_json=json.dumps(eski_veri, ensure_ascii=False, default=str) if eski_veri is not None else None,
            yeni_json=json.dumps(yeni_veri, ensure_ascii=False, default=str) if yeni_veri is not None else None,
        ))

    # ------------------------------------------------------------------
    # Yedekleme (native SQLite backup API - dosya kopyalama YASAK)
    # ------------------------------------------------------------------
    def backup_db(self, hedef_dosya: str):
        kaynak = self.engine.raw_connection()
        hedef = sqlite3.connect(hedef_dosya)
        try:
            kaynak.connection.backup(hedef)
        finally:
            hedef.close()
            kaynak.close()
        return hedef_dosya

    # ------------------------------------------------------------------
    # Yıl Sonu Devri (Rollover)
    # ------------------------------------------------------------------
    def rollover_yil(self, kullanici: str, acik_siparis_karari: str = "tasi"):
        yeni_yil = self.yil + 1

        with self.session_scope() as s:
            bilanco_bakiyeler = s.execute(
                select(
                    MuhasebeHareketi.hesap_kodu,
                    (func.sum(MuhasebeHareketi.borc) - func.sum(MuhasebeHareketi.alacak)).label("net"),
                )
                .join(MuhasebeHesabi, MuhasebeHesabi.hesap_kodu == MuhasebeHareketi.hesap_kodu)
                .where(MuhasebeHesabi.hesap_sinifi.between(1, 5), MuhasebeHareketi.yil == self.yil)
                .group_by(MuhasebeHareketi.hesap_kodu)
            ).all()

            gelir_gider = s.execute(
                select(
                    func.sum(MuhasebeHareketi.alacak).filter(MuhasebeHesabi.hesap_sinifi == 6).label("gelir"),
                    func.sum(MuhasebeHareketi.borc).filter(MuhasebeHesabi.hesap_sinifi == 7).label("gider"),
                )
                .join(MuhasebeHesabi, MuhasebeHesabi.hesap_kodu == MuhasebeHareketi.hesap_kodu)
                .where(MuhasebeHesabi.hesap_sinifi.in_((6, 7)), MuhasebeHareketi.yil == self.yil)
            ).one()

            toplam_gelir = gelir_gider.gelir or 0
            toplam_gider = gelir_gider.gider or 0
            net_sonuc = toplam_gelir - toplam_gider
            kar_zarar_hesabi = GECMIS_YIL_KAR_HESABI if net_sonuc >= 0 else GECMIS_YIL_ZARAR_HESABI

            s.add(MuhasebeHareketi(
                tarih=f"{self.yil}-12-31", hesap_kodu=kar_zarar_hesabi,
                borc=0 if net_sonuc >= 0 else abs(net_sonuc),
                alacak=net_sonuc if net_sonuc >= 0 else 0,
                yil=self.yil, aciklama="Dönem sonu gelir/gider kapanış kaydı",
            ))
            self.audit_log(s, "MuhasebeHareketi", 0, "EKLEME", kullanici,
                            None, {"kar_zarar_hesabi": kar_zarar_hesabi, "net_sonuc": net_sonuc})

            acik_siparisler = s.execute(
                select(SiparisBaslik).where(SiparisBaslik.durum.in_(["Onayli", "KismiSevk"]))
            ).scalars().all()
            acik_siparis_verileri = [
                dict(siparis_no=sp.siparis_no, cari_id=sp.cari_id, para_birimi=sp.para_birimi,
                     kur=sp.kur, vade_gunu=sp.vade_gunu, durum=sp.durum)
                for sp in acik_siparisler
            ]

        yeni_db = DBManager(self.firma_kodu, yeni_yil)

        with yeni_db.session_scope() as s:
            acilis_tarihi = f"{yeni_yil}-01-01"
            for satir in bilanco_bakiyeler:
                if not satir.net:
                    continue
                s.add(MuhasebeHareketi(
                    tarih=acilis_tarihi, hesap_kodu=satir.hesap_kodu,
                    borc=satir.net if satir.net > 0 else 0,
                    alacak=abs(satir.net) if satir.net < 0 else 0,
                    yil=yeni_yil, aciklama="Açılış fişi - devir bakiyesi",
                ))

            if acik_siparis_karari == "tasi":
                for sp in acik_siparis_verileri:
                    s.add(SiparisBaslik(
                        siparis_no=sp["siparis_no"], cari_id=sp["cari_id"],
                        siparis_tarihi=acilis_tarihi, para_birimi=sp["para_birimi"],
                        kur=sp["kur"], vade_gunu=sp["vade_gunu"], durum=sp["durum"],
                        aciklama=f"{self.yil} yılından devir",
                    ))
            # 'iptal' seçilirse: orijinal db'de storno akışı (controllers/shipment_controller.py) çağrılmalı

        return yeni_db.db_path
