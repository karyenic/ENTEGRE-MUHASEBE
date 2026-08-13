"""
invoice_controller.py
------------------------
Fatura ekranının "B) Direkt" akışı: sipariş/sevkiyat OLMADAN doğrudan
fatura kesme. (A) Siparişten/sevkiyattan gelen akış zaten
shipment_controller.sevkiyat_onayla() içinde ele alınıyor.

Direkt faturada da stok düşer (satış gerçekleştiği için), ama sipariş
kaleminden düşecek bir "kalan miktar" olmadığından doğrudan StokKart
üzerinden race-condition korumalı düşülür.
"""

import datetime
from sqlalchemy import select, update

from core.db_manager import DBManager
from core.models import StokKart, StokHareket, FaturaBaslik, FaturaDetay, CariHareket, CariKart, MuhasebeHareketi
from core.sequence import get_next_number

KDV_VARSAYILAN = 20.0
SATIS_GELIR_HESABI = "600"
SATIS_MALIYET_HESABI = "621"
KDV_HESAP_HESABI = "391"
CARI_HESAP_KODU = "120"


def fatura_olustur_direkt(db: DBManager, cari_id: int, kalemler: list[dict],
                          kullanici_id: int, kullanici_adi: str,
                          tarih: str | None = None, kur: float = 1.0,
                          efatura_adapter=None) -> dict:
    """
    kalemler: [{"stok_id": int, "miktar": float, "birim_fiyat": float|None,
                "kdv_orani": float|None}, ...]
    Sipariş/sevkiyat olmadan doğrudan fatura kesilir; stok anında düşer.
    """
    tarih = tarih or datetime.date.today().isoformat()

    with db.session_scope() as s:
        if db.tarih_kilitli_mi(s, tarih):
            raise ValueError("Bu tarih kapalı bir dönemde. Doğrudan fatura girilemez.")

        fatura_no = get_next_number(s, "Fatura", kullanici_adi)

        toplam_satis = toplam_kdv = toplam_maliyet = 0.0
        fatura_kalemleri_veri = []

        for kalem in kalemler:
            stok = s.get(StokKart, kalem["stok_id"])
            if not stok:
                raise ValueError(f"Stok bulunamadı: {kalem['stok_id']}")
            miktar = kalem["miktar"]
            if miktar <= 0:
                raise ValueError("Miktar sıfırdan büyük olmalıdır.")

            birim_fiyat = kalem.get("birim_fiyat") or stok.guncel_satis_fiyati
            kdv_orani = kalem.get("kdv_orani") or stok.kdv_orani or KDV_VARSAYILAN

            # --- Race condition korumalı doğrudan stok düşümü ---
            sonuc = s.execute(
                update(StokKart)
                .where(StokKart.id == stok.id,
                       (StokKart.mevcut_miktar - StokKart.rezerve_miktar) >= miktar)
                .values(mevcut_miktar=StokKart.mevcut_miktar - miktar)
            )
            if sonuc.rowcount == 0:
                raise ValueError(f"Stok ID {stok.id} için yeterli kullanılabilir stok yok.")

            s.add(StokHareket(
                stok_id=stok.id, tarih=tarih, hareket_tipi="Cikis", miktar=miktar,
                referans_tablo="FaturaDetay", referans_id=None,
                aciklama="Doğrudan fatura - stok çıkışı",
            ))

            satir_tutari = miktar * birim_fiyat * kur
            satir_kdv = satir_tutari * (kdv_orani / 100.0)
            satir_maliyet = miktar * stok.guncel_maliyet * kur

            toplam_satis += satir_tutari
            toplam_kdv += satir_kdv
            toplam_maliyet += satir_maliyet

            fatura_kalemleri_veri.append({
                "stok_id": stok.id, "miktar": miktar, "birim_fiyat": birim_fiyat,
                "kdv_orani": kdv_orani, "satir_toplami": satir_tutari,
            })

        fatura = FaturaBaslik(
            fatura_no=fatura_no, irsaliye_id=None, sevkiyat_id=None, cari_id=cari_id,
            tarih=tarih, kur=kur, kur_farki=0, toplam_tutar=toplam_satis,
            kdv_tutari=toplam_kdv, durum="Kesildi",
        )
        s.add(fatura)
        s.flush()

        for k in fatura_kalemleri_veri:
            s.add(FaturaDetay(
                fatura_id=fatura.id, stok_id=k["stok_id"], sevkiyat_kalemi_id=None,
                miktar=k["miktar"], birim_fiyat=k["birim_fiyat"],
                kdv_orani=k["kdv_orani"], satir_toplami=k["satir_toplami"],
            ))

        if efatura_adapter:
            sonuc_ef = efatura_adapter.fatura_gonder(
                {"fatura_no": fatura_no, "cari_id": cari_id}, fatura.client_uuid
            )
            fatura.efatura_durumu = sonuc_ef.durum
            fatura.efatura_uuid = sonuc_ef.efatura_uuid

        toplam_borc = toplam_satis + toplam_kdv
        s.add(CariHareket(
            cari_id=cari_id, tarih=tarih, hareket_tipi="Borc", tutar=toplam_borc,
            referans_tablo="FaturaBaslik", referans_id=fatura.id,
            aciklama="Doğrudan fatura - alıcı borcu",
        ))
        cari = s.get(CariKart, cari_id)
        cari.bakiye += toplam_borc

        yil = int(tarih[:4])
        kayitlar = [
            (CARI_HESAP_KODU, toplam_borc, 0, "Doğrudan fatura - alıcı borcu"),
            (SATIS_GELIR_HESABI, 0, toplam_satis, "Doğrudan fatura - satış geliri"),
            (KDV_HESAP_HESABI, 0, toplam_kdv, "Doğrudan fatura - hesaplanan KDV"),
            (SATIS_MALIYET_HESABI, toplam_maliyet, 0, "Satılan malın maliyeti"),
        ]
        for hesap, borc, alacak, aciklama in kayitlar:
            s.add(MuhasebeHareketi(
                tarih=tarih, hesap_kodu=hesap, borc=borc, alacak=alacak, yil=yil,
                referans_tablo="FaturaBaslik", referans_id=fatura.id, aciklama=aciklama,
            ))

        db.audit_log(s, "FaturaBaslik", fatura.id, "EKLEME", kullanici_adi,
                      None, {"fatura_no": fatura_no, "tutar": toplam_borc, "direkt": True})

        return {
            "fatura_id": fatura.id, "fatura_no": fatura_no,
            "toplam_satis": toplam_satis, "toplam_kdv": toplam_kdv,
        }


