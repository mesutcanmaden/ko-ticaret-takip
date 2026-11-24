from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QStackedWidget, QVBoxLayout, QWidget,
)

from ..core.errors import UserError
from ..core.money import fmt_gb
from ..core.paths import APP_NAME, APP_VERSION
from ..core.service import fmt_date
from . import theme
from .dialogs import CashDialog, DetailDialog, EditPurchaseDialog, EditSaleDialog, EditTradeDialog
from .pages.base import Bus, Context
from .pages.buy import BuyPage
from .pages.dashboard import DashboardPage
from .pages.history import HistoryPage
from .pages.sell import SellPage
from .pages.settings import SettingsPage
from .pages.stats import StatsPage
from .pages.stock import StockPage
from .pages.tools import ToolsPage
from .widgets import confirm, info, warn

NAV = [
    ("home", "Ana Sayfa", DashboardPage),
    ("buy", "Item Al", BuyPage),
    ("sell", "Item Sat", SellPage),
    ("stock", "Stoklarım", StockPage),
    ("history", "İşlem Geçmişi", HistoryPage),
    ("stats", "İstatistikler", StatsPage),
    ("tools", "Hesaplama Araçları", ToolsPage),
    ("settings", "Ayarlar", SettingsPage),
]


class MainWindow(QMainWindow):
    def __init__(self, service):
        super().__init__()
        self.svc = service
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1320, 820)
        self.setMinimumSize(QSize(1000, 640))
        self.bus = Bus()
        self.ctx = Context(service, self.bus, self)

        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        nav_panel = QWidget()
        nav_panel.setObjectName("NavPanel")
        nav_panel.setFixedWidth(220)
        nl = QVBoxLayout(nav_panel)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)
        brand = QLabel("KO Ticaret Takip")
        brand.setObjectName("Brand")
        sub = QLabel("Item alış-satış defteri")
        sub.setObjectName("BrandSub")
        nl.addWidget(brand)
        nl.addWidget(sub)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for i, (_k, text, _cls) in enumerate(NAV):
            it = QListWidgetItem(text)
            it.setToolTip(f"{text}  (Ctrl+{i + 1})")
            self.nav.addItem(it)
        nl.addWidget(self.nav, 1)
        self.balance_lbl = QLabel("")
        self.balance_lbl.setWordWrap(True)
        self.balance_lbl.setStyleSheet(f"background: {theme.PANEL}; padding: 12px 16px; color: {theme.MUTED};")
        nl.addWidget(self.balance_lbl)
        h.addWidget(nav_panel)

        self.stack = QStackedWidget()
        self.pages = {}
        for key, _text, cls in NAV:
            page = cls(self.ctx)
            self.pages[key] = page
            self.stack.addWidget(page)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.nav.currentRowChanged.connect(self._switch)
        self.bus.data_changed.connect(self._on_data_changed)
        for i in range(len(NAV)):
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda i=i: self.nav.setCurrentRow(i))
        self.nav.setCurrentRow(0)
        self._update_balance()

    # ------------------------------------------------------------------ #
    def _switch(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        self._refresh_current()

    def _refresh_current(self) -> None:
        page = self.stack.currentWidget()
        try:
            page.refresh()
        except UserError as e:
            warn(self, str(e))

    def _on_data_changed(self) -> None:
        self._refresh_current()
        self._update_balance()

    def _update_balance(self) -> None:
        bal = self.svc.balance()
        color = theme.RED if bal < 0 else theme.ACCENT
        self.balance_lbl.setText(f"Kullanılabilir<br><span style='color:{color}; font-size:12pt; font-weight:600;'>"
                                 f"{fmt_gb(bal)}</span>")

    def go(self, key: str, **kw) -> None:
        idx = [k for k, _t, _c in NAV].index(key)
        if self.nav.currentRow() != idx:
            self.nav.setCurrentRow(idx)
        else:
            self._refresh_current()
        page = self.pages[key]
        if key == "buy" and kw.get("product_id"):
            page.prefill(kw["product_id"])
        elif key == "sell":
            page.open(kw.get("tab", 0), kw.get("product_id"), kw.get("lot_id"))

    # ------------------------------------------------------------------ #
    def cash_dialog(self, kind: str) -> None:
        if CashDialog(self, self.svc, kind).exec():
            self.bus.data_changed.emit()

    def show_detail(self, tx_id: int) -> None:
        try:
            DetailDialog(self, self.svc, tx_id).exec()
        except UserError as e:
            warn(self, str(e))

    def edit_transaction(self, tx_id: int) -> None:
        try:
            typ = self.svc.transaction_summary(tx_id)["type"]
        except UserError as e:
            warn(self, str(e))
            return
        if typ == "purchase":
            dlg = EditPurchaseDialog(self, self.svc, tx_id)
        elif typ == "sale":
            dlg = EditSaleDialog(self, self.svc, tx_id)
        elif typ == "trade":
            dlg = EditTradeDialog(self, self.svc, tx_id)
        else:
            dlg = CashDialog(self, self.svc, typ, tx_id)
        if dlg.exec():
            self.bus.data_changed.emit()

    def _describe(self, s: dict) -> str:
        parts = [f"#{s['id']} · {s['type_name']} · {fmt_date(s['date'])}"]
        if s["items"] and s["items"] != "—":
            parts.append(s["items"])
        parts.append(f"Tutar: {fmt_gb(s['amount'])}")
        return "\n".join(parts)

    def delete_transaction(self, tx_id: int) -> None:
        try:
            s = self.svc.transaction_summary(tx_id)
        except UserError as e:
            warn(self, str(e))
            return
        deps = self.svc.dependents(tx_id)
        if deps:
            warn(self, "Bu işlem silinemez.\n\n" + self._describe(s) + "\n\nBu işlemle gelen itemler şu işlemlerde "
                 "kullanılmış: " + ", ".join(f"#{d}" for d in deps) + ".\nÖnce o işlemleri silmelisiniz.")
            return
        effect = {
            "purchase": "Item stoktan çıkarılacak ve alış tutarı kullanılabilir GB'ye geri eklenecek.",
            "sale": "Satılan itemler stoğa geri dönecek, net satış tutarı kullanılabilir GB'den düşülecek ve "
                    "bu satışın kârı/zararı hesaplardan çıkarılacak.",
            "trade": "Verilen itemler stoğa geri dönecek, alınan itemler stoktan çıkarılacak ve GB farkı geri alınacak.",
            "deposit": "Eklenen GB kullanılabilir bakiyeden düşülecek.",
            "withdraw": "Çıkarılan GB kullanılabilir bakiyeye geri eklenecek.",
        }[s["type"]]
        if not confirm(self, f"Bu işlem silinsin mi?\n\n{self._describe(s)}\n\n{effect}\n\nBu işlem geri alınamaz.",
                       "İşlemi sil", danger=True):
            return
        try:
            self.svc.delete_transaction(tx_id)
        except UserError as e:
            warn(self, str(e))
            return
        self.bus.data_changed.emit()

    def undo_last(self) -> None:
        last = self.svc.last_transaction()
        if not last:
            info(self, "Geri alınacak işlem yok.")
            return
        deps = self.svc.dependents(last["id"])
        if deps:
            warn(self, "Son işlem güvenli şekilde geri alınamıyor.\n\n" + self._describe(last)
                 + "\n\nBu işlemle gelen itemler daha sonra başka işlemlerde kullanılmış: "
                 + ", ".join(f"#{d}" for d in deps) + ".")
            return
        if not confirm(self, "Son kaydedilen işlem geri alınsın mı?\n\n" + self._describe(last)
                       + "\n\nStok, maliyet, bakiye ve kâr hesapları eski durumuna döner.", "Son işlemi geri al"):
            return
        try:
            self.svc.undo_last()
        except UserError as e:
            warn(self, str(e))
            return
        self.bus.data_changed.emit()
        info(self, "İşlem geri alındı.")
