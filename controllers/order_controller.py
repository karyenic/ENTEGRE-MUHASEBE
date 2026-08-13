"""
order_controller.py
----------------------
Sipariş yaşam döngüsü: Taslak -> Onayli -> (sevkiyatlarla) KismiSevk/TamSevk
                                 -> Iptal (sadece Taslak'ken "Geri Tarama/Vazgeç")

Not: Sipariş kalemlerindeki birim_fiyat/maliyet, KAYIT ANINDA StokKart'tan
snapshot olarak alınır (kullanıcı isterse ekranda değiştirebilir - bu
değer zaten UI'dan geldiği için burada sadece "verilmemişse StokKart'tan
doldur" davranışı uygulanır).
"""

import datetime
from sqlalchemy import select

from core.db_manager import DBManager
from core.models import SiparisBaslik, SiparisKalemi, StokKart
from core.sequence import get_next_number


def taslak_siparis_olustur(db: DBManager, cari_id: int, kalemler: list[dict],
                            kullanici_id: int, kullanici_adi: str,
                            siparis_tarihi: str | None = None,
                            para_birimi: str = "TRY", kur: float = 1.0,
                            vade_gunu: int = 0) -> int:
    """
    kalemler: [{"stok_id": int, "miktar": float, "birim_fiyat": float|None,
                "kdv_orani": float|None}, ...]
    birim_fiyat/kdv_orani verilmezse StokKart'taki güncel değerler kullanılır.
    Döner: yeni SiparisBaslik.id
    """
    tarih = siparis_tarihi or datetime.date.today().isoformat()

    with db.session_scope() as s:
        siparis_no = get_next_number(s, "Siparis", kullanici_adi)

        siparis = SiparisBaslik(
            siparis_no=siparis_no, cari_id=cari_id, siparis_tarihi=tarih,
            para_birimi=para_birimi, kur=kur, vade_gunu=vade_gunu,
            durum="Taslak", olusturan_kullanici_id=kullanici_id,
        )
        s.add(siparis)
        s.flush()   # siparis.id almak için

        for kalem in kalemler:
            stok = s.get(StokKart, kalem["stok_id"])
            if not stok:
                raise ValueError(f"Stok bulunamadı: {kalem['stok_id']}")
            miktar = kalem["miktar"]
            if miktar <= 0:
                raise ValueError("Sipariş miktarı sıfırdan büyük olmalıdır.")

            birim_fiyat = kalem.get("birim_fiyat")
            if birim_fiyat is None:
                birim_fiyat = stok.guncel_satis_fiyati
            kdv_orani = kalem.get("kdv_orani")
            if kdv_orani is None:
                kdv_orani = stok.kdv_orani

            s.add(SiparisKalemi(
                siparis_id=siparis.id, stok_id=stok.id, sip_miktar=miktar,
                sevk_edilen_miktar=0, kalan_miktar=miktar,
                birim_fiyat=birim_fiyat, maliyet=stok.guncel_maliyet,
                kdv_orani=kdv_orani,
            ))

        db.audit_log(s, "SiparisBaslik", siparis.id, "EKLEME", kullanici_adi,
                      None, {"siparis_no": siparis_no, "durum": "Taslak"})
        return siparis.id


