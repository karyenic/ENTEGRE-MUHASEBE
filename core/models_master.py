"""
models_master.py
-------------------
Merkezi (master) veritabanı için SQLAlchemy ORM modelleri.
Konum: C:\\ENTEGRE_MUHASEBE_2026\\Data\\_master.db

Bu modeller TÜM firmalar için ortaktır: Firma tanımları ve kullanıcılar
burada yaşar, yıllık db'lerde YAŞAMAZ (bkz. models.py başlığındaki not).
"""

import datetime
from sqlalchemy import String, Integer, Boolean, ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class MasterBase(DeclarativeBase):
    pass


class Firma(MasterBase):
    __tablename__ = "firmalar"

    id: Mapped[int] = mapped_column(primary_key=True)
    firma_kodu: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    firma_adi: Mapped[str] = mapped_column(String, nullable=False)
    vergi_no: Mapped[str | None] = mapped_column(String)
    adres: Mapped[str | None] = mapped_column(String)
    aktif_mi: Mapped[bool] = mapped_column(Boolean, default=True)

    kullanicilar: Mapped[list["Kullanici"]] = relationship(back_populates="firma")


class Kullanici(MasterBase):
    __tablename__ = "kullanicilar"
    __table_args__ = (UniqueConstraint("firma_id", "kullanici_adi"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), nullable=False)
    kullanici_adi: Mapped[str] = mapped_column(String, nullable=False)
    ad_soyad: Mapped[str | None] = mapped_column(String)
    sifre_hash: Mapped[str] = mapped_column(String, nullable=False)
    salt: Mapped[str] = mapped_column(String, nullable=False)
    rol: Mapped[str] = mapped_column(String, nullable=False)   # Admin/Muhasebeci/Depo/User
    aktif_mi: Mapped[bool] = mapped_column(Boolean, default=True)
    olusturma_tarihi: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    son_giris_tarihi: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    firma: Mapped["Firma"] = relationship(back_populates="kullanicilar")


class SistemAyari(MasterBase):
    __tablename__ = "sistem_ayarlari"

    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), primary_key=True)
    anahtar: Mapped[str] = mapped_column(String, primary_key=True)
    deger: Mapped[str | None] = mapped_column(String)   # JSON string
