"""
master_db.py
--------------
Firma ve kullanıcı bilgilerini tutan MERKEZİ veritabanı (_master.db),
SQLAlchemy ile.

Giriş ekranı akışı bu sınıf üzerinden çalışır:
    1. firmalari_listele()               -> Firma seç (dropdown)
    2. kullanicilari_listele(firma_id)   -> Kullanıcı seç (rolüyle birlikte)
    3. giris_yap(firma_id, kullanici_id, sifre) -> doğrulama

İlk çalıştırmada master db boşsa, sistemin açılabilmesi için bir demo
firma + admin kullanıcı otomatik oluşturulur (kullanıcı: admin / şifre: admin123).
"""

import os
import datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.auth import sifre_hashle, sifre_dogrula
from core.db_manager import DATA_DIR
from core.models_master import MasterBase, Firma, Kullanici

MASTER_DB_PATH = os.path.join(DATA_DIR, "_master.db")


class GirisHatasi(Exception):
    """Hatalı kullanıcı/şifre veya pasif hesap gibi giriş hatalarında fırlatılır."""


class MasterDB:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        yeni_mi = not os.path.exists(MASTER_DB_PATH)
        self.engine = create_engine(f"sqlite:///{MASTER_DB_PATH}")
        self._SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False)

        if yeni_mi:
            MasterBase.metadata.create_all(self.engine)
            self._ilk_calistirma_seed()

    def _ilk_calistirma_seed(self):
        with self._SessionFactory() as s:
            firma = Firma(firma_kodu="DEMO", firma_adi="Demo Firma A.Ş.")
            s.add(firma)
            s.flush()
            sifre_hash, salt = sifre_hashle("admin123")
            s.add(Kullanici(
                firma_id=firma.id, kullanici_adi="admin", ad_soyad="Sistem Yöneticisi",
                sifre_hash=sifre_hash, salt=salt, rol="Admin",
                olusturma_tarihi=datetime.datetime.now(),
            ))
            s.commit()

    # ------------------------------------------------------------------
    # Firma işlemleri
    # ------------------------------------------------------------------
    def firmalari_listele(self, sadece_aktif: bool = True) -> list[Firma]:
        with self._SessionFactory() as s:
            sorgu = select(Firma)
            if sadece_aktif:
                sorgu = sorgu.where(Firma.aktif_mi.is_(True))
            return list(s.execute(sorgu.order_by(Firma.firma_adi)).scalars().all())

    def firma_ekle(self, firma_kodu: str, firma_adi: str, vergi_no: str = "", adres: str = "") -> int:
        with self._SessionFactory() as s:
            firma = Firma(firma_kodu=firma_kodu, firma_adi=firma_adi, vergi_no=vergi_no, adres=adres)
            s.add(firma)
            s.commit()
            return firma.id

    # ------------------------------------------------------------------
    # Kullanıcı işlemleri
    # ------------------------------------------------------------------
    def kullanicilari_listele(self, firma_id: int, sadece_aktif: bool = True) -> list[Kullanici]:
        with self._SessionFactory() as s:
            sorgu = select(Kullanici).where(Kullanici.firma_id == firma_id)
            if sadece_aktif:
                sorgu = sorgu.where(Kullanici.aktif_mi.is_(True))
            return list(s.execute(sorgu.order_by(Kullanici.rol, Kullanici.kullanici_adi)).scalars().all())

    def kullanici_ekle(self, firma_id: int, kullanici_adi: str, sifre: str,
                        rol: str, ad_soyad: str = "") -> int:
        sifre_hash, salt = sifre_hashle(sifre)
        with self._SessionFactory() as s:
            kullanici = Kullanici(
                firma_id=firma_id, kullanici_adi=kullanici_adi, ad_soyad=ad_soyad,
                sifre_hash=sifre_hash, salt=salt, rol=rol,
                olusturma_tarihi=datetime.datetime.now(),
            )
            s.add(kullanici)
            s.commit()
            return kullanici.id

    # ------------------------------------------------------------------
    # Giriş doğrulama
    # ------------------------------------------------------------------
    def giris_yap(self, firma_id: int, kullanici_id: int, sifre: str) -> Kullanici:
        with self._SessionFactory() as s:
            kullanici = s.execute(
                select(Kullanici).where(Kullanici.id == kullanici_id, Kullanici.firma_id == firma_id)
            ).scalar_one_or_none()
            if not kullanici:
                raise GirisHatasi("Kullanıcı bulunamadı.")
            if not kullanici.aktif_mi:
                raise GirisHatasi("Bu kullanıcı hesabı pasif durumda.")
            if not sifre_dogrula(sifre, kullanici.sifre_hash, kullanici.salt):
                raise GirisHatasi("Şifre hatalı.")

            kullanici.son_giris_tarihi = datetime.datetime.now()
            s.commit()
            s.refresh(kullanici)
            return kullanici
