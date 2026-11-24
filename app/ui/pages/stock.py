from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QPushButton, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ...core.errors import UserError
from ...core.money import fmt_gb
from .. import theme
from ..widgets import (
    Cell, DateInput, PriceChart, Table, date_cell, fmt_pl, money_cell, muted, num_cell, page_title, pl_color,
    section, warn,
)
from .base import Page


class ListingDialog(QDialog):
    def __init__(self, parent, lot: dict):
        super().__init__(parent)
        self.setWindowTitle("Satışa çıkar")
        form = QFormLayout(self)
        form.addRow(QLabel(f"<b>{lot['display']}</b> · parti #{lot['id']} · kalan {lot['remaining']} adet"))
        self.qty = QSpinBox()
        self.qty.setRange(1, lot["remaining"])
        self.qty.setValue(max(1, lot["listed"] or lot["remaining"]))
        form.addRow("Satıştaki toplam adet", self.qty)
        self.date = DateInput()
        if lot.get("listed_since"):
            self.date.set_iso(lot["listed_since"])
        form.addRow("Satışa çıkış tarihi", self.date)
        form.addRow(muted("Satışa çıkarılan itemler stoktan düşmez; yalnızca satış tamamlanınca düşer. "
                          "İlan fiyatı kaydedilmez."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class StockPage(Page):
    title = "Stoklarım"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.lay.addWidget(page_title("Stoklarım", "Aynı itemin farklı alışları tek başlıkta birleşir; "
                                                   "her alış partisi ayrıca saklanır."))
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Item ara…")
        self.search.textChanged.connect(self.refresh)
        self.show_sold = QCheckBox("Satılmış (stokta kalmayan) itemleri de göster")
        self.show_sold.toggled.connect(self.refresh)
        oldest = QPushButton("En uzun bekleyenler")
        oldest.setToolTip("Uzun süredir satılmayan itemleri üste sırala")
        oldest.clicked.connect(lambda: self.table.sortItems(7, Qt.SortOrder.DescendingOrder))
        bar.addWidget(self.search, 1)
        bar.addWidget(self.show_sold)
        bar.addWidget(oldest)
        self.lay.addLayout(bar)

        split = QSplitter(Qt.Orientation.Vertical)
        self.table = Table(["Item", "Toplam adet", "Stokta", "Satışta", "Ortalama alış fiyatı", "Toplam maliyet",
                            "Durum", "Stokta bekleme", "Satışta bekleme"], stretch=0)
        self.table.itemSelectionChanged.connect(self._show_detail)
        split.addWidget(self.table)

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 6, 0, 0)
        hdr = QHBoxLayout()
        self.d_title = section("Bir item seçin")
        hdr.addWidget(self.d_title)
        hdr.addStretch(1)
        self.b_rename = QPushButton("İsmi düzenle")
        self.b_rename.clicked.connect(self._rename)
        self.b_buy = QPushButton("Bu itemden al")
        self.b_buy.clicked.connect(self._buy_more)
        hdr.addWidget(self.b_buy)
        hdr.addWidget(self.b_rename)
        dl.addLayout(hdr)
        self.tabs = QTabWidget()

        lots_w = QWidget()
        ll = QVBoxLayout(lots_w)
        self.lots = Table(["Parti", "Alış tarihi", "Kaynak", "Alınan", "Kalan", "Stokta", "Satışta", "Birim maliyet",
                           "Kalan maliyet", "Elde (gün)", "Satışta (gün)"], stretch=None)
        self.lots.doubleClicked.connect(lambda _i: self._open_lot_tx())
        ll.addWidget(self.lots)
        lb = QHBoxLayout()
        self.b_list = QPushButton("Satışa çıkar…")
        self.b_list.clicked.connect(self._list)
        self.b_unlist = QPushButton("Satıştan kaldır")
        self.b_unlist.clicked.connect(self._unlist)
        self.b_sell = QPushButton("Bu partiden sat")
        self.b_sell.setObjectName("Primary")
        self.b_sell.clicked.connect(self._sell)
        for b in (self.b_list, self.b_unlist, self.b_sell):
            lb.addWidget(b)
        lb.addStretch(1)
        lb.addWidget(muted("Çift tıklama: partinin alış kaydını açar"))
        ll.addLayout(lb)
        self.tabs.addTab(lots_w, "Alış partileri")

        hist_w = QWidget()
        hl = QVBoxLayout(hist_w)
        sg = QGridLayout()
        self.h = {}
        for i, (k, t) in enumerate((("avg_buy", "Ortalama alış fiyatı"), ("avg_sell", "Ortalama satış fiyatı"),
                                    ("realized", "Gerçekleşen net kâr/zarar"), ("sold", "Satılan adet"),
                                    ("profit", "Toplam kâr"), ("loss", "Toplam zarar"))):
            sg.addWidget(QLabel(t + ":"), i // 3, (i % 3) * 2)
            self.h[k] = QLabel("—")
            self.h[k].setStyleSheet("font-weight: 600;")
            sg.addWidget(self.h[k], i // 3, (i % 3) * 2 + 1)
        hl.addLayout(sg)
        hs = QSplitter(Qt.Orientation.Horizontal)
        self.hist = Table(["Tarih", "İşlem", "Adet", "Birim fiyat", "Toplam", "Maliyet", "Kâr/Zarar"], stretch=1)
        self.hist.doubleClicked.connect(lambda _i: self._open_hist_tx())
        self.chart = PriceChart()
        hs.addWidget(self.hist)
        hs.addWidget(self.chart)
        hs.setSizes([600, 400])
        hl.addWidget(hs, 1)
        hl.addWidget(muted("Fiyat geçmişi yalnızca programa girdiğiniz işlemlerden oluşur. "
                           "Ortalama alış fiyatı bilgi amaçlıdır; satış kârı seçilen partinin gerçek maliyetiyle hesaplanır."))
        self.tabs.addTab(hist_w, "Fiyat geçmişi")
        dl.addWidget(self.tabs, 1)
        split.addWidget(detail)
        split.setSizes([330, 380])
        self.lay.addWidget(split, 1)
        self._pid = None
        self._lot_rows: dict[int, dict] = {}
        self._set_detail_enabled(False)

    # ------------------------------------------------------------------ #
    def _set_detail_enabled(self, on: bool) -> None:
        for b in (self.b_rename, self.b_buy, self.b_list, self.b_unlist, self.b_sell):
            b.setEnabled(on)

    def refresh(self) -> None:
        rows, data = [], []
        for a in self.svc.stock_overview(self.show_sold.isChecked(), self.search.text()):
            color = {"Satışta": theme.BLUE, "Kısmen satışta": theme.BLUE, "Satıldı": theme.MUTED}.get(a["status"])
            rows.append([
                Cell(a["display"], bold=True), num_cell(a["remaining"]), num_cell(a["in_stock"]),
                num_cell(a["listed"]), money_cell(a["avg_cost"] if a["remaining"] else None),
                money_cell(a["remaining_cost"]), Cell(a["status"], color=color),
                Cell(f"{a['days_held']} gün" if a["days_held"] is not None else "—",
                     a["days_held"] if a["days_held"] is not None else -1, "r"),
                Cell(f"{a['days_listed']} gün" if a["days_listed"] is not None else "—",
                     a["days_listed"] if a["days_listed"] is not None else -1, "r"),
            ])
            data.append(a["product_id"])
        keep = self._pid
        self.table.set_rows(rows, data)
        if keep in data:
            for r in range(self.table.rowCount()):
                if self.table.row_data(r) == keep:
                    self.table.selectRow(r)
                    break
        else:
            self._pid = None
            self._clear_detail()

    def _clear_detail(self) -> None:
        self.d_title.setText("Bir item seçin")
        self.lots.set_rows([])
        self.hist.set_rows([])
        self.chart.set_data([], [])
        for v in self.h.values():
            v.setText("—")
        self._set_detail_enabled(False)

    def _show_detail(self) -> None:
        pid = self.table.selected_data()
        if not pid:
            return
        self._pid = pid
        self._set_detail_enabled(True)
        p = self.svc.product(pid)
        self.d_title.setText(p["display"])
        lots = self.svc.lots_for_product(pid)
        self._lot_rows = {l["id"]: l for l in lots}
        self.lots.set_rows([[
            Cell(f"#{l['id']}", l["id"], "r"), date_cell(l["tx_date"]), l["source"], num_cell(l["qty"]),
            num_cell(l["remaining"]), num_cell(l["in_stock"]), num_cell(l["listed"]),
            money_cell(l["unit_cost"]), money_cell(l["remaining_cost"]),
            num_cell(l["days_held"] if l["remaining"] else None),
            num_cell(l["days_listed"]),
        ] for l in lots], [l["id"] for l in lots])
        h = self.svc.product_history(pid)
        self.h["avg_buy"].setText(fmt_gb(h["avg_buy"]) if h["avg_buy"] is not None else "—")
        self.h["avg_sell"].setText(fmt_gb(h["avg_sell"]) if h["avg_sell"] is not None else "—")
        self.h["realized"].setText(fmt_pl(h["realized"]) if h["sold_qty"] else "—")
        c = pl_color(h["realized"])
        self.h["realized"].setStyleSheet("font-weight: 600;" + (f"color: {c};" if c else ""))
        self.h["sold"].setText(str(h["sold_qty"]))
        self.h["profit"].setText(fmt_gb(h["profit_total"]))
        self.h["loss"].setText(fmt_gb(h["loss_total"]))
        rows, data = [], []
        for b in h["buys"]:
            rows.append([date_cell(b["date"]), Cell(b["source"], color=theme.ACCENT), num_cell(b["qty"]),
                         money_cell(b["unit"]), money_cell(b["total"]), Cell(""), Cell("")])
            data.append(b["tx_id"])
        for s in h["sells"]:
            rows.append([date_cell(s["date"]), Cell(s["kind"], color=theme.GREEN if s["type"] == "sale" else None),
                         num_cell(s["qty"]), money_cell(s["unit"]), money_cell(s["gross"]), money_cell(s["cost"]),
                         money_cell(s["profit"], signed=True, color=True)])
            data.append(s["tx_id"])
        self.hist.set_rows(rows, data)
        self.hist.sortItems(0, Qt.SortOrder.DescendingOrder)
        self.chart.set_data([(b["date"], b["unit"]) for b in h["buys"]],
                            [(s["date"], s["unit"]) for s in h["sells"] if s["unit"] is not None])

    def _selected_lot(self) -> dict | None:
        lid = self.lots.selected_data()
        if lid is None and len(self._lot_rows) == 1:
            lid = next(iter(self._lot_rows))
        lot = self._lot_rows.get(lid) if lid else None
        if lot is None:
            warn(self, "Önce alt tablodan bir alış partisi seçin.")
        return lot

    def _list(self) -> None:
        lot = self._selected_lot()
        if not lot:
            return
        if lot["remaining"] <= 0:
            warn(self, "Bu partide kalan item yok.")
            return
        dlg = ListingDialog(self, lot)
        if dlg.exec():
            try:
                self.svc.set_listing(lot["id"], dlg.qty.value(), dlg.date.iso())
            except UserError as e:
                warn(self, str(e))
                return
            self.changed()

    def _unlist(self) -> None:
        lot = self._selected_lot()
        if not lot:
            return
        if not lot["listed"]:
            warn(self, "Bu partide satışta bekleyen item yok.")
            return
        n, ok = QInputDialog.getInt(self, "Satıştan kaldır",
                                    f"{lot['display']} · parti #{lot['id']}\nKaç adet satıştan kaldırılsın?",
                                    lot["listed"], 1, lot["listed"])
        if not ok:
            return
        try:
            self.svc.set_listing(lot["id"], lot["listed"] - n)
        except UserError as e:
            warn(self, str(e))
            return
        self.changed()

    def _sell(self) -> None:
        lot = self._selected_lot()
        if not lot:
            return
        if lot["remaining"] <= 0:
            warn(self, "Bu partide kalan item yok.")
            return
        self.ctx.main.go("sell", product_id=self._pid, lot_id=lot["id"])

    def _buy_more(self) -> None:
        if self._pid:
            self.ctx.main.go("buy", product_id=self._pid)

    def _rename(self) -> None:
        if not self._pid:
            return
        p = self.svc.product(self._pid)
        new, ok = QInputDialog.getText(
            self, "İsmi düzenle",
            f"'{p['name']}' itemi için yeni ad (bütün upgrade seviyeleri ve geçmiş kayıtlar güncellenir):",
            QLineEdit.EchoMode.Normal, p["name"])
        if not ok or not new.strip() or new.strip() == p["name"]:
            return
        try:
            self.svc.rename_item(p["name_id"], new)
        except UserError as e:
            warn(self, str(e))
            return
        self.changed()

    def _open_lot_tx(self) -> None:
        lot = self._lot_rows.get(self.lots.selected_data())
        if lot:
            self.ctx.main.show_detail(lot["tx_id"])

    def _open_hist_tx(self) -> None:
        tid = self.hist.selected_data()
        if tid:
            self.ctx.main.show_detail(tid)

