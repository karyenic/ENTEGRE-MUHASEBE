"""
base.py
--------
E-Fatura / E-İrsaliye entegratörleri için soyut arayüz.

ÖNEMLİ GERÇEK: Gerçek bir GİB entegrasyonu; bir e-fatura entegratörü
(Nilvera, Uyumsoft, Foriba, Logo vb.) ile ticari sözleşme + API kimlik
bilgisi + mali mühür/e-imza gerektirir. Bunlar bu ortamda yok ve
olamaz. Bu dosya, gerçek entegratör API'si geldiğinde TEK bir yeni
adaptör sınıfı yazılarak (bu arayüzü uygulayarak) sisteme
bağlanabilmesi için tasarlanmıştır - iş mantığı (controllers/) hiçbir
zaman "hangi entegratör" olduğunu bilmez, sadece bu arayüzü çağırır.

Kullanım:
    adapter = get_efatura_adapter()   # Ayarlar'dan seçilen adaptör
    sonuc = adapter.fatura_gonder(fatura_payload)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EFaturaSonuc:
    basarili: bool
    efatura_uuid: str | None = None
    hata_mesaji: str | None = None
    durum: str = "Beklemede"   # 'Gonderildi' | 'Hata' | 'Beklemede'


class EFaturaAdapter(ABC):
    """Tüm entegratör adaptörleri bu arayüzü uygulamalıdır."""

    @abstractmethod
    def mukellef_sorgula(self, vergi_no: str) -> bool:
        """Cari, e-Fatura mükellefi mi? (değilse e-Arşiv Fatura kesilmeli)"""
        raise NotImplementedError

    @abstractmethod
    def fatura_gonder(self, fatura_payload: dict, client_uuid: str) -> EFaturaSonuc:
        """
        client_uuid: idempotency anahtarı. Aynı client_uuid ile tekrar
        gönderim yapılırsa entegratör mükerrer kayıt OLUŞTURMAMALIDIR
        (gerçek entegratörler bunu genelde otomatik destekler; bu
        adaptör katmanı sadece bu anahtarı iletmekle yükümlüdür).
        """
        raise NotImplementedError

    @abstractmethod
    def irsaliye_gonder(self, irsaliye_payload: dict, client_uuid: str) -> EFaturaSonuc:
        raise NotImplementedError

    @abstractmethod
    def durum_sorgula(self, efatura_uuid: str) -> EFaturaSonuc:
        raise NotImplementedError