def taslak_guncelle(db: DBManager, siparis_id: int, kalemler: list[dict], kullanici_adi: str):
    """
    Sadece durum='Taslak' iken çağrılabilir (liste ekranındaki "Düzenle
    sadece taslaksa" kuralı). Mevcut kalemleri SİLİP yeniden oluşturur
    (taslak aşamasında henüz hiçbir sevkiyat/muhasebe etkisi yok, bu
    yüzden bu basit yaklaşım güvenlidir).
    """
    with db.session_scope() as s:
        siparis = s.get(SiparisBaslik, siparis_id)
        if not siparis:
            raise ValueError("Sipariş bulunamadı.")
        if siparis.durum != "Taslak":
            raise ValueError("Sadece 'Taslak' durumundaki siparişler düzenlenebilir.")

        eski_kalemler = [{"stok_id": k.stok_id, "miktar": k.sip_miktar} for k in siparis.kalemler]
        for k in list(siparis.kalemler):
            s.delete(k)
        s.flush()

        for kalem in kalemler:
            stok = s.get(StokKart, kalem["stok_id"])
            if not stok:
                raise ValueError(f"Stok bulunamadı: {kalem['stok_id']}")
            miktar = kalem["miktar"]
            birim_fiyat = kalem.get("birim_fiyat", stok.guncel_satis_fiyati)
            kdv_orani = kalem.get("kdv_orani", stok.kdv_orani)
            s.add(SiparisKalemi(
                siparis_id=siparis.id, stok_id=stok.id, sip_miktar=miktar,
                sevk_edilen_miktar=0, kalan_miktar=miktar,
                birim_fiyat=birim_fiyat, maliyet=stok.guncel_maliyet, kdv_orani=kdv_orani,
            ))

        db.audit_log(s, "SiparisBaslik", siparis.id, "GUNCELLEME", kullanici_adi,
                      {"kalemler": eski_kalemler}, {"kalemler": kalemler})


def taslak_onayla(db: DBManager, siparis_id: int, kullanici_adi: str):
    """Taslak -> Onayli. Onaylandıktan sonra sevkiyat başlatılabilir."""
    with db.session_scope() as s:
        siparis = s.get(SiparisBaslik, siparis_id)
        if not siparis:
            raise ValueError("Sipariş bulunamadı.")
        if siparis.durum != "Taslak":
            raise ValueError("Sadece 'Taslak' durumundaki siparişler onaylanabilir.")
        if not siparis.kalemler:
            raise ValueError("En az bir kalem olmadan sipariş onaylanamaz.")

        siparis.durum = "Onayli"
        db.audit_log(s, "SiparisBaslik", siparis.id, "GUNCELLEME", kullanici_adi,
                      {"durum": "Taslak"}, {"durum": "Onayli"})


def taslak_vazgec(db: DBManager, siparis_id: int, kullanici_adi: str):
    """
    'Geri Tarama' (bu ekranda anlamı): kaydedilmemiş bir taslağı iptal eder.
    Henüz hiçbir stok/muhasebe etkisi olmadığından basitçe durum='Iptal' yapılır.
    """
    with db.session_scope() as s:
        siparis = s.get(SiparisBaslik, siparis_id)
        if not siparis:
            raise ValueError("Sipariş bulunamadı.")
        if siparis.durum != "Taslak":
            raise ValueError("Sadece 'Taslak' durumundaki siparişler bu şekilde iptal edilebilir "
                              "(onaylanmış/sevk edilmiş siparişler için storno akışı kullanılmalı).")
        siparis.durum = "Iptal"
        db.audit_log(s, "SiparisBaslik", siparis.id, "GUNCELLEME", kullanici_adi,
                      {"durum": "Taslak"}, {"durum": "Iptal"})


def siparisleri_filtrele(db: DBManager, cari_id: int | None = None,
                          durum: str | None = None,
                          tarih_bas: str | None = None, tarih_son: str | None = None):
    """Sipariş Liste ekranındaki filtreler için."""
    with db.session_scope() as s:
        sorgu = select(SiparisBaslik)
        if cari_id:
            sorgu = sorgu.where(SiparisBaslik.cari_id == cari_id)
        if durum:
            sorgu = sorgu.where(SiparisBaslik.durum == durum)
        if tarih_bas:
            sorgu = sorgu.where(SiparisBaslik.siparis_tarihi >= tarih_bas)
        if tarih_son:
            sorgu = sorgu.where(SiparisBaslik.siparis_tarihi <= tarih_son)
        return list(s.execute(sorgu.order_by(SiparisBaslik.siparis_tarihi.desc())).scalars().all())
