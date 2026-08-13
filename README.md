# ENTEGRE MUHASEBE 2026

Python tabanlı, taşınabilir (Portable EXE) muhasebe ve sipariş yönetim sistemi.

## Sabit Proje Dizini
Bu depo, Windows'ta doğrudan `C:\ENTEGRE_MUHASEBE_2026` dizinine karşılık gelir
(ayrı bir alt klasör yoktur).

- `C:\ENTEGRE_MUHASEBE_2026\main.py`, `core\`, `ui\`, `controllers\` → kaynak kod
- `C:\ENTEGRE_MUHASEBE_2026\Data\_master.db` → TÜM firmalar ve kullanıcılar (merkezi)
- `C:\ENTEGRE_MUHASEBE_2026\Data\FIRMA_YIL.db` → her firma+yıl için ayrı işlem veritabanı
- `C:\ENTEGRE_MUHASEBE_2026\Yedekler\` → Şifreli ZIP yedekler

## Teknik Yapı
- Python 3.10+
- PyQt5 (arayüz)
- **SQLAlchemy 2.0 ORM** + SQLite (firma+yıl başına ayrı dosya, kullanıcı/firma merkezi `_master.db`'de)
- PyInstaller (tek dosya .exe olarak dağıtım)

## Kurulum
```bash
pip install -r requirements.txt
python main.py
```
İlk çalıştırmada demo giriş: **admin / admin123** (Demo Firma A.Ş.)

## Klasör Yapısı
```
core/
  models_master.py     - Firma, Kullanici (merkezi _master.db)
  models.py             - Yıllık db modelleri: CariKart, StokKart, SiparisBaslik/Kalemi,
                          Sevkiyat/Kalemi, IrsaliyeBaslik/Detay, FaturaBaslik/Detay,
                          CariHareket, MuhasebeHesabi/Hareketi, Sequence, AuditLog
  db_manager.py          - DBManager: engine/session, backup_db(), rollover_yil()
  master_db.py           - MasterDB: firma/kullanıcı CRUD + giriş doğrulama
  auth.py                - Şifre hash/doğrulama (PBKDF2-HMAC-SHA256)
  sequence.py            - Concurrency-safe, admin ayarlanabilir evrak numaralandırma
  backup_manager.py       - Yerel ZIP+şifreleme + Google Drive Service Account yükleme
  efatura/
    base.py               - E-Fatura/E-İrsaliye entegratörü için soyut arayüz
    mock_adapter.py        - Test amaçlı sahte adaptör (gerçek entegratör bağlanana kadar)
controllers/
  order_controller.py     - Sipariş: Taslak -> Onayli -> (Vazgeç/Düzenle)
  shipment_controller.py   - Sevkiyat: Hazır -> Onayla&Faturala -> Storno (4 göz onayı)
  invoice_controller.py    - Doğrudan (siparişsiz) fatura + storno
ui/
  main_window.py          - Giriş ekranı (Firma seç -> Kullanıcı seç -> Şifre) + slide menü + dashboard
main.py                   - Uygulama giriş noktası
```

## Belge Akışı
```
SiparisBaslik (Taslak -> Onayli)
    -> Sevkiyat (Hazir -> Onaylandi)              [4 göz onayı: Depo hazırlar, Muhasebeci onaylar]
        -> IrsaliyeBaslik (sevkiyat_turu'na göre opsiyonel, ayrı numaralandırma)
            -> FaturaBaslik (irsaliyeden VEYA doğrudan/siparişsiz de kesilebilir)
                -> CariHareket + StokHareket + MuhasebeHareketi
```
Sevkiyat türleri: `SadeceIrsaliye`, `IrsaliyeVeFatura`, `SadeceFatura`.

## İş Kuralları (Uygulanmış)
- **Stok kilidi:** Koşullu `UPDATE ... WHERE mevcut_miktar >= X` ile race condition koruması
- **Fiyat/maliyet snapshot:** Sipariş kalemindeki değerler sevkiyat anında değişmez
- **Döviz çıpası:** Sipariş kuru sabitlenir, fatura kuru farklıysa 646/656 hesaplarına otomatik kur farkı
- **Storno:** Hiçbir kayıt silinmez; ters kayıt ile iptal (Sevkiyat, İrsaliye, Fatura, Muhasebe)
- **Audit log:** Tüm kritik işlemler `AuditLog` tablosunda JSON olarak saklanır
- **4 göz onayı:** Depo "Hazır" işaretler (rezerve) → Muhasebeci "Onayla & Faturala" der (kesin düşüm)
- **Dönem kilidi:** Kapalı döneme kayıt girişi admin "Olağanüstü Düzeltme" izni gerektirir
- **Concurrency-safe numaralandırma:** `Sequence` tablosu, admin tarafından elle düzeltilebilir/başlatılabilir
- **İdempotency:** Fatura/İrsaliye'de `client_uuid` - entegratöre tekrar gönderimde mükerrer kayıt önler
- **TTL temizliği:** `rezerve_temizle()` - unutulmuş "Hazır" rezervasyonları serbest bırakır

## E-Fatura / E-İrsaliye
Gerçek GİB entegrasyonu bir e-fatura entegratörü (Nilvera/Uyumsoft/Foriba vb.) ile
sözleşme + API kimlik bilgisi + mali mühür gerektirir. `core/efatura/base.py`
soyut arayüzü, gerçek entegratör geldiğinde tek bir adaptör sınıfı yazılarak
bağlanabilecek şekilde tasarlanmıştır. Şimdilik `mock_adapter.py` ile test edilir.

## Gelecek Geliştirmeler (Bilinçli Olarak Ertelenenler)
- **Çoklu seri desteği:** Şu an her belge türü için tek seri var (`Sequence.belge_turu`).
  Çok şubeli/çok depolu senaryoda `seri_kodu` boyutu eklenebilir.
- **Optimistic concurrency:** Taslak siparişlerde iki kullanıcının aynı anda
  düzenlemesine karşı `version`/`son_degisiklik_zamani` kontrolü eklenebilir.

## Durum
Bu depo aktif geliştirme aşamasındadır.
