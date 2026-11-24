from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QCompleter, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ...core.errors import UserError
from ...core.money import fmt_gb, fmt_percent, fmt_rate, profit_percent
from ...core.service import MAX_QTY, display_name, fmt_date, split_name_upgrade
from .. import theme
from ..widgets import (
    Cell, DateInput, ItemNameInput, MoneyInput, Table, UpgradeCombo, confirm, date_cell, fmt_pl, money_cell, muted, page_title,
    pl_color, section, warn,
)
from .base import Page
from .buy import resolve_item_name


def _value_label() -> QLabel:
    lbl = QLabel("—")
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def _searchable_combo() -> QComboBox:
    cb = QComboBox()
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    cb.completer().setFilterMode(Qt.MatchFlag.MatchContains)
    cb.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    cb.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    cb.setMinimumWidth(320)
    return cb


class MethodChooser(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.market = QRadioButton("Pazar satışı (vergili)")
        self.trade = QRadioButton("Trade (vergisiz)")
        self.market.setChecked(True)
        g = QButtonGroup(self)
        g.addButton(self.market)
        g.addButton(self.trade)
        lay.addWidget(self.market)
        lay.addWidget(self.trade)
        lay.addStretch(1)
        self.toggled = self.market.toggled

    def value(self) -> str:
        return "market" if self.market.isChecked() else "trade"

    def set_value(self, v: str) -> None:
        (self.market if v == "market" else self.trade).setChecked(True)


# --------------------------------------------------------------------------- #
# Satış
# --------------------------------------------------------------------------- #
class SaleTab(QWidget):
    def __init__(self, page: "SellPage"):
        super().__init__()
        self.page = page
        self.svc = page.svc
        self._spins: dict[int, QSpinBox] = {}
        self._lots: list[dict] = []
        self._pref_lot: int | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(14)

        left = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(QLabel("Item"))
        self.product = _searchable_combo()
        self.product.currentIndexChanged.connect(self._load_lots)
        top.addWidget(self.product, 1)
        left.addLayout(top)
        left.addWidget(section("Alış partileri"))
        left.addWidget(muted("Hangi partiden satış yaptığınızı seçin. Varsayılan: en eski parti. "
                             "Gerçekleşen kâr, seçilen partilerin gerçek maliyetine göre hesaplanır."))
        self.lots = Table(["Parti", "Alış tarihi", "Kaynak", "Birim maliyet", "Kalan", "Satışta", "Elde",
                           "Satılacak adet"], stretch=None, sortable=False)
        left.addWidget(self.lots, 1)
        qrow = QHBoxLayout()
        qrow.addWidget(QLabel("Satılacak toplam adet"))
        self.total_qty = QSpinBox()
        self.total_qty.setRange(0, MAX_QTY)
        self.total_qty.valueChanged.connect(self._distribute)
        qrow.addWidget(self.total_qty)
        fifo = QPushButton("En eskiden dağıt")
        fifo.setToolTip("Toplam adedi en eski partiden başlayarak dağıtır")
        fifo.clicked.connect(lambda: self._distribute(self.total_qty.value()))
        qrow.addWidget(fifo)
        self.avail_lbl = muted("")
        qrow.addWidget(self.avail_lbl)
        qrow.addStretch(1)
        left.addLayout(qrow)
        lay.addLayout(left, 3)

        right = QVBoxLayout()
        box = QGroupBox("Satış bilgileri")
        form = QFormLayout(box)
        form.setVerticalSpacing(9)
        pr = QWidget()
        prl = QHBoxLayout(pr)
        prl.setContentsMargins(0, 0, 0, 0)
        self.price = MoneyInput("Satış fiyatı")
        self.price.changed.connect(self._preview)
        self.price.gb.returnPressed.connect(self.save)
        self.price.m.returnPressed.connect(self.save)
        self.basis = QComboBox()
        self.basis.addItems(["birim fiyat", "toplam fiyat"])
        self.basis.currentIndexChanged.connect(self._preview)
        prl.addWidget(self.price, 1)
        prl.addWidget(self.basis)
        form.addRow("Satış fiyatı", pr)
        self.method = MethodChooser()
        self.method.toggled.connect(self._preview)
        form.addRow("Satış yöntemi", self.method)
        self.date = DateInput()
        self.date.dateChanged.connect(self._preview)
        form.addRow("Satış tarihi", self.date)
        self.note = QLineEdit()
        self.note.setMaxLength(500)
        self.note.setPlaceholderText("İsteğe bağlı (örn. Trade üzerinden satıldı.)")
        form.addRow("İşlem notu", self.note)
        right.addWidget(box)

        pv = QGroupBox("Önizleme")
        g = QGridLayout(pv)
        self.pv = {}
        for i, (k, t) in enumerate((("gross", "Brüt satış tutarı"), ("tax", "Pazar vergisi"), ("net", "Net satış tutarı"),
                                    ("cost", "Satılan itemlerin maliyeti"), ("profit", "Net kâr / zarar"),
                                    ("pct", "Kâr oranı"))):
            g.addWidget(QLabel(t), i, 0)
            self.pv[k] = _value_label()
            g.addWidget(self.pv[k], i, 1)
        self.pv["profit"].setStyleSheet("font-size: 12pt; font-weight: 600;")
        self.err = QLabel("")
        self.err.setWordWrap(True)
        self.err.setStyleSheet(f"color: {theme.RED};")
        g.addWidget(self.err, 6, 0, 1, 2)
        right.addWidget(pv)
        btn = QPushButton("Satışı Kaydet")
        btn.setObjectName("Primary")
        btn.clicked.connect(self.save)
        right.addWidget(btn)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {theme.GREEN};")
        right.addWidget(self.status)
        right.addStretch(1)
        rw = QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(380)
        rw.setMaximumWidth(480)
        lay.addWidget(rw, 2)

    # ------------------------------------------------------------------ #
    def reload_products(self, select_product: int | None = None, select_lot: int | None = None) -> None:
        current = select_product if select_product is not None else self.product.currentData()
        self._pref_lot = select_lot
        self.product.blockSignals(True)
        self.product.clear()
        self.product.addItem("— Satılacak itemi seçin —", None)
        idx = 0
        for i, p in enumerate(self.svc.products_in_stock(), start=1):
            extra = f" · satışta {p['listed']}" if p["listed"] else ""
            self.product.addItem(f"{p['display']}  (stok: {p['remaining']}{extra})", p["id"])
            if p["id"] == current:
                idx = i
        self.product.setCurrentIndex(idx)
        self.product.blockSignals(False)
        self._load_lots()

    def _load_lots(self) -> None:
        pid = self.product.currentData()
        self._spins = {}
        self._lots = self.svc.lots_for_product(pid, only_available=True) if pid else []
        rows = []
        for lot in self._lots:
            rows.append([Cell(f"#{lot['id']}", align="r"), date_cell(lot["tx_date"]), lot["source"],
                         money_cell(lot["unit_cost"]), Cell(lot["remaining"], align="r"),
                         Cell(lot["listed"] or "", align="r"), Cell(f"{lot['days_held']} gün", align="r"), ""])
        self.lots.set_rows(rows, [lot["id"] for lot in self._lots])
        for r, lot in enumerate(self._lots):
            sp = QSpinBox()
            sp.setRange(0, lot["remaining"])
            sp.valueChanged.connect(self._lot_spin_changed)
            self.lots.setCellWidget(r, 7, sp)
            self._spins[lot["id"]] = sp
        total = sum(l["remaining"] for l in self._lots)
        self.total_qty.blockSignals(True)
        self.total_qty.setMaximum(total)
        self.total_qty.blockSignals(False)
        self.avail_lbl.setText(f"Mevcut: {total} adet" if pid else "")
        pref, self._pref_lot = self._pref_lot, None
        if pref and pref in self._spins:
            for sp in self._spins.values():
                sp.blockSignals(True)
                sp.setValue(0)
                sp.blockSignals(False)
            self._spins[pref].setValue(1)
        else:
            self.total_qty.setValue(1 if total else 0)
            self._distribute(self.total_qty.value())
        self._preview()

    def _distribute(self, qty: int) -> None:
        left = qty
        for lot in self._lots:  # en eski parti önce
            sp = self._spins[lot["id"]]
            take = min(left, lot["remaining"])
            sp.blockSignals(True)
            sp.setValue(take)
            sp.blockSignals(False)
            left -= take
        self._preview()

    def _lot_spin_changed(self) -> None:
        self.total_qty.blockSignals(True)
        self.total_qty.setValue(sum(sp.value() for sp in self._spins.values()))
        self.total_qty.blockSignals(False)
        self._preview()

    def _alloc(self) -> dict[int, int]:
        return {lid: sp.value() for lid, sp in self._spins.items() if sp.value() > 0}

    def _gross(self, qty: int) -> int:
        v = self.price.value()
        return v * qty if self.basis.currentIndex() == 0 else v

    def _preview(self) -> None:
        for lbl in self.pv.values():
            lbl.setText("—")
        self.pv["profit"].setStyleSheet("font-size: 12pt; font-weight: 600;")
        self.err.setText("")
        pid = self.product.currentData()
        alloc = self._alloc()
        bps = self.svc.tax_bps
        self.method.market.setText(f"Pazar satışı (vergi {fmt_rate(bps)})")
        if not pid or not alloc or self.price.is_empty():
            return
        try:
            qty = sum(alloc.values())
            res = self.svc.preview_sale(pid, alloc, self._gross(qty), self.method.value(), self.date.iso())
        except UserError as e:
            self.err.setText(str(e))
            return
        self.pv["gross"].setText(fmt_gb(res["gross"]))
        self.pv["tax"].setText(fmt_gb(res["tax"]) + (f"  ({fmt_rate(res['tax_bps'])})" if res["tax"] else ""))
        self.pv["net"].setText(fmt_gb(res["net"]))
        self.pv["cost"].setText(fmt_gb(res["cost"]))
        self.pv["profit"].setText(fmt_pl(res["profit"]))
        c = pl_color(res["profit"])
        self.pv["profit"].setStyleSheet("font-size: 12pt; font-weight: 600;" + (f"color: {c};" if c else ""))
        self.pv["pct"].setText(fmt_percent(profit_percent(res["profit"], res["cost"])))

    def save(self) -> None:
        pid = self.product.currentData()
        try:
            if not pid:
                raise UserError("Satılacak itemi seçin.")
            alloc = self._alloc()
            if not alloc:
                raise UserError("Satılacak adet seçilmedi.")
            qty = sum(alloc.values())
            gross = self._gross(qty)
            method = self.method.value()
            res = self.svc.preview_sale(pid, alloc, gross, method, self.date.iso())
            if res["profit"] < 0 and not confirm(
                    self, f"Bu satış {fmt_gb(-res['profit'])} ZARAR ile sonuçlanacak.\nYine de kaydedilsin mi?",
                    "Zararlı satış"):
                return
            self.svc.record_sale(pid, alloc, gross, method, self.date.iso(), self.note.text())
        except UserError as e:
            warn(self, str(e))
            return
        name = self.svc.product(pid)["display"]
        self.status.setText(f"✓ Satış kaydedildi: {name} ×{qty} · net {fmt_gb(res['net'])} · "
                            f"kâr/zarar {fmt_pl(res['profit'])}")
        self.price.clear()
        self.note.clear()
        self.page.changed()


# --------------------------------------------------------------------------- #
# Takas
# --------------------------------------------------------------------------- #
class TradeTab(QWidget):
    def __init__(self, page: "SellPage"):
        super().__init__()
        self.page = page
        self.svc = page.svc
        self.given: list[dict] = []
        self.received: list[dict] = []
        self._last_preview = None
        self._lot_info: dict[int, dict] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)
        outer.addWidget(muted(
            "Takasta verilen itemlerin GERÇEK maliyeti (± verilen/alınan GB), alınan itemlere anlaşılan değerleri "
            "oranında aktarılır. Takas tek başına kâr üretmez; kâr/zarar alınan item satıldığında oluşur. "
            "Yalnızca aldığınız GB, verdiklerinizin toplam maliyetini aşarsa aradaki fark kâr sayılır."))
        cols = QHBoxLayout()
        cols.setSpacing(14)

        # Verilenler
        gbox = QGroupBox("Verdiğim itemler")
        gl = QVBoxLayout(gbox)
        r1 = QHBoxLayout()
        self.lot_combo = _searchable_combo()
        self.lot_combo.currentIndexChanged.connect(self._lot_selected)
        self.give_qty = QSpinBox()
        self.give_qty.setRange(1, MAX_QTY)
        add_g = QPushButton("Ekle")
        add_g.clicked.connect(self._add_given)
        r1.addWidget(self.lot_combo, 1)
        r1.addWidget(QLabel("Adet"))
        r1.addWidget(self.give_qty)
        r1.addWidget(add_g)
        gl.addLayout(r1)
        self.t_given = Table(["Item", "Parti", "Adet", "Tahmini maliyet"], stretch=0, sortable=False)
        gl.addWidget(self.t_given)
        rm_g = QPushButton("Seçiliyi kaldır")
        rm_g.clicked.connect(lambda: self._remove(self.t_given, self.given))
        gl.addWidget(rm_g, 0, Qt.AlignmentFlag.AlignLeft)
        cols.addWidget(gbox, 1)

        # Alınanlar
        rbox = QGroupBox("Aldığım itemler")
        rl = QVBoxLayout(rbox)
        r2 = QGridLayout()
        self.rec_name = ItemNameInput()
        self.rec_upg = UpgradeCombo()
        self.rec_qty = QSpinBox()
        self.rec_qty.setRange(1, MAX_QTY)
        self.rec_val = MoneyInput("Anlaşılan değer", allow_empty=True)
        self.rec_val.setToolTip("Bu itemin takasta anlaşılan birim değeri. Maliyet dağıtımında oran olarak kullanılır.")
        add_r = QPushButton("Ekle")
        add_r.clicked.connect(self._add_received)
        r2.addWidget(QLabel("Item"), 0, 0)
        r2.addWidget(self.rec_name, 0, 1, 1, 3)
        r2.addWidget(QLabel("Upgrade"), 1, 0)
        r2.addWidget(self.rec_upg, 1, 1)
        r2.addWidget(QLabel("Adet"), 1, 2)
        r2.addWidget(self.rec_qty, 1, 3)
        r2.addWidget(QLabel("Anlaşılan birim değer"), 2, 0)
        r2.addWidget(self.rec_val, 2, 1, 1, 2)
        r2.addWidget(add_r, 2, 3)
        rl.addLayout(r2)
        self.t_rec = Table(["Item", "Adet", "Anlaşılan değer (birim)", "Atanan maliyet", "Birim maliyet"],
                           stretch=0, sortable=False)
        rl.addWidget(self.t_rec)
        rm_r = QPushButton("Seçiliyi kaldır")
        rm_r.clicked.connect(lambda: self._remove(self.t_rec, self.received))
        rl.addWidget(rm_r, 0, Qt.AlignmentFlag.AlignLeft)
        cols.addWidget(rbox, 1)
        outer.addLayout(cols, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        cbox = QGroupBox("GB, tarih ve not")
        cf = QFormLayout(cbox)
        self.cash_out = MoneyInput("Verdiğim GB", allow_empty=True)
        self.cash_in = MoneyInput("Aldığım GB", allow_empty=True)
        self.cash_out.changed.connect(self._preview)
        self.cash_in.changed.connect(self._preview)
        cf.addRow("Verdiğim GB", self.cash_out)
        cf.addRow("Aldığım GB", self.cash_in)
        self.date = DateInput()
        self.date.dateChanged.connect(self._preview)
        cf.addRow("Takas tarihi", self.date)
        self.note = QLineEdit()
        self.note.setMaxLength(500)
        self.note.setPlaceholderText("İsteğe bağlı (örn. Takasla alındı.)")
        cf.addRow("Not", self.note)
        bottom.addWidget(cbox, 1)

        pbox = QGroupBox("Takasın etkisi (kaydetmeden önce)")
        pg = QGridLayout(pbox)
        self.pv = {}
        for i, (k, t) in enumerate((("given", "Verilen itemlerin gerçek maliyeti"), ("out", "+ Verilen GB"),
                                    ("in", "− Alınan GB"), ("basis", "= Alınan itemlere aktarılan maliyet"),
                                    ("realized", "Gerçekleşen kâr / zarar"), ("bal", "Kullanılabilir GB etkisi"))):
            pg.addWidget(QLabel(t), i, 0)
            self.pv[k] = _value_label()
            pg.addWidget(self.pv[k], i, 1)
        self.err = QLabel("")
        self.err.setWordWrap(True)
        self.err.setStyleSheet(f"color: {theme.RED};")
        pg.addWidget(self.err, 6, 0, 1, 2)
        btn = QPushButton("Takası Kaydet")
        btn.setObjectName("Primary")
        btn.clicked.connect(self.save)
        pg.addWidget(btn, 7, 0, 1, 2)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {theme.GREEN};")
        pg.addWidget(self.status, 8, 0, 1, 2)
        bottom.addWidget(pbox, 1)
        outer.addLayout(bottom)

    # ------------------------------------------------------------------ #
    def reload(self) -> None:
        self.rec_name.set_suggestions(self.svc.completion_list())
        cur = self.lot_combo.currentData()
        self.lot_combo.blockSignals(True)
        self.lot_combo.clear()
        self.lot_combo.addItem("— Verilecek itemi seçin —", None)
        self._lot_info = {}
        idx = 0
        for i, lot in enumerate(self.svc.available_lots(), start=1):
            self._lot_info[lot["id"]] = lot
            self.lot_combo.addItem(
                f"{lot['display']} · parti #{lot['id']} · {fmt_date(lot['tx_date'])} · kalan {lot['remaining']} · "
                f"birim {fmt_gb(lot['unit_cost'])}", lot["id"])
            if lot["id"] == cur:
                idx = i
        self.lot_combo.setCurrentIndex(idx)
        self.lot_combo.blockSignals(False)
        # artık mevcut olmayan partileri listeden çıkar
        self.given = [g for g in self.given if g["lot_id"] in self._lot_info]
        self._render()

    def _lot_selected(self) -> None:
        lid = self.lot_combo.currentData()
        lot = self._lot_info.get(lid) if lid else None
        self.give_qty.setMaximum(lot["remaining"] if lot else MAX_QTY)

    def _add_given(self) -> None:
        lid = self.lot_combo.currentData()
        if not lid:
            warn(self, "Verilecek itemi seçin.")
            return
        lot = self._lot_info[lid]
        q = self.give_qty.value()
        existing = next((g for g in self.given if g["lot_id"] == lid), None)
        already = existing["qty"] if existing else 0
        if already + q > lot["remaining"]:
            warn(self, f"Bu partide yalnızca {lot['remaining']} adet var.")
            return
        if existing:
            existing["qty"] += q
        else:
            self.given.append({"lot_id": lid, "qty": q, "display": lot["display"],
                               "unit_cost": (lot["remaining_cost"] / lot["remaining"]) if lot["remaining"] else 0})
        self._render()

    def _add_received(self) -> None:
        try:
            raw = self.rec_name.text().strip()
            if not raw:
                raise UserError("Alınan item adını yazın.")
            name, up = split_name_upgrade(raw)
            up = self.rec_upg.value() if up is None else up
            val = self.rec_val.value()
        except UserError as e:
            warn(self, str(e))
            return
        name = resolve_item_name(self, self.svc, name)
        if name is None:
            return
        self.received.append({"name": name, "upgrade": up, "qty": self.rec_qty.value(), "agreed_value": val})
        self.rec_name.clear()
        self.rec_upg.setValue(0)
        self.rec_qty.setValue(1)
        self.rec_val.clear()
        self._render()

    def _remove(self, table: Table, lst: list) -> None:
        rows = table.selectionModel().selectedRows()
        if not rows:
            return
        i = rows[0].row()
        if 0 <= i < len(lst):
            lst.pop(i)
        self._render()

    def _render(self) -> None:
        self.t_given.set_rows([[g["display"], f"#{g['lot_id']}", Cell(g["qty"], align="r"),
                                money_cell(round(g["unit_cost"] * g["qty"]))] for g in self.given])
        self._preview()

    def _render_received(self, pv: dict | None) -> None:
        rows = []
        for i, r in enumerate(self.received):
            assigned = pv["received"][i] if pv and i < len(pv["received"]) else None
            rows.append([display_name(r["name"], r["upgrade"]), Cell(r["qty"], align="r"),
                         money_cell(r["agreed_value"]),
                         money_cell(assigned["cost"]) if assigned else Cell("—", align="r"),
                         money_cell(assigned["unit_cost"]) if assigned else Cell("—", align="r")])
        self.t_rec.set_rows(rows)

    def _args(self):
        return ([(g["lot_id"], g["qty"]) for g in self.given], list(self.received),
                self.cash_out.value(), self.cash_in.value(), self.date.iso())

    def _preview(self) -> None:
        self._last_preview = None
        for lbl in self.pv.values():
            lbl.setText("—")
            lbl.setStyleSheet("")
        self.err.setText("")
        if not self.given and not self.received:
            self._render_received(None)
            return
        try:
            pv = self.svc.preview_trade(*self._args())
        except UserError as e:
            self.err.setText(str(e))
            self._render_received(None)
            return
        self._last_preview = pv
        self.pv["given"].setText(fmt_gb(pv["given_cost"]))
        self.pv["out"].setText(fmt_gb(pv["cash_out"]))
        self.pv["in"].setText(fmt_gb(pv["cash_in"]))
        self.pv["basis"].setText(fmt_gb(pv["assigned_total"]))
        self.pv["realized"].setText(fmt_pl(pv["realized"]))
        c = pl_color(pv["realized"])
        self.pv["realized"].setStyleSheet("font-weight: 600;" + (f"color: {c};" if c else ""))
        self.pv["bal"].setText(fmt_gb(pv["balance_effect"], signed=True))
        self._render_received(pv)

    def save(self) -> None:
        try:
            pv = self.svc.preview_trade(*self._args())
        except UserError as e:
            warn(self, str(e))
            return
        lines = [f"Verilen itemlerin maliyeti: {fmt_gb(pv['given_cost'])}",
                 f"Verilen GB: {fmt_gb(pv['cash_out'])}   ·   Alınan GB: {fmt_gb(pv['cash_in'])}"]
        for r in pv["received"]:
            lines.append(f"  • {r['display']} ×{r['qty']} → atanan maliyet {fmt_gb(r['cost'])}")
        lines.append(f"Gerçekleşen kâr/zarar: {fmt_pl(pv['realized'])}")
        lines.append(f"Kullanılabilir GB değişimi: {fmt_gb(pv['balance_effect'], signed=True)}")
        if not confirm(self, "Takas kaydedilsin mi?\n\n" + "\n".join(lines), "Takası onayla"):
            return
        try:
            g, r, co, ci, d = self._args()
            self.svc.record_trade(g, r, co, ci, d, self.note.text())
        except UserError as e:
            warn(self, str(e))
            return
        self.given, self.received = [], []
        self.cash_in.clear()
        self.cash_out.clear()
        self.note.clear()
        self.status.setText("✓ Takas kaydedildi.")
        self.page.changed()


# --------------------------------------------------------------------------- #
class SellPage(Page):
    title = "Item Sat"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.lay.addWidget(page_title("Item Sat", "Satış ve takas işlemleri"))
        self.tabs = QTabWidget()
        self.sale = SaleTab(self)
        self.trade = TradeTab(self)
        self.tabs.addTab(self.sale, "Satış")
        self.tabs.addTab(self.trade, "Takas")
        self.lay.addWidget(self.tabs, 1)

    def open(self, tab: int = 0, product_id: int | None = None, lot_id: int | None = None) -> None:
        self.tabs.setCurrentIndex(tab)
        if product_id:
            self.sale.reload_products(product_id, lot_id)

    def refresh(self) -> None:
        self.sale.reload_products()
        self.trade.reload()
