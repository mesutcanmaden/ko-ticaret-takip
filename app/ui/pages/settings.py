from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from ...core import backup
from ...core.errors import UserError
from ...core.money import fmt_rate, parse_tax_rate
from ...core.paths import APP_VERSION, data_dir, default_backup_dir
from ..widgets import Cell, MoneyInput, Table, confirm, info, muted, page_title, warn
from .base import Page


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB".replace(".", ",")
    return f"{n / 1024 ** 2:.1f} MB".replace(".", ",")


class SettingsPage(Page):
    title = "Ayarlar"

    def __init__(self, ctx):
        super().__init__(ctx, scroll=True)
        self.lay.addWidget(page_title("Ayarlar"))

        gen = QGroupBox("Genel")
        gf = QFormLayout(gen)
        gf.setVerticalSpacing(10)
        self.tax = QLineEdit()
        self.tax.setMaximumWidth(120)
        self.tax.setPlaceholderText("örn. 3")
        tax_row = QHBoxLayout()
        tax_row.addWidget(QLabel("%"))
        tax_row.addWidget(self.tax)
        tax_row.addWidget(muted("Yalnızca bundan sonraki pazar satışlarına uygulanır; geçmiş satışlar değişmez."))
        tax_row.addStretch(1)
        gf.addRow("Pazar vergi oranı", tax_row)
        self.mode = QComboBox()
        self.mode.addItem("Yalnızca M  (örn. 105 M = 1,05 GB)", "m")
        self.mode.addItem("Ondalıklı GB  (örn. 12,5 GB)", "gb")
        self.mode.addItem("GB ve M ayrı alanlar  (örn. 12 GB + 50 M)", "gbm")
        self.mode.setMaximumWidth(360)
        gf.addRow("Varsayılan fiyat giriş yöntemi", self.mode)
        self.initial = MoneyInput("Başlangıç GB", allow_empty=True)
        self.initial.setMaximumWidth(360)
        gf.addRow("Başlangıç GB miktarı", self.initial)
        gf.addRow("", muted("Programı kullanmaya başladığınızdaki GB. Sonradan program dışı değişiklikler için "
                            "Ana Sayfa'daki 'GB Ekle / GB Çıkar' işlemlerini kullanın."))
        save = QPushButton("Ayarları Kaydet")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        gf.addRow("", save)
        self.lay.addWidget(gen)

        bk = QGroupBox("Yedekleme")
        bl = QVBoxLayout(bk)
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Yedekleme klasörü:"))
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        frow.addWidget(self.folder, 1)
        for text, slot in (("Değiştir…", self._choose_folder), ("Varsayılan", self._default_folder),
                           ("Klasörü aç", self._open_folder)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            frow.addWidget(b)
        bl.addLayout(frow)
        self.last = muted("")
        bl.addWidget(self.last)
        bl.addWidget(muted("Otomatik yedek: son başarılı yedekten 3 gün sonra programın ilk açılışında alınır. "
                           "Son 10 yedek saklanır, daha eskiler otomatik silinir."))
        self.backups = Table(["Yedek dosyası", "Tarih", "Boyut"], stretch=0)
        self.backups.setMinimumHeight(220)
        bl.addWidget(self.backups)
        brow = QHBoxLayout()
        now = QPushButton("Şimdi yedek al")
        now.setObjectName("Primary")
        now.clicked.connect(self._backup_now)
        rest = QPushButton("Seçili yedeği geri yükle")
        rest.setObjectName("Danger")
        rest.clicked.connect(self._restore_selected)
        rest_file = QPushButton("Dosyadan geri yükle…")
        rest_file.clicked.connect(self._restore_file)
        for b in (now, rest, rest_file):
            brow.addWidget(b)
        brow.addStretch(1)
        bl.addLayout(brow)
        self.lay.addWidget(bk)

        dbb = QGroupBox("Veritabanı bilgileri")
        df = QFormLayout(dbb)
        self.db = {}
        for k, t in (("path", "Veritabanı dosyası"), ("size", "Boyut"), ("counts", "Kayıtlar"),
                     ("version", "Program sürümü")):
            self.db[k] = QLabel("—")
            self.db[k].setWordWrap(True)
            df.addRow(t, self.db[k])
        drow = QHBoxLayout()
        for text, slot in (("Veri klasörünü aç", lambda: self._open(data_dir())),
                           ("Bütünlük kontrolü", self._check), ("Hesapları yeniden kur", self._recompute)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            drow.addWidget(b)
        drow.addStretch(1)
        df.addRow(drow)
        df.addRow(muted("Program yalnızca tek bir Knight Online sunucusundaki ticareti takip eder. "
                        "Oyuna bağlanmaz, oyun dosyalarına dokunmaz; bütün kayıtlar elle girilir."))
        self.lay.addWidget(dbb)
        self.lay.addStretch(1)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        self.tax.setText(fmt_rate(self.svc.tax_bps).lstrip("%"))
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.svc.price_mode)))
        self.initial.set_mode(self.svc.price_mode)
        self.initial.set_value(self.svc.initial_balance)
        try:
            folder = backup.backup_dir(self.svc)
        except OSError as e:
            folder = Path(self.svc.get_setting("backup_dir") or default_backup_dir())
            warn(self, f"Yedekleme klasörüne erişilemiyor: {e}")
        self.folder.setText(str(folder))
        last = backup.last_backup_at(self.svc)
        self.last.setText("Son başarılı yedek: " + (last.strftime("%d.%m.%Y %H:%M") if last else "henüz yok"))
        files = backup.list_backups(folder) if folder.exists() else []
        rows = []
        for f in files:
            st = f.stat()
            kind = " (geri yükleme öncesi)" if f.name.startswith(backup.SAFETY_PREFIX) else ""
            rows.append([f.name + kind, Cell(datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M:%S"),
                                             st.st_mtime, "c"), Cell(_size(st.st_size), st.st_size, "r")])
        self.backups.set_rows(rows, [str(f) for f in files])
        i = self.svc.db_info()
        self.db["path"].setText(i["path"])
        self.db["size"].setText(_size(i["size"]))
        self.db["counts"].setText(f"{i['transactions']} işlem · {i['lots']} alış partisi · "
                                  f"{i['item_names']} item adı · {i['products']} ürün (item + upgrade)")
        self.db["version"].setText(APP_VERSION)

    def save(self) -> None:
        try:
            bps = parse_tax_rate(self.tax.text())
            initial = self.initial.value()
            mode = self.mode.currentData()
            self.svc.set_tax_bps(bps)
            self.svc.set_price_mode(mode)
            self.svc.set_initial_balance(initial)
        except UserError as e:
            warn(self, str(e))
            return
        MoneyInput.apply_default_mode(mode)
        self.ctx.bus.settings_changed.emit()
        self.changed()
        info(self, "Ayarlar kaydedildi.")

    def _choose_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Yedekleme klasörünü seçin", self.folder.text())
        if d:
            try:
                Path(d).mkdir(parents=True, exist_ok=True)
                test = Path(d) / ".yazma_testi"
                test.write_text("ok")
                test.unlink()
            except OSError as e:
                warn(self, f"Bu klasöre yazılamıyor: {e}")
                return
            self.svc.set_setting("backup_dir", d)
            self.refresh()

    def _default_folder(self) -> None:
        self.svc.set_setting("backup_dir", str(default_backup_dir()))
        self.refresh()

    def _open(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_folder(self) -> None:
        self._open(Path(self.folder.text()))

    def _backup_now(self) -> None:
        try:
            p = backup.make_backup(self.svc)
        except UserError as e:
            warn(self, str(e))
            return
        self.refresh()
        info(self, f"Yedek alındı:\n{p}")

    def _restore(self, path: Path) -> None:
        if not confirm(self, f"'{path.name}' geri yüklenecek.\n\nMevcut bütün veriler bu yedekteki verilerle "
                             f"DEĞİŞTİRİLECEK. Geri yüklemeden önce mevcut verilerin güvenlik yedeği otomatik alınır.\n\n"
                             f"Devam edilsin mi?", "Yedekten geri yükle", danger=True):
            return
        try:
            safety = backup.restore_backup(self.svc, path)
        except UserError as e:
            warn(self, str(e))
            return
        MoneyInput.apply_default_mode(self.svc.price_mode)
        self.ctx.bus.settings_changed.emit()
        self.changed()
        info(self, f"Yedek geri yüklendi.\n\nÖnceki verilerinizin güvenlik yedeği:\n{safety.name}")

    def _restore_selected(self) -> None:
        p = self.backups.selected_data()
        if not p:
            warn(self, "Önce listeden bir yedek seçin.")
            return
        self._restore(Path(p))

    def _restore_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Yedek dosyası seçin", self.folder.text(),
                                           "Veritabanı yedeği (*.db);;Bütün dosyalar (*)")
        if f:
            self._restore(Path(f))

    def _check(self) -> None:
        if self.svc.integrity_ok():
            info(self, "Veritabanı sağlam. Sorun bulunmadı.")
        else:
            warn(self, "Veritabanında sorun bulundu! Ayarlar > Yedekleme bölümünden son sağlam yedeği geri yükleyin.")

    def _recompute(self) -> None:
        try:
            self.svc.recompute()
        except UserError as e:
            warn(self, str(e))
            return
        self.changed()
        info(self, "Bütün stok, maliyet, kâr ve bakiye hesapları kayıtlardan yeniden kuruldu.")
