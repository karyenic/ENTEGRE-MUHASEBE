"""
shipment_controller.py
-------------------------
Sevkiyat akışının kalbi:
    sevkiyat_hazirla()  -> Depo: "Hazır" (stok REZERVE edilir, düşmez)
    sevkiyat_onayla()   -> Muhasebeci/Yetkili: "Onayla" (stok kesin düşer,
                            sevkiyat_turu'na göre İrsaliye ve/veya Fatura oluşur)
    sevkiyat_storno()   -> "Geri Tarama" (Sevkiyat İptal/İade süreci):
                            hiçbir kayıt SİLİNMEZ, ters kayıt oluşturulur.
    rezerve_temizle()   -> TTL: X saatten uzun süredir "Hazır" bekleyen
                            sevkiyatların rezerve stoğunu serbest bırakır.
"""

import datetime
from sqlalchemy import select, update

from core.db_manager import DBManager
from core.models import (
    SiparisBaslik, SiparisKalemi, StokKart, StokHareket, Sevkiyat, SevkiyatKalemi,
    IrsaliyeBaslik, IrsaliyeDetay, FaturaBaslik, FaturaDetay, CariHareket, CariKart, MuhasebeHareketi,
)
from core.sequence import get_next_number

KDV_VARSAYILAN = 20.0
SATIS_GELIR_HESABI = "600"
SATIS_MALIYET_HESABI = "621"
KDV_HESAP_HESABI = "391"
CARI_HESAP_KODU = "120"
KUR_FARKI_GELIR_HESABI = "646"
KUR_FARKI_GIDER_HESABI = "656"

SEVKIYAT_TURLERI = ("SadeceIrsaliye", "IrsaliyeVeFatura", "SadeceFatura")


# =====================================================================
# AŞAMA 1: Depo hazırlar (REZERVE eder, düşmez)
# =====================================================================
def sevkiyat_hazirla(db: DBManager, siparis_id: int, sevk_listesi: list[dict],
                      sevkiyat_turu: str, hazirlayan_kullanici_id: int,
                      hazirlayan_kullanici_adi: str) -> int:
    """
    sevk_listesi: [{"siparis_kalemi_id": int, "miktar": float}, ...]
    Döner: yeni Sevkiyat.id
    """
    if sevkiyat_turu not in SEVKIYAT_TURLERI:
        raise ValueError(f"Geçersiz sevkiyat türü: {sevkiyat_turu}")

    with db.session_scope() as s:
        siparis = s.get(SiparisBaslik, siparis_id)
        if not siparis:
            raise ValueError("Sipariş bulunamadı.")
        if siparis.durum not in ("Onayli", "KismiSevk"):
            raise ValueError(
                f"Sadece 'Onayli' veya 'KismiSevk' durumundaki siparişler sevk edilebilir "
                f"(mevcut durum: {siparis.durum})."
            )

        tarih = datetime.date.today().isoformat()
        sevkiyat_no = get_next_number(s, "Sevkiyat", hazirlayan_kullanici_adi)

        sevkiyat = Sevkiyat(
            sevkiyat_no=sevkiyat_no, siparis_id=siparis_id, tarih=tarih,
            sevkiyat_turu=sevkiyat_turu, durum="Hazir",
            hazirlayan_kullanici_id=hazirlayan_kullanici_id,
        )
        s.add(sevkiyat)
        s.flush()

        for satir in sevk_listesi:
            kalem = s.get(SiparisKalemi, satir["siparis_kalemi_id"])
            if not kalem:
                raise ValueError(f"Sipariş kalemi bulunamadı: {satir['siparis_kalemi_id']}")
            miktar = satir["miktar"]
            if miktar <= 0:
                raise ValueError("Sevk miktarı sıfırdan büyük olmalıdır.")
            if miktar > kalem.kalan_miktar:
                raise ValueError(
                    f"Sevk miktarı ({miktar}) kalan sipariş miktarından ({kalem.kalan_miktar}) fazla olamaz."
                )

            # --- Race condition korumalı REZERVE etme ---
            sonuc = s.execute(
                update(StokKart)
                .where(StokKart.id == kalem.stok_id,
                       (StokKart.mevcut_miktar - StokKart.rezerve_miktar) >= miktar)
                .values(rezerve_miktar=StokKart.rezerve_miktar + miktar)
            )
            if sonuc.rowcount == 0:
                raise ValueError(f"Stok ID {kalem.stok_id} için yeterli kullanılabilir stok yok.")

            s.add(SevkiyatKalemi(
                sevkiyat_id=sevkiyat.id, siparis_kalemi_id=kalem.id,
                sevk_miktar=miktar, fiyat=kalem.birim_fiyat,
            ))
            s.add(StokHareket(
                stok_id=kalem.stok_id, tarih=tarih, hareket_tipi="Rezerve", miktar=miktar,
                referans_tablo="Sevkiyat", referans_id=sevkiyat.id,
                aciklama="Depo hazırlık - stok rezerve edildi",
            ))

        db.audit_log(s, "Sevkiyat", sevkiyat.id, "EKLEME", hazirlayan_kullanici_adi,
                      None, {"sevkiyat_no": sevkiyat_no, "durum": "Hazir", "tur": sevkiyat_turu})
        return sevkiyat.id


