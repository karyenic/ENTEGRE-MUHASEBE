"""
mock_adapter.py
-----------------
Gerçek entegratör bağlanana kadar akışı test etmek için sahte adaptör.
Hiçbir gerçek ağ isteği yapmaz; her zaman "başarılı" döner ve rastgele
bir UUID üretir. ASLA üretimde (gerçek GİB gönderimi yerine) kullanılmamalıdır.
"""

import uuid
from core.efatura.base import EFaturaAdapter, EFaturaSonuc


class MockEFaturaAdapter(EFaturaAdapter):
    def mukellef_sorgula(self, vergi_no: str) -> bool:
        # Test amaçlı: vergi no çift sayıyla bitiyorsa mükellef kabul edelim
        return bool(vergi_no) and vergi_no[-1] in "02468"

    def fatura_gonder(self, fatura_payload: dict, client_uuid: str) -> EFaturaSonuc:
        return EFaturaSonuc(basarili=True, efatura_uuid=str(uuid.uuid4()), durum="Gonderildi")

    def irsaliye_gonder(self, irsaliye_payload: dict, client_uuid: str) -> EFaturaSonuc:
        return EFaturaSonuc(basarili=True, efatura_uuid=str(uuid.uuid4()), durum="Gonderildi")

    def durum_sorgula(self, efatura_uuid: str) -> EFaturaSonuc:
        return EFaturaSonuc(basarili=True, efatura_uuid=efatura_uuid, durum="Gonderildi")