def fatura_storno_direkt(db: DBManager, fatura_id: int, kullanici_id: int, kullanici_adi: str) -> dict:
    """
    SADECE sevkiyat_id=None olan (doğrudan kesilmiş) faturalar için.
    Sevkiyata bağlı faturalar shipment_controller.sevkiyat_storno() ile
    geri alınmalıdır (stok orada sevkiyat üzerinden yönetiliyor).
    """
    with db.session_scope() as s:
        fatura = s.get(FaturaBaslik, fatura_id)
        if not fatura:
            raise ValueError("Fatura bulunamadı.")
        if fatura.sevkiyat_id is not None:
            raise ValueError(
                "Bu fatura bir sevkiyata bağlı. Storno için shipment_controller.sevkiyat_storno() kullanılmalı."
            )
        if fatura.durum != "Kesildi":
            raise ValueError("Sadece 'Kesildi' durumundaki faturalar storno edilebilir.")

        tarih = datetime.date.today().isoformat()
        storno_fatura_no = get_next_number(s, "Fatura", kullanici_adi)

        storno_fatura = FaturaBaslik(
            fatura_no=storno_fatura_no, cari_id=fatura.cari_id, tarih=tarih,
            kur=fatura.kur, kur_farki=-fatura.kur_farki,
            toplam_tutar=-fatura.toplam_tutar, kdv_tutari=-fatura.kdv_tutari,
            durum="Kesildi", storno_id=fatura.id,
        )
        s.add(storno_fatura)
        s.flush()

        eski_kalemler = list(
            s.execute(select(FaturaDetay).where(FaturaDetay.fatura_id == fatura.id)).scalars()
        )
        for k in eski_kalemler:
            s.execute(
                update(StokKart).where(StokKart.id == k.stok_id)
                .values(mevcut_miktar=StokKart.mevcut_miktar + k.miktar)
            )
            s.add(StokHareket(
                stok_id=k.stok_id, tarih=tarih, hareket_tipi="Storno", miktar=k.miktar,
                referans_tablo="FaturaBaslik", referans_id=storno_fatura.id,
                aciklama=f"Fatura #{fatura.id} stornosu",
            ))
            s.add(FaturaDetay(
                fatura_id=storno_fatura.id, stok_id=k.stok_id, sevkiyat_kalemi_id=None,
                miktar=-k.miktar, birim_fiyat=k.birim_fiyat, kdv_orani=k.kdv_orani,
                satir_toplami=-k.satir_toplami,
            ))

        s.add(CariHareket(
            cari_id=fatura.cari_id, tarih=tarih, hareket_tipi="Alacak",
            tutar=fatura.toplam_tutar + fatura.kdv_tutari,
            referans_tablo="FaturaBaslik", referans_id=storno_fatura.id,
            aciklama=f"Fatura #{fatura.id} stornosu",
        ))
        cari = s.get(CariKart, fatura.cari_id)
        cari.bakiye -= (fatura.toplam_tutar + fatura.kdv_tutari)

        yil = int(tarih[:4])
        eski_muhasebe = list(s.execute(
            select(MuhasebeHareketi).where(
                MuhasebeHareketi.referans_tablo == "FaturaBaslik",
                MuhasebeHareketi.referans_id == fatura.id,
            )
        ).scalars())
        for k in eski_muhasebe:
            s.add(MuhasebeHareketi(
                tarih=tarih, hesap_kodu=k.hesap_kodu, borc=k.alacak, alacak=k.borc,
                yil=yil, referans_tablo="FaturaBaslik", referans_id=storno_fatura.id,
                aciklama=f"Storno: {k.aciklama}", storno_mu=True,
            ))

        fatura.durum = "Stornolandi"

        db.audit_log(s, "FaturaBaslik", fatura.id, "STORNO", kullanici_adi,
                      {"durum": "Kesildi"}, {"durum": "Stornolandi", "storno_fatura_id": storno_fatura.id})

        return {"storno_fatura_id": storno_fatura.id}
