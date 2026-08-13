"""
sequence.py
-------------
Sipariş/Sevkiyat/İrsaliye/Fatura numaralarının concurrency-safe üretimi.

Neden ayrı bir modül: Önceki iskelette numara üretimi `COUNT(*)+1` ile
yapılıyordu — bu, aynı anda iki kullanıcı işlem yaparsa ÇAKIŞABİLİR
(iki farklı belgeye aynı numara verilebilir). Doğrusu, ayrı bir
`Sequence` tablosunu tek bir UPDATE ifadesiyle arttırmaktır: SQLite bir
transaction içindeki ilk yazma ifadesinde veritabanını kilitler, bu
yüzden get_next_number() çağrıldığı anda başka hiçbir yazma işlemi
aynı anda bu sayacı artıramaz.

Admin, Ayarlar ekranından set_sequence() ile sayacı elle
başlatabilir/düzeltebilir (örn. yıl başında sıfırlamak, ya da bir hatayı
düzeltmek için).
"""

import datetime
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.models import Sequence


def get_next_number(session: Session, belge_turu: str, kullanici: str) -> str:
    """
    Belirtilen belge türü için bir sonraki numarayı üretir ve DÖNER
    (örn. 'SIP-000042'). Çağıran fonksiyon bu session'ı commit etmeden
    önce diğer tüm işlemlerini de yapmalı ki hata durumunda numara
    artışı da geri alınsın (tutarlılık için).
    """
    # Tek UPDATE ifadesi: SQLite bu noktada veritabanını kilitler.
    sonuc = session.execute(
        update(Sequence)
        .where(Sequence.belge_turu == belge_turu)
        .values(
            mevcut_deger=Sequence.mevcut_deger + 1,
            son_guncelleyen=kullanici,
            son_guncelleme_tarihi=datetime.datetime.now(),
        )
    )
    if sonuc.rowcount == 0:
        raise ValueError(f"Tanımsız belge türü için sequence: {belge_turu}")

    seq = session.execute(
        select(Sequence).where(Sequence.belge_turu == belge_turu)
    ).scalar_one()

    return f"{seq.on_ek}{str(seq.mevcut_deger).zfill(seq.basamak_sayisi)}"


def set_sequence(session: Session, belge_turu: str, yeni_deger: int, kullanici: str):
    """
    ADMIN İŞLEMİ: sayacı elle belirli bir değere ayarlar/düzeltir.
    Bir sonraki get_next_number() çağrısı yeni_deger + 1'i üretecektir.
    """
    sonuc = session.execute(
        update(Sequence)
        .where(Sequence.belge_turu == belge_turu)
        .values(
            mevcut_deger=yeni_deger,
            son_guncelleyen=f"{kullanici} (elle düzeltme)",
            son_guncelleme_tarihi=datetime.datetime.now(),
        )
    )
    if sonuc.rowcount == 0:
        raise ValueError(f"Tanımsız belge türü için sequence: {belge_turu}")


def sequence_durumu(session: Session) -> list[Sequence]:
    """Ayarlar ekranında göstermek için tüm sayaçların mevcut durumu."""
    return list(session.execute(select(Sequence)).scalars().all())
