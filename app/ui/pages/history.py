from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton

from ...core.money import fmt_gb
from .. import theme
from ..widgets import Cell, DateInput, Table, date_cell, money_cell, muted, page_title, warn
from .base import Page

TYPE_FILTERS = [
    ("Bütün işlemler", None),
    ("Item alış", ["purchase"]),
    ("Item satış", ["sale"]),
    ("Item takası", ["trade"]),
    ("GB ekleme", ["deposit"]),
    ("GB çıkarma", ["withdraw"]),
    ("GB hareketleri (ekleme + çıkarma)", ["deposit", "withdraw"]),
]
SORTS = [
    ("Tarih (yeniden eskiye)", "date_desc"),
    ("Tarih (eskiden yeniye)", "date_asc"),
    ("Kâr (yüksekten düşüğe)", "profit_desc"),
    ("Kâr (düşükten yükseğe) / en çok zarar", "profit_asc"),
]
TYPE_COLORS = {"purchase": theme.ACCENT, "sale": theme.GREEN, "trade": theme.BLUE}


class HistoryPage(Page):
    title = "İşlem Geçmişi"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.lay.addWidget(page_title("İşlem Geçmişi", "Bütün alış, satış, takas ve GB hareketleri"))
        f1 = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Item adı veya notta ara…")
        self.search.textChanged.connect(self.refresh)
        self.type = QComboBox()
        for t, v in TYPE_FILTERS:
            self.type.addItem(t, v)
        self.type.currentIndexChanged.connect(self.refresh)
        self.sort = QComboBox()
        for t, v in SORTS:
            self.sort.addItem(t, v)
        self.sort.currentIndexChanged.connect(self._sort_changed)
        f1.addWidget(self.search, 2)
        f1.addWidget(self.type, 1)
        f1.addWidget(self.sort, 1)
        self.lay.addLayout(f1)

        f2 = QHBoxLayout()
        self.use_dates = QCheckBox("Tarih aralığı:")
        self.use_dates.toggled.connect(self._toggle_dates)
        self.d_from = DateInput()
        self.d_from.setDate(self.d_from.date().addDays(-30))
        self.d_to = DateInput()
        for w in (self.d_from, self.d_to):
            w.setEnabled(False)
            w.dateChanged.connect(self.refresh)
        f2.addWidget(self.use_dates)
        f2.addWidget(self.d_from)
        f2.addWidget(QLabel("–"))
        f2.addWidget(self.d_to)
        f2.addStretch(1)
        self.count = muted("")
        f2.addWidget(self.count)
        self.lay.addLayout(f2)

        self.table = Table(["#", "Tarih", "Tür", "Item(ler)", "Adet", "Tutar", "Bakiye etkisi", "Kâr/Zarar", "Not"],
                           stretch=3)
        self.table.doubleClicked.connect(lambda _i: self._detail())
        self.lay.addWidget(self.table, 1)

        b = QHBoxLayout()
        for text, slot, name in (("Detay", self._detail, None), ("Düzenle", self._edit, None),
                                 ("Sil", self._delete, "Danger"), ("↶ Son işlemi geri al", ctx.main.undo_last, None)):
            btn = QPushButton(text)
            if name:
                btn.setObjectName(name)
            btn.clicked.connect(slot)
            b.addWidget(btn)
        b.addStretch(1)
        self.totals = muted("")
        b.addWidget(self.totals)
        self.lay.addLayout(b)

    def _sort_changed(self) -> None:
        self.table.reset_sort()
        self.refresh()

    def _toggle_dates(self, on: bool) -> None:
        self.d_from.setEnabled(on)
        self.d_to.setEnabled(on)
        self.refresh()

    def refresh(self) -> None:
        df = self.d_from.iso() if self.use_dates.isChecked() else None
        dt = self.d_to.iso() if self.use_dates.isChecked() else None
        txs = self.svc.list_transactions(self.search.text().strip(), self.type.currentData(), df, dt,
                                         self.sort.currentData())
        rows = []
        for t in txs:
            rows.append([
                Cell(f"#{t['id']}", t["id"], "r"), date_cell(t["date"]),
                Cell(t["type_name"], color=TYPE_COLORS.get(t["type"])), t["items"],
                Cell("" if t["qty"] is None else t["qty"], t["qty"] if t["qty"] is not None else -1, "r"),
                money_cell(t["amount"]), money_cell(t["net_cash"], signed=True, color=True),
                money_cell(t["realized"], signed=True, color=True), t["note"],
            ])
        self.table.set_rows(rows, [t["id"] for t in txs])
        self.count.setText(f"{len(txs)} işlem")
        pl = sum(t["realized"] or 0 for t in txs)
        self.totals.setText(f"Listelenen işlemlerin gerçekleşen kâr/zararı: {fmt_gb(pl, signed=True)}")

    def _selected(self) -> int | None:
        tid = self.table.selected_data()
        if tid is None:
            warn(self, "Önce listeden bir işlem seçin.")
        return tid

    def _detail(self) -> None:
        tid = self._selected()
        if tid:
            self.ctx.main.show_detail(tid)

    def _edit(self) -> None:
        tid = self._selected()
        if tid:
            self.ctx.main.edit_transaction(tid)

    def _delete(self) -> None:
        tid = self._selected()
        if tid:
            self.ctx.main.delete_transaction(tid)

