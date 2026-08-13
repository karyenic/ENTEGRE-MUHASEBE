"""
main.py
--------
Uygulama giriş noktası.

PyInstaller ile derlemek için (proje kökünden):
    pyinstaller --onefile --noconsole --add-data "core/schema.sql;core" main.py

Sabit proje dizini: C:\\ENTEGRE_MUHASEBE_2026
Bu dizin hem projenin kendisidir (bu dosyanın, core/ ve ui/'nin durduğu yer)
hem de Data/ ve Yedekler/ alt klasörlerinin oluşturulduğu yerdir
(bkz. core/db_manager.py -> BASE_DIR). Ayrı bir "muhasebe_sistemi" alt
klasörü YOKTUR; proje C:\\ENTEGRE_MUHASEBE_2026 dizininin doğrudan kendisidir.
GitHub deposu: https://github.com/karyenic/ENTEGRE-MUHASEBE
"""

from ui.main_window import uygulamayi_baslat

if __name__ == "__main__":
    uygulamayi_baslat()
