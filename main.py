"""KO Ticaret Takip — Knight Online item alış-satış takip programı.

Çalıştırma:  python main.py
"""
from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import QLibraryInfo, QLocale, QTimer, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core import backup
from app.core.db import Database
from app.core.errors import UserError
from app.core.paths import APP_NAME, db_path, log_path, resource_path
from app.core.service import TradeService
from app.ui import theme
from app.ui.dialogs import InitialSetupDialog
from app.ui.main_window import MainWindow
from app.ui.widgets import MoneyInput


def _setup_logging() -> None:
    try:
        logging.basicConfig(filename=str(log_path()), level=logging.INFO, encoding="utf-8",
                            format="%(asctime)s %(levelname)s %(message)s")
    except OSError:
        logging.basicConfig(level=logging.INFO)


def _excepthook(exc_type, exc, tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    logging.error("Beklenmeyen hata:\n%s", text)
    if issubclass(exc_type, UserError):
        QMessageBox.warning(None, "Uyarı", str(exc))
        return
    QMessageBox.critical(
        None, "Beklenmeyen hata",
        "Beklenmeyen bir hata oluştu. Verileriniz güvende: yarım kalan işlem kaydedilmedi.\n\n"
        f"Hata: {exc}\n\nAyrıntılar şu dosyaya yazıldı:\n{log_path()}")


def main() -> int:
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("KOTicaretTakip")
    app.setStyle("Fusion")
    app.setStyleSheet(theme.QSS)
    QLocale.setDefault(QLocale("tr_TR"))
    tr = QTranslator(app)
    if tr.load("qtbase_tr", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(tr)
    icon = resource_path("assets/icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    sys.excepthook = _excepthook

    try:
        db = Database(db_path())
        service = TradeService(db)
    except Exception as e:  # noqa: BLE001
        logging.exception("Veritabanı açılamadı")
        QMessageBox.critical(None, "Veritabanı açılamadı",
                             f"Veritabanı açılamadı:\n{db_path()}\n\n{e}\n\n"
                             "Dosya başka bir program tarafından kullanılıyor olabilir.")
        return 1

    MoneyInput.default_mode = service.price_mode
    if not service.is_initialized():
        dlg = InitialSetupDialog(None, service)
        if not dlg.exec():
            service.mark_initialized()  # başlangıç 0 GB

    # Otomatik yedek (başarısız olsa bile program açılır, kullanıcı bilgilendirilir)
    backup_error = None
    try:
        backup.maybe_auto_backup(service)
    except (UserError, OSError) as e:
        backup_error = str(e)
        logging.warning("Otomatik yedek alınamadı: %s", e)

    win = MainWindow(service)
    win.show()
    if backup_error:
        QTimer.singleShot(400, lambda: QMessageBox.warning(
            win, "Yedekleme",
            f"Otomatik yedek alınamadı:\n{backup_error}\n\nProgramı kullanmaya devam edebilirsiniz. "
            "Ayarlar > Yedekleme bölümünden klasörü kontrol edip manuel yedek alabilirsiniz."))
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