# =====================================================================
# AŞAMA 2: Onayla & Faturala/İrsaliyele
# =====================================================================
def sevkiyat_onayla(db: DBManager, sevkiyat_id: int, onaylayan_kullanici_id: int,
                     onaylayan_kullanici_adi: str, fatura_kur: float | None = None,
                     olaganustu_duzeltme: bool = False, efatura_adapter=None) -> dict:
    """
    "Onayla" butonu. Atomik olarak:
      1. Stok kesin düşer (rezerveden -> mevcuttan).
      2. Sipariş kalemlerindeki sevk_edilen/kalan güncellenir.
      3. sevkiyat_turu'na göre İrsaliye ve/veya Fatura oluşur (ayrı seri no'larla).
      4. Fatura oluşuyorsa Cari hareket + Muhasebe kayıtları oluşur.
      5. efatura_adapter verilmişse (Ayarlar'dan seçilen), oluşan belge(ler)
         entegratöre gönderilir (idempotency: client_uuid kullanılır).
    """
    with db.session_scope() as s:
        sevkiyat = s.get(Sevkiyat, sevkiyat_id)
        if not sevkiyat:
            raise ValueError("Sevkiyat bulunamadı.")
        if sevkiyat.durum != "Hazir":
            raise ValueError("Sadece 'Hazir' durumundaki sevkiyatlar onaylanabilir.")

        siparis = s.get(SiparisBaslik, sevkiyat.siparis_id)
        tarih = datetime.date.today().isoformat()

        if db.tarih_kilitli_mi(s, tarih) and not olaganustu_duzeltme:
            raise ValueError(
                "Bu tarih kapalı bir dönemde. Admin yetkisi ile 'Olağanüstü Düzeltme' "
                "işaretlemeden kayıt girilemez."
            )

        sevk_kalemleri = list(
            s.execute(select(SevkiyatKalemi).where(SevkiyatKalemi.sevkiyat_id == sevkiyat_id)).scalars()
        )
        if not sevk_kalemleri:
            raise ValueError("Sevkiyat kalemi bulunamadı.")

        siparis_kuru = siparis.kur
        kullanilan_kur = fatura_kur if fatura_kur is not None else siparis_kuru

        # --- 1 & 2: Kesin stok düşümü + sipariş kalemi güncelleme ---
        for sk in sevk_kalemleri:
            kalem = s.get(SiparisKalemi, sk.siparis_kalemi_id)
            miktar = sk.sevk_miktar

            sonuc = s.execute(
                update(StokKart)
                .where(StokKart.id == kalem.stok_id,
                       StokKart.mevcut_miktar >= miktar, StokKart.rezerve_miktar >= miktar)
                .values(mevcut_miktar=StokKart.mevcut_miktar - miktar,
                        rezerve_miktar=StokKart.rezerve_miktar - miktar)
            )
            if sonuc.rowcount == 0:
                raise ValueError(f"Stok tutarsızlığı: Stok ID {kalem.stok_id} için düşüm yapılamadı.")

            s.add(StokHareket(
                stok_id=kalem.stok_id, tarih=tarih, hareket_tipi="Cikis", miktar=miktar,
                referans_tablo="SevkiyatKalemi", referans_id=sk.id,
                aciklama="Onaylandı - kesin stok çıkışı",
            ))
            kalem.sevk_edilen_miktar += miktar
            kalem.kalan_miktar -= miktar

        kalan_toplam = sum(
            k.kalan_miktar for k in s.execute(
                select(SiparisKalemi).where(SiparisKalemi.siparis_id == siparis.id)
            ).scalars()
        )
        siparis.durum = "TamSevk" if kalan_toplam <= 1e-9 else "KismiSevk"

        sevkiyat.durum = "Onaylandi"
        sevkiyat.onaylayan_kullanici_id = onaylayan_kullanici_id
        sevkiyat.onay_tarihi = datetime.datetime.now()
        sevkiyat.olaganustu_duzeltme = olaganustu_duzeltme

        # --- 3: İrsaliye ve/veya Fatura oluştur ---
        irsaliye_id = None
        if sevkiyat.sevkiyat_turu in ("SadeceIrsaliye", "IrsaliyeVeFatura"):
            irsaliye_no = get_next_number(s, "Irsaliye", onaylayan_kullanici_adi)
            irsaliye = IrsaliyeBaslik(
                irsaliye_no=irsaliye_no, sevkiyat_id=sevkiyat.id, cari_id=siparis.cari_id,
                tarih=tarih, durum="Kesildi",
            )
            s.add(irsaliye)
            s.flush()
            irsaliye_id = irsaliye.id

            for sk in sevk_kalemleri:
                s.add(IrsaliyeDetay(irsaliye_id=irsaliye.id, sevkiyat_kalemi_id=sk.id, miktar=sk.sevk_miktar))

            if efatura_adapter:
                sonuc_ef = efatura_adapter.irsaliye_gonder(
                    {"irsaliye_no": irsaliye_no, "cari_id": siparis.cari_id}, irsaliye.client_uuid
                )
                irsaliye.efatura_durumu = sonuc_ef.durum
                irsaliye.efatura_uuid = sonuc_ef.efatura_uuid

            db.audit_log(s, "IrsaliyeBaslik", irsaliye.id, "EKLEME", onaylayan_kullanici_adi,
                          None, {"irsaliye_no": irsaliye_no})

        fatura_id = None
        toplam_satis = toplam_kdv = toplam_maliyet = kur_farki_tutari = 0.0
        if sevkiyat.sevkiyat_turu in ("SadeceFatura", "IrsaliyeVeFatura"):
            fatura_no = get_next_number(s, "Fatura", onaylayan_kullanici_adi)
            fatura_kalemleri_veri = []

            for sk in sevk_kalemleri:
                kalem = s.get(SiparisKalemi, sk.siparis_kalemi_id)
                miktar = sk.sevk_miktar
                birim_fiyat = kalem.birim_fiyat  # SNAPSHOT
                kdv_orani = kalem.kdv_orani or KDV_VARSAYILAN

                satir_tutari = miktar * birim_fiyat * kullanilan_kur
                satir_kdv = satir_tutari * (kdv_orani / 100.0)
                satir_maliyet = miktar * kalem.maliyet * kullanilan_kur

                toplam_satis += satir_tutari
                toplam_kdv += satir_kdv
                toplam_maliyet += satir_maliyet

                fatura_kalemleri_veri.append({
                    "stok_id": kalem.stok_id, "sevkiyat_kalemi_id": sk.id,
                    "miktar": miktar, "birim_fiyat": birim_fiyat,
                    "kdv_orani": kdv_orani, "satir_toplami": satir_tutari,
                })

            if fatura_kur is not None and fatura_kur != siparis_kuru:
                kur_farki_tutari = sum(
                    k["miktar"] * k["birim_fiyat"] for k in fatura_kalemleri_veri
                ) * (fatura_kur - siparis_kuru)

            fatura = FaturaBaslik(
                fatura_no=fatura_no, irsaliye_id=irsaliye_id, sevkiyat_id=sevkiyat.id,
                cari_id=siparis.cari_id, tarih=tarih, kur=kullanilan_kur,
                kur_farki=kur_farki_tutari, toplam_tutar=toplam_satis, kdv_tutari=toplam_kdv,
                durum="Kesildi",
            )
            s.add(fatura)
            s.flush()
            fatura_id = fatura.id

            for k in fatura_kalemleri_veri:
                s.add(FaturaDetay(
                    fatura_id=fatura.id, stok_id=k["stok_id"], sevkiyat_kalemi_id=k["sevkiyat_kalemi_id"],
                    miktar=k["miktar"], birim_fiyat=k["birim_fiyat"],
                    kdv_orani=k["kdv_orani"], satir_toplami=k["satir_toplami"],
                ))

            if efatura_adapter:
                sonuc_ef = efatura_adapter.fatura_gonder(
                    {"fatura_no": fatura_no, "cari_id": siparis.cari_id}, fatura.client_uuid
                )
                fatura.efatura_durumu = sonuc_ef.durum
                fatura.efatura_uuid = sonuc_ef.efatura_uuid

            # --- 4: Cari hareket + Muhasebe ---
            toplam_borc = toplam_satis + toplam_kdv
            s.add(CariHareket(
                cari_id=siparis.cari_id, tarih=tarih, hareket_tipi="Borc", tutar=toplam_borc,
                referans_tablo="FaturaBaslik", referans_id=fatura.id, aciklama="Fatura - alıcı borcu",
            ))
            cari = s.get(CariKart, siparis.cari_id)
            cari.bakiye += toplam_borc

            yil = int(tarih[:4])
            kayitlar = [
                (CARI_HESAP_KODU, toplam_borc, 0, "Fatura - alıcı borcu"),
                (SATIS_GELIR_HESABI, 0, toplam_satis, "Fatura - satış geliri"),
                (KDV_HESAP_HESABI, 0, toplam_kdv, "Fatura - hesaplanan KDV"),
                (SATIS_MALIYET_HESABI, toplam_maliyet, 0, "Satılan malın maliyeti"),
            ]
            if kur_farki_tutari > 0:
                kayitlar.append((KUR_FARKI_GIDER_HESABI, kur_farki_tutari, 0, "Kur farkı gideri"))
            elif kur_farki_tutari < 0:
                kayitlar.append((KUR_FARKI_GELIR_HESABI, 0, abs(kur_farki_tutari), "Kur farkı geliri"))

            for hesap, borc, alacak, aciklama in kayitlar:
                s.add(MuhasebeHareketi(
                    tarih=tarih, hesap_kodu=hesap, borc=borc, alacak=alacak, yil=yil,
                    referans_tablo="FaturaBaslik", referans_id=fatura.id, aciklama=aciklama,
                ))

            db.audit_log(s, "FaturaBaslik", fatura.id, "EKLEME", onaylayan_kullanici_adi,
                          None, {"fatura_no": fatura_no, "tutar": toplam_borc})

        db.audit_log(s, "Sevkiyat", sevkiyat.id, "GUNCELLEME", onaylayan_kullanici_adi,
                      {"durum": "Hazir"}, {"durum": "Onaylandi"})

        return {
            "sevkiyat_id": sevkiyat.id, "irsaliye_id": irsaliye_id, "fatura_id": fatura_id,
            "siparis_durumu": siparis.durum, "toplam_satis": toplam_satis,
            "toplam_kdv": toplam_kdv, "kur_farki": kur_farki_tutari,
        }


