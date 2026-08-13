"""
models.py
-----------
Her firma+yıl için AYRI bir SQLite dosyasında (FIRMA_YIL.db) kullanılan
SQLAlchemy ORM modelleri.

ÖNEMLİ: Firma ve Kullanıcı modelleri BURADA DEĞİL, models_master.py'dedir
(C:\\ENTEGRE_MUHASEBE_2026\\Data\\_master.db). Bu yüzden bu dosyadaki
"...kullanici_id" alanları düz Integer'dır; SQLite ayrı veritabanı
dosyaları arasında FOREIGN KEY kısıtını desteklemez.

Belge akışı:
    SiparisBaslik (Taslak -> Onayli -> KismiSevk/TamSevk)
        -> Sevkiyat (Hazir -> Onaylandi)   [4 göz onayı]
            -> IrsaliyeBaslik (sevkiyat türüne göre opsiyonel)
                -> FaturaBaslik (irsaliyeden VEYA doğrudan, siparişsiz de olabilir)
                    -> CariHareket + StokHareket + MuhasebeHareketi
"""

import datetime
import uuid
from sqlalchemy import (
    String, Integer, Float, Boolean, ForeignKey, DateTime, CheckConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class YearBase(DeclarativeBase):
    pass


# =====================================================================
# CARİ / STOK
# =====================================================================
class CariKart(YearBase):
    __tablename__ = "cari_kartlar"

    id: Mapped[int] = mapped_column(primary_key=True)
    cari_kodu: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    unvan: Mapped[str] = mapped_column(String, nullable=False)
    tip: Mapped[str] = mapped_column(String, nullable=False)   # Musteri/Tedarikci/Musteri-Tedarikci
    vergi_no: Mapped[str | None] = mapped_column(String)
    efatura_mukellefi_mi: Mapped[bool] = mapped_column(Boolean, default=False)
    bakiye: Mapped[float] = mapped_column(Float, default=0)   # + : cari bize borçlu, - : biz cariye borçluyuz
    aktif_mi: Mapped[bool] = mapped_column(Boolean, default=True)


class StokKart(YearBase):
    __tablename__ = "stok_kartlar"

    id: Mapped[int] = mapped_column(primary_key=True)
    stok_kodu: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    stok_adi: Mapped[str] = mapped_column(String, nullable=False)
    birim: Mapped[str] = mapped_column(String, default="Adet")
    guncel_satis_fiyati: Mapped[float] = mapped_column(Float, default=0)
    guncel_maliyet: Mapped[float] = mapped_column(Float, default=0)
    kdv_orani: Mapped[float] = mapped_column(Float, default=20)
    kritik_stok: Mapped[float] = mapped_column(Float, default=0)
    mevcut_miktar: Mapped[float] = mapped_column(Float, default=0)
    rezerve_miktar: Mapped[float] = mapped_column(Float, default=0)
    aktif_mi: Mapped[bool] = mapped_column(Boolean, default=True)


class StokHareket(YearBase):
    __tablename__ = "stok_hareketleri"

    id: Mapped[int] = mapped_column(primary_key=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlar.id"), nullable=False)
    tarih: Mapped[str] = mapped_column(String, nullable=False)
    hareket_tipi: Mapped[str] = mapped_column(String, nullable=False)  # Giris/Cikis/Rezerve/RezerveIptal/Storno
    miktar: Mapped[float] = mapped_column(Float, nullable=False)
    referans_tablo: Mapped[str | None] = mapped_column(String)
    referans_id: Mapped[int | None] = mapped_column(Integer)
    aciklama: Mapped[str | None] = mapped_column(String)


# =====================================================================
# EVRAK NUMARALANDIRMA (admin tarafından başlatılabilir/düzeltilebilir)
# =====================================================================
class Sequence(YearBase):
    """
    Her belge türü için ayrı, admin tarafından ayarlanabilir sayaç.
    get_next_number() (core/sequence.py) bu tabloyu SERIALIZABLE bir
    transaction içinde okuyup arttırarak concurrency-safe numara üretir.
    Admin, mevcut_deger'i Ayarlar ekranından elle değiştirebilir
    (örn. yıl başında "1"den başlat, ya da manuel bir düzeltme yap).
    """
    __tablename__ = "sequences"

    belge_turu: Mapped[str] = mapped_column(String, primary_key=True)  # 'Siparis','Sevkiyat','Irsaliye','Fatura'
    mevcut_deger: Mapped[int] = mapped_column(Integer, default=0)
    on_ek: Mapped[str] = mapped_column(String, default="")             # örn 'SIP-', 'FTR-'
    basamak_sayisi: Mapped[int] = mapped_column(Integer, default=6)
    son_guncelleyen: Mapped[str | None] = mapped_column(String)
    son_guncelleme_tarihi: Mapped[datetime.datetime | None] = mapped_column(DateTime)


# =====================================================================
# SİPARİŞ
# =====================================================================
class SiparisBaslik(YearBase):
    __tablename__ = "siparis_baslik"
    __table_args__ = (
        CheckConstraint("durum IN ('Taslak','Onayli','KismiSevk','TamSevk','Iptal')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    siparis_no: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False)
    siparis_tarihi: Mapped[str] = mapped_column(String, nullable=False)
    para_birimi: Mapped[str] = mapped_column(String, default="TRY")
    kur: Mapped[float] = mapped_column(Float, default=1.0)   # Döviz çıpası - sabit kalır
    vade_gunu: Mapped[int] = mapped_column(Integer, default=0)
    durum: Mapped[str] = mapped_column(String, default="Taslak")
    olusturan_kullanici_id: Mapped[int | None] = mapped_column(Integer)  # master db Kullanici.id
    aciklama: Mapped[str | None] = mapped_column(String)

    kalemler: Mapped[list["SiparisKalemi"]] = relationship(back_populates="siparis")


class SiparisKalemi(YearBase):
    __tablename__ = "siparis_kalemleri"

    id: Mapped[int] = mapped_column(primary_key=True)
    siparis_id: Mapped[int] = mapped_column(ForeignKey("siparis_baslik.id"), nullable=False)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlar.id"), nullable=False)
    sip_miktar: Mapped[float] = mapped_column(Float, nullable=False)
    sevk_edilen_miktar: Mapped[float] = mapped_column(Float, default=0)
    kalan_miktar: Mapped[float] = mapped_column(Float, nullable=False)
    birim_fiyat: Mapped[float] = mapped_column(Float, nullable=False)   # SNAPSHOT
    maliyet: Mapped[float] = mapped_column(Float, nullable=False)       # SNAPSHOT
    kdv_orani: Mapped[float] = mapped_column(Float, default=20)

    siparis: Mapped["SiparisBaslik"] = relationship(back_populates="kalemler")


# =====================================================================
# SEVKİYAT (4 göz onayı: Hazir -> Onaylandi)
# =====================================================================
class Sevkiyat(YearBase):
    __tablename__ = "sevkiyatlar"
    __table_args__ = (
        CheckConstraint("durum IN ('Hazir','Onaylandi','Stornolandi')"),
        CheckConstraint("sevkiyat_turu IN ('SadeceIrsaliye','IrsaliyeVeFatura','SadeceFatura')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sevkiyat_no: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    siparis_id: Mapped[int] = mapped_column(ForeignKey("siparis_baslik.id"), nullable=False)
    tarih: Mapped[str] = mapped_column(String, nullable=False)
    sevkiyat_turu: Mapped[str] = mapped_column(String, default="IrsaliyeVeFatura")
    durum: Mapped[str] = mapped_column(String, default="Hazir")
    hazirlayan_kullanici_id: Mapped[int | None] = mapped_column(Integer)
    onaylayan_kullanici_id: Mapped[int | None] = mapped_column(Integer)
    onay_tarihi: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    olaganustu_duzeltme: Mapped[bool] = mapped_column(Boolean, default=False)
    storno_id: Mapped[int | None] = mapped_column(ForeignKey("sevkiyatlar.id"))


class SevkiyatKalemi(YearBase):
    __tablename__ = "sevkiyat_kalemleri"

    id: Mapped[int] = mapped_column(primary_key=True)
    sevkiyat_id: Mapped[int] = mapped_column(ForeignKey("sevkiyatlar.id"), nullable=False)
    siparis_kalemi_id: Mapped[int] = mapped_column(ForeignKey("siparis_kalemleri.id"), nullable=False)
    sevk_miktar: Mapped[float] = mapped_column(Float, nullable=False)   # storno satırında negatif olabilir
    fiyat: Mapped[float] = mapped_column(Float, nullable=False)         # sipariş satırından kopyalanan snapshot


# =====================================================================
# İRSALİYE (ayrı tablo - faturadan bağımsız numaralandırma + e-irsaliye takibi)
# =====================================================================
class IrsaliyeBaslik(YearBase):
    __tablename__ = "irsaliye_baslik"
    __table_args__ = (
        CheckConstraint("durum IN ('Kesildi','Stornolandi')"),
        CheckConstraint("efatura_durumu IN ('Beklemede','Gonderildi','Hata','GerekliDegil')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    irsaliye_no: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    sevkiyat_id: Mapped[int] = mapped_column(ForeignKey("sevkiyatlar.id"), nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False)
    tarih: Mapped[str] = mapped_column(String, nullable=False)
    durum: Mapped[str] = mapped_column(String, default="Kesildi")
    storno_id: Mapped[int | None] = mapped_column(ForeignKey("irsaliye_baslik.id"))
    efatura_durumu: Mapped[str] = mapped_column(String, default="Beklemede")
    efatura_uuid: Mapped[str | None] = mapped_column(String)   # entegratörden dönen GİB UUID
    client_uuid: Mapped[str] = mapped_column(String, unique=True, default=lambda: str(uuid.uuid4()))


class IrsaliyeDetay(YearBase):
    __tablename__ = "irsaliye_detay"

    id: Mapped[int] = mapped_column(primary_key=True)
    irsaliye_id: Mapped[int] = mapped_column(ForeignKey("irsaliye_baslik.id"), nullable=False)
    sevkiyat_kalemi_id: Mapped[int] = mapped_column(ForeignKey("sevkiyat_kalemleri.id"), nullable=False)
    miktar: Mapped[float] = mapped_column(Float, nullable=False)


# =====================================================================
# FATURA (siparişten/sevkiyattan VEYA doğrudan - siparişsiz - kesilebilir)
# =====================================================================
class FaturaBaslik(YearBase):
    __tablename__ = "fatura_baslik"
    __table_args__ = (
        CheckConstraint("durum IN ('Kesildi','Stornolandi')"),
        CheckConstraint("efatura_durumu IN ('Beklemede','Gonderildi','Hata','GerekliDegil')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fatura_no: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    irsaliye_id: Mapped[int | None] = mapped_column(ForeignKey("irsaliye_baslik.id"))  # opsiyonel
    sevkiyat_id: Mapped[int | None] = mapped_column(ForeignKey("sevkiyatlar.id"))       # opsiyonel
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False)
    tarih: Mapped[str] = mapped_column(String, nullable=False)
    kur: Mapped[float] = mapped_column(Float, default=1.0)
    kur_farki: Mapped[float] = mapped_column(Float, default=0)
    toplam_tutar: Mapped[float] = mapped_column(Float, nullable=False)
    kdv_tutari: Mapped[float] = mapped_column(Float, nullable=False)
    durum: Mapped[str] = mapped_column(String, default="Kesildi")
    storno_id: Mapped[int | None] = mapped_column(ForeignKey("fatura_baslik.id"))
    efatura_durumu: Mapped[str] = mapped_column(String, default="Beklemede")
    efatura_uuid: Mapped[str | None] = mapped_column(String)
    client_uuid: Mapped[str] = mapped_column(String, unique=True, default=lambda: str(uuid.uuid4()))

    kalemler: Mapped[list["FaturaDetay"]] = relationship(back_populates="fatura")


class FaturaDetay(YearBase):
    """
    stok_id + miktar + fiyat DOĞRUDAN burada tutulur (sevkiyat_kalemi_id
    OPSİYONELDİR) ki "sipariş/sevkiyat olmadan doğrudan fatura" akışı da
    aynı tabloyu kullanabilsin.
    """
    __tablename__ = "fatura_detay"

    id: Mapped[int] = mapped_column(primary_key=True)
    fatura_id: Mapped[int] = mapped_column(ForeignKey("fatura_baslik.id"), nullable=False)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlar.id"), nullable=False)
    sevkiyat_kalemi_id: Mapped[int | None] = mapped_column(ForeignKey("sevkiyat_kalemleri.id"))
    miktar: Mapped[float] = mapped_column(Float, nullable=False)
    birim_fiyat: Mapped[float] = mapped_column(Float, nullable=False)
    kdv_orani: Mapped[float] = mapped_column(Float, nullable=False)
    satir_toplami: Mapped[float] = mapped_column(Float, nullable=False)

    fatura: Mapped["FaturaBaslik"] = relationship(back_populates="kalemler")


# =====================================================================
# CARİ HAREKET (ayrı, sorgulanabilir hareket tablosu)
# =====================================================================
class CariHareket(YearBase):
    __tablename__ = "cari_hareketleri"
    __table_args__ = (CheckConstraint("hareket_tipi IN ('Borc','Alacak')"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False)
    tarih: Mapped[str] = mapped_column(String, nullable=False)
    hareket_tipi: Mapped[str] = mapped_column(String, nullable=False)
    tutar: Mapped[float] = mapped_column(Float, nullable=False)
    referans_tablo: Mapped[str | None] = mapped_column(String)
    referans_id: Mapped[int | None] = mapped_column(Integer)
    aciklama: Mapped[str | None] = mapped_column(String)


# =====================================================================
# MUHASEBE
# =====================================================================
class MuhasebeHesabi(YearBase):
    __tablename__ = "muhasebe_hesaplari"

    hesap_kodu: Mapped[str] = mapped_column(String, primary_key=True)
    hesap_adi: Mapped[str] = mapped_column(String, nullable=False)
    hesap_sinifi: Mapped[int] = mapped_column(Integer, nullable=False)


class MuhasebeHareketi(YearBase):
    __tablename__ = "muhasebe_hareketleri"

    id: Mapped[int] = mapped_column(primary_key=True)
    tarih: Mapped[str] = mapped_column(String, nullable=False)
    hesap_kodu: Mapped[str] = mapped_column(ForeignKey("muhasebe_hesaplari.hesap_kodu"), nullable=False)
    borc: Mapped[float] = mapped_column(Float, default=0)
    alacak: Mapped[float] = mapped_column(Float, default=0)
    yil: Mapped[int] = mapped_column(Integer, nullable=False)
    referans_tablo: Mapped[str | None] = mapped_column(String)
    referans_id: Mapped[int | None] = mapped_column(Integer)
    aciklama: Mapped[str | None] = mapped_column(String)
    storno_mu: Mapped[bool] = mapped_column(Boolean, default=False)


class DonemKilit(YearBase):
    __tablename__ = "donem_kilit"

    id: Mapped[int] = mapped_column(primary_key=True)
    kilit_tarihi: Mapped[str] = mapped_column(String, unique=True, nullable=False)


class AuditLog(YearBase):
    __tablename__ = "audit_log"
    __table_args__ = (CheckConstraint("islem IN ('EKLEME','GUNCELLEME','STORNO')"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tablo_adi: Mapped[str] = mapped_column(String, nullable=False)
    kayit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    islem: Mapped[str] = mapped_column(String, nullable=False)
    kullanici: Mapped[str] = mapped_column(String, nullable=False)
    tarih: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.now)
    eski_json: Mapped[str | None] = mapped_column(String)
    yeni_json: Mapped[str | None] = mapped_column(String)


DEFAULT_HESAP_PLANI = [
    ("120", "Alıcılar", 1),
    ("391", "Hesaplanan KDV", 1),
    ("590", "Dönem Net Karı", 5),
    ("591", "Dönem Net Zararı", 5),
    ("600", "Yurtiçi Satışlar", 6),
    ("621", "Satılan Ticari Mallar Maliyeti", 7),
    ("646", "Kambiyo Karları", 6),
    ("656", "Kambiyo Zararları", 7),
]

DEFAULT_SEQUENCES = [
    ("Siparis", "SIP-"),
    ("Sevkiyat", "SVK-"),
    ("Irsaliye", "IRS-"),
    ("Fatura", "FTR-"),
]
