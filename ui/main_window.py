"""
main_window.py
----------------
PyQt5 ana pencere iskeleti: sol slide menü + QStackedWidget ile modül geçişi
+ giriş sonrası dashboard (KPI'lar).

Bu bir MİNİMAL iskelettir; her modül (Siparis, Cari, Banka/Kasa, Stok,
Raporlar, Ayarlar) için ayrı widget dosyaları (ui/modules/*.py) açılıp
buraya bağlanması önerilir.
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QFrame, QGridLayout, QComboBox, QLineEdit,
    QMessageBox, QListWidget, QListWidgetItem,
)
from PyQt5.QtCore import Qt


# ---------------------------------------------------------------------
# Giriş Ekranı: Şirket seçimi + Kullanıcı + Şifre
# ---------------------------------------------------------------------
class GirisPenceresi(QWidget):
    def __init__(self, giris_basarili_callback):
        super().__init__()
        self.giris_basarili_callback = giris_basarili_callback
        self.setWindowTitle("Python Muhasebe Entegre Sistemi - Giriş")
        self.resize(420, 340)

        from core.master_db import MasterDB, GirisHatasi
        self.GirisHatasi = GirisHatasi
        self.mdb = MasterDB()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        baslik = QLabel("Muhasebe Entegre Sistemi")
        baslik.setStyleSheet("font-size: 20px; font-weight: bold;")
        baslik.setAlignment(Qt.AlignCenter)
        layout.addWidget(baslik)

        # --- 1. Firma seç ---
        self.firma_combo = QComboBox()
        self.firmalar = self.mdb.firmalari_listele()
        for firma in self.firmalar:
            self.firma_combo.addItem(f"{firma.firma_kodu} - {firma.firma_adi}", firma.id)
        self.firma_combo.currentIndexChanged.connect(self._firma_degisti)
        layout.addWidget(QLabel("Şirket:"))
        layout.addWidget(self.firma_combo)

        # --- 2. Kullanıcı seç (rolüyle birlikte, seçilen firmaya göre filtrelenir) ---
        self.kullanici_combo = QComboBox()
        layout.addWidget(QLabel("Kullanıcı:"))
        layout.addWidget(self.kullanici_combo)
        self._firma_degisti(0)   # ilk firma için kullanıcı listesini doldur

        self.sifre_edit = QLineEdit()
        self.sifre_edit.setPlaceholderText("Şifre")
        self.sifre_edit.setEchoMode(QLineEdit.Password)
        self.sifre_edit.returnPressed.connect(self._giris_dene)
        layout.addWidget(self.sifre_edit)

        giris_btn = QPushButton("Giriş Yap")
        giris_btn.clicked.connect(self._giris_dene)
        layout.addWidget(giris_btn)

    def _firma_degisti(self, index: int):
        """Şirket değişince o şirkete ait kullanıcı listesini (rolüyle) doldurur."""
        self.kullanici_combo.clear()
        if index < 0 or not self.firmalar:
            return
        firma_id = self.firma_combo.itemData(index)
        kullanicilar = self.mdb.kullanicilari_listele(firma_id)
        for k in kullanicilar:
            etiket = f"{k.kullanici_adi} ({k.rol})" + (f" - {k.ad_soyad}" if k.ad_soyad else "")
            self.kullanici_combo.addItem(etiket, k.id)

    def _giris_dene(self):
        if not self.firmalar:
            QMessageBox.warning(self, "Hata", "Tanımlı firma bulunamadı.")
            return
        if self.kullanici_combo.count() == 0:
            QMessageBox.warning(self, "Hata", "Bu firma için tanımlı kullanıcı yok.")
            return
        if not self.sifre_edit.text():
            QMessageBox.warning(self, "Hata", "Şifre giriniz.")
            return

        firma_id = self.firma_combo.currentData()
        kullanici_id = self.kullanici_combo.currentData()

        try:
            kullanici = self.mdb.giris_yap(firma_id, kullanici_id, self.sifre_edit.text())
        except self.GirisHatasi as e:
            QMessageBox.warning(self, "Giriş Başarısız", str(e))
            return

        firma_kodu = self.firma_combo.currentText().split(" - ")[0]
        self.giris_basarili_callback(firma_kodu, kullanici)


# ---------------------------------------------------------------------
# Dashboard (KPI özet kartları)
# ---------------------------------------------------------------------
class DashboardWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QGridLayout(self)

        self.kpi_kartlari = {}
        kpi_tanimlari = [
            ("cari_bakiye", "Toplam Cari Bakiye"),
            ("bekleyen_siparis", "Bekleyen Sipariş"),
            ("kritik_stok", "Kritik Stok Uyarısı"),
            ("gunluk_ciro", "Günlük Ciro"),
        ]
        for i, (anahtar, baslik) in enumerate(kpi_tanimlari):
            kart = self._kpi_kart_olustur(baslik, "—")
            self.kpi_kartlari[anahtar] = kart
            layout.addWidget(kart, i // 2, i % 2)

    def _kpi_kart_olustur(self, baslik: str, deger: str) -> QFrame:
        kart = QFrame()
        kart.setFrameShape(QFrame.StyledPanel)
        kart.setStyleSheet(
            "QFrame { background: #f5f5f7; border-radius: 10px; padding: 12px; }"
        )
        v = QVBoxLayout(kart)
        baslik_lbl = QLabel(baslik)
        baslik_lbl.setStyleSheet("color: #666; font-size: 12px;")
        deger_lbl = QLabel(deger)
        deger_lbl.setStyleSheet("font-size: 22px; font-weight: bold;")
        deger_lbl.setObjectName("deger")
        v.addWidget(baslik_lbl)
        v.addWidget(deger_lbl)
        return kart

    def kpi_guncelle(self, anahtar: str, deger: str):
        kart = self.kpi_kartlari.get(anahtar)
        if kart:
            deger_lbl = kart.findChild(QLabel, "deger")
            if deger_lbl:
                deger_lbl.setText(deger)


# ---------------------------------------------------------------------
# Basit yer tutucu modül widget'ı (Siparis, Cari, Stok, vb. için)
# ---------------------------------------------------------------------
class YerTutucuModul(QWidget):
    def __init__(self, baslik: str):
        super().__init__()
        layout = QVBoxLayout(self)
        lbl = QLabel(f"{baslik} Modülü")
        lbl.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(lbl)
        layout.addWidget(QLabel("(Bu modül henüz geliştirilecek - ui/modules/ altına eklenecek)"))
        layout.addStretch()


# ---------------------------------------------------------------------
# Ana Pencere: Sol slide menü + QStackedWidget
# ---------------------------------------------------------------------
class AnaPencere(QMainWindow):
    MODULLER = ["Ana Sayfa", "Sipariş", "Cari", "Banka/Kasa", "Stok", "Raporlar", "Ayarlar"]

    def __init__(self, firma_kodu: str, kullanici):
        super().__init__()
        self.firma_kodu = firma_kodu
        self.kullanici = kullanici   # core.models_master.Kullanici nesnesi

        self.setWindowTitle(
            f"Muhasebe Entegre Sistemi - {firma_kodu} - {kullanici.kullanici_adi} ({kullanici.rol})"
        )
        self.resize(1200, 750)

        merkezi_widget = QWidget()
        ana_layout = QHBoxLayout(merkezi_widget)
        ana_layout.setContentsMargins(0, 0, 0, 0)
        ana_layout.setSpacing(0)

        # --- Sol slide menü ---
        self.menu_listesi = QListWidget()
        self.menu_listesi.setFixedWidth(200)
        self.menu_listesi.setStyleSheet(
            "QListWidget { background: #1e1e2d; color: white; border: none; font-size: 14px; }"
            "QListWidget::item { padding: 14px 16px; }"
            "QListWidget::item:selected { background: #3a3a55; }"
        )
        for modul in self.MODULLER:
            QListWidgetItem(modul, self.menu_listesi)
        cikis_item = QListWidgetItem("Çıkış")
        self.menu_listesi.addItem(cikis_item)

        self.menu_listesi.currentRowChanged.connect(self._modul_degistir)
        ana_layout.addWidget(self.menu_listesi)

        # --- Sağ taraf: QStackedWidget ---
        self.stack = QStackedWidget()
        self.dashboard = DashboardWidget()
        self.stack.addWidget(self.dashboard)                      # index 0: Ana Sayfa
        for modul in self.MODULLER[1:]:                           # index 1..: diğer modüller
            self.stack.addWidget(YerTutucuModul(modul))

        ana_layout.addWidget(self.stack, stretch=1)

        self.setCentralWidget(merkezi_widget)
        self.menu_listesi.setCurrentRow(0)

        self._kpi_verilerini_yukle()

    def _modul_degistir(self, index: int):
        if index == len(self.MODULLER):  # "Çıkış" seçildi
            self.close()
            return
        self.stack.setCurrentIndex(index)

    def _kpi_verilerini_yukle(self):
        """
        TODO: core.db_manager üzerinden gerçek verileri çek:
          - Cari_Hesaplar.Bakiye toplamı
          - Siparisler WHERE Durum IN ('Acik','KismiSevk') sayısı
          - Urunler WHERE MevcutStok <= KritikStok sayısı
          - Bugünün Faturalar.ToplamTutar toplamı
        Şimdilik yer tutucu değerlerle gösteriliyor.
        """
        self.dashboard.kpi_guncelle("cari_bakiye", "—")
        self.dashboard.kpi_guncelle("bekleyen_siparis", "—")
        self.dashboard.kpi_guncelle("kritik_stok", "—")
        self.dashboard.kpi_guncelle("gunluk_ciro", "—")


def uygulamayi_baslat():
    app = QApplication(sys.argv)

    ana_pencere_ref = {}

    def giris_basarili(firma_kodu, kullanici):
        giris_penceresi.close()
        ana_pencere = AnaPencere(firma_kodu, kullanici)
        ana_pencere_ref["pencere"] = ana_pencere  # referansı canlı tut (GC'ye kaptırma)
        ana_pencere.show()

    giris_penceresi = GirisPenceresi(giris_basarili)
    giris_penceresi.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    uygulamayi_baslat()