# =====================================================================
# GERİ TARAMA: Sevkiyat İptal/İade (ters kayıt - hiçbir şey silinmez)
# =====================================================================
def sevkiyat_storno(db: DBManager, sevkiyat_id: int, kullanici_id: int, kullanici_adi: str) -> dict:
    with db.session_scope() as s:
        sevkiyat = s.get(Sevkiyat, sevkiyat_id)
        if not sevkiyat:
            raise ValueError("Sevkiyat bulunamadı.")
        if sevkiyat.durum != "Onaylandi":
            raise ValueError("Sadece onaylanmış sevkiyatlar storno edilebilir.")

        tarih = datetime.date.today().isoformat()
        storno_no = get_next_number(s, "Sevkiyat", kullanici_adi)

        storno_sevkiyat = Sevkiyat(
            sevkiyat_no=storno_no, siparis_id=sevkiyat.siparis_id, tarih=tarih,
            sevkiyat_turu=sevkiyat.sevkiyat_turu, durum="Stornolandi",
            hazirlayan_kullanici_id=kullanici_id, storno_id=sevkiyat.id,
        )
        s.add(storno_sevkiyat)
        s.flush()

        sevk_kalemleri = list(
            s.execute(select(SevkiyatKalemi).where(SevkiyatKalemi.sevkiyat_id == sevkiyat_id)).scalars()
        )
        for sk in sevk_kalemleri:
            kalem = s.get(SiparisKalemi, sk.siparis_kalemi_id)
            miktar = sk.sevk_miktar

            s.add(SevkiyatKalemi(
                sevkiyat_id=storno_sevkiyat.id, siparis_kalemi_id=sk.siparis_kalemi_id,
                sevk_miktar=-miktar, fiyat=sk.fiyat,
            ))
            s.execute(
                update(StokKart).where(StokKart.id == kalem.stok_id)
                .values(mevcut_miktar=StokKart.mevcut_miktar + miktar)
            )
            s.add(StokHareket(
                stok_id=kalem.stok_id, tarih=tarih, hareket_tipi="Storno", miktar=miktar,
                referans_tablo="Sevkiyat", referans_id=storno_sevkiyat.id,
                aciklama=f"Sevkiyat #{sevkiyat_id} stornosu",
            ))
            kalem.sevk_edilen_miktar -= miktar
            kalem.kalan_miktar += miktar

        # İlgili irsaliyeyi stornola
        irsaliye = s.execute(
            select(IrsaliyeBaslik).where(IrsaliyeBaslik.sevkiyat_id == sevkiyat_id)
        ).scalar_one_or_none()
        if irsaliye and irsaliye.durum == "Kesildi":
            irsaliye.durum = "Stornolandi"

        # İlgili faturayı stornola (ters kayıtlarla)
        fatura = s.execute(
            select(FaturaBaslik).where(FaturaBaslik.sevkiyat_id == sevkiyat_id)
        ).scalar_one_or_none()
        storno_fatura_id = None
        if fatura and fatura.durum == "Kesildi":
            storno_fatura_no = get_next_number(s, "Fatura", kullanici_adi)
            storno_fatura = FaturaBaslik(
                fatura_no=storno_fatura_no, sevkiyat_id=storno_sevkiyat.id, cari_id=fatura.cari_id,
                tarih=tarih, kur=fatura.kur, kur_farki=-fatura.kur_farki,
                toplam_tutar=-fatura.toplam_tutar, kdv_tutari=-fatura.kdv_tutari,
                durum="Kesildi", storno_id=fatura.id,
            )
            s.add(storno_fatura)
            s.flush()
            storno_fatura_id = storno_fatura.id

            s.add(CariHareket(
                cari_id=fatura.cari_id, tarih=tarih, hareket_tipi="Alacak",
                tutar=fatura.toplam_tutar + fatura.kdv_tutari,
                referans_tablo="FaturaBaslik", referans_id=storno_fatura.id,
                aciklama=f"Fatura #{fatura.id} stornosu",
            ))
            cari = s.get(CariKart, fatura.cari_id)
            cari.bakiye -= (fatura.toplam_tutar + fatura.kdv_tutari)

            yil = int(tarih[:4])
            eski_kayitlar = list(s.execute(
                select(MuhasebeHareketi).where(
                    MuhasebeHareketi.referans_tablo == "FaturaBaslik",
                    MuhasebeHareketi.referans_id == fatura.id,
                )
            ).scalars())
            for k in eski_kayitlar:
                s.add(MuhasebeHareketi(
                    tarih=tarih, hesap_kodu=k.hesap_kodu, borc=k.alacak, alacak=k.borc,
                    yil=yil, referans_tablo="FaturaBaslik", referans_id=storno_fatura.id,
                    aciklama=f"Storno: {k.aciklama}", storno_mu=True,
                ))

            fatura.durum = "Stornolandi"

        sevkiyat.durum = "Stornolandi"

        # Sipariş durumunu yeniden hesapla
        kalemler = list(
            s.execute(select(SiparisKalemi).where(SiparisKalemi.siparis_id == sevkiyat.siparis_id)).scalars()
        )
        toplam_kalan = sum(k.kalan_miktar for k in kalemler)
        toplam_sip = sum(k.sip_miktar for k in kalemler)
        siparis = s.get(SiparisBaslik, sevkiyat.siparis_id)
        siparis.durum = "Onayli" if toplam_kalan >= toplam_sip - 1e-9 else "KismiSevk"

        db.audit_log(s, "Sevkiyat", sevkiyat.id, "STORNO", kullanici_adi,
                      {"durum": "Onaylandi"}, {"durum": "Stornolandi", "storno_sevkiyat_id": storno_sevkiyat.id})

        return {"storno_sevkiyat_id": storno_sevkiyat.id, "storno_fatura_id": storno_fatura_id}


# =====================================================================
# TTL Temizliği: unutulmuş "Hazır" rezervasyonları serbest bırakır
# =====================================================================
def rezerve_temizle(db: DBManager, saat_esigi: int = 48, sistem_kullanici: str = "Sistem"):
    """
    saat_esigi saatten daha eski, hâlâ 'Hazir' durumundaki sevkiyatların
    rezerve stoğunu serbest bırakır ve sevkiyatı 'Stornolandi' işaretler.
    Bu fonksiyon periyodik bir arka plan görevi (örn. günde bir kez,
    uygulama açılışında) olarak çağrılmalıdır.
    """
    sinir_tarihi = (datetime.date.today() - datetime.timedelta(hours=saat_esigi)).isoformat()
    with db.session_scope() as s:
        eski_sevkiyatlar = list(
            s.execute(select(Sevkiyat).where(Sevkiyat.durum == "Hazir", Sevkiyat.tarih < sinir_tarihi)).scalars()
        )
        for sevkiyat in eski_sevkiyatlar:
            sevk_kalemleri = list(
                s.execute(select(SevkiyatKalemi).where(SevkiyatKalemi.sevkiyat_id == sevkiyat.id)).scalars()
            )
            for sk in sevk_kalemleri:
                kalem = s.get(SiparisKalemi, sk.siparis_kalemi_id)
                s.execute(
                    update(StokKart).where(StokKart.id == kalem.stok_id)
                    .values(rezerve_miktar=StokKart.rezerve_miktar - sk.sevk_miktar)
                )
            sevkiyat.durum = "Stornolandi"
            db.audit_log(s, "Sevkiyat", sevkiyat.id, "GUNCELLEME", sistem_kullanici,
                         {"durum": "Hazir"}, {"durum": "Stornolandi (TTL - süresi doldu)"})
        return len(eski_sevkiyatlar)
