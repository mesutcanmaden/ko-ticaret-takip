from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QSpinBox

from ...core.errors import UserError
from ...core.money import NOAH_PER_M, fmt_gb, fmt_gb_m, fmt_percent, fmt_rate, round_up_to, slice_cost
from ...core.service import MAX_QTY
from .. import theme
from ..widgets import MoneyInput, fmt_pl, muted, page_title, pl_color
from .base import Page
from .sell import MethodChooser


def _res_label() -> QLabel:
    lbl = QLabel("—")
    lbl.setStyleSheet("font-weight: 600;")
    return lbl


class ToolsPage(Page):
    title = "Hesaplama Araçları"

    def __init__(self, ctx):
        super().__init__(ctx, scroll=True)
        self.lay.addWidget(page_title("Hesaplama Araçları", "Bu araçlar yalnızca hesaplama yapar, kayıt oluşturmaz."))
        row = QHBoxLayout()
        row.setSpacing(14)

        # Hedef satış fiyatı
        tbox = QGroupBox("Hedef satış fiyatı")
        tf = QFormLayout(tbox)
        tf.setVerticalSpacing(9)
        self.t_cost = MoneyInput("Alış fiyatı")
        self.t_target = MoneyInput("Hedef net kâr")
        self.t_method = MethodChooser()
        for w in (self.t_cost, self.t_target):
            w.changed.connect(self.calc_target)
        self.t_method.toggled.connect(self.calc_target)
        tf.addRow("Alış fiyatı (maliyet)", self.t_cost)
        tf.addRow("Hedef net kâr", self.t_target)
        tf.addRow("Satış yöntemi", self.t_method)
        self.t_rate = muted("")
        tf.addRow("", self.t_rate)
        self.t_out = {}
        for k, t in (("price", "Minimum satış fiyatı"), ("rounded", "Yuvarlanmış öneri (M'ye)"),
                     ("tax", "Vergi"), ("net", "Net satış tutarı"), ("profit", "Net kâr")):
            self.t_out[k] = _res_label()
            tf.addRow(t, self.t_out[k])
        self.t_out["price"].setStyleSheet(f"font-size: 13pt; font-weight: 600; color: {theme.ACCENT};")
        self.t_err = QLabel("")
        self.t_err.setStyleSheet(f"color: {theme.RED};")
        tf.addRow(self.t_err)
        row.addWidget(tbox, 1)

        # Teklif hesaplayıcı
        obox = QGroupBox("Teklif hesaplayıcı")
        of = QFormLayout(obox)
        of.setVerticalSpacing(9)
        self.o_source = QComboBox()
        self.o_source.currentIndexChanged.connect(self._source_changed)
        of.addRow("Item / maliyet", self.o_source)
        self.o_qty = QSpinBox()
        self.o_qty.setRange(1, MAX_QTY)
        self.o_qty.valueChanged.connect(self._source_changed)
        of.addRow("Adet", self.o_qty)
        self.o_cost = MoneyInput("Maliyet")
        self.o_cost.changed.connect(self.calc_offer)
        of.addRow("Toplam maliyet", self.o_cost)
        self.o_offer = MoneyInput("Teklif edilen fiyat")
        self.o_offer.changed.connect(self.calc_offer)
        of.addRow("Teklif edilen fiyat (toplam)", self.o_offer)
        self.o_method = MethodChooser()
        self.o_method.toggled.connect(self.calc_offer)
        of.addRow("Satış yöntemi", self.o_method)
        self.o_out = {}
        for k, t in (("tax", "Vergi"), ("net", "Vergi sonrası net tutar"), ("profit", "Net kâr / zarar"),
                     ("pct", "Kâr yüzdesi")):
            self.o_out[k] = _res_label()
            of.addRow(t, self.o_out[k])
        self.o_out["profit"].setStyleSheet("font-size: 13pt; font-weight: 600;")
        self.o_err = QLabel("")
        self.o_err.setStyleSheet(f"color: {theme.RED};")
        of.addRow(self.o_err)
        of.addRow(muted("Stoktan bir item seçerseniz maliyet, en eski partiden başlayarak seçilen adet kadar "
                        "gerçek parti maliyetinden hesaplanır."))
        row.addWidget(obox, 1)
        self.lay.addLayout(row)
        self.lay.addStretch(1)
        self._lots = {}

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        bps = self.svc.tax_bps
        self.t_rate.setText(f"Güncel pazar vergisi: {fmt_rate(bps)} (Ayarlar'dan değiştirilebilir)")
        self.t_method.market.setText(f"Pazar ({fmt_rate(bps)})")
        self.o_method.market.setText(f"Pazar ({fmt_rate(bps)})")
        cur = self.o_source.currentData()
        self.o_source.blockSignals(True)
        self.o_source.clear()
        self.o_source.addItem("Manuel maliyet girişi", None)
        self._lots = {}
        idx = 0
        for i, p in enumerate(self.svc.products_in_stock(), start=1):
            self.o_source.addItem(f"{p['display']} (stok: {p['remaining']})", p["id"])
            if p["id"] == cur:
                idx = i
        self.o_source.setCurrentIndex(idx)
        self.o_source.blockSignals(False)
        self._source_changed()
        self.calc_target()

    def _source_changed(self) -> None:
        pid = self.o_source.currentData()
        self.o_cost.setEnabled(pid is None)
        if pid is None:
            self.o_qty.setMaximum(MAX_QTY)
            self.calc_offer()
            return
        lots = self.svc.lots_for_product(pid, only_available=True)
        total = sum(l["remaining"] for l in lots)
        self.o_qty.blockSignals(True)
        self.o_qty.setMaximum(max(1, total))
        self.o_qty.blockSignals(False)
        left, cost = self.o_qty.value(), 0
        for l in lots:  # en eski partiden başlayarak gerçek maliyet
            take = min(left, l["remaining"])
            if take:  # satış motoruyla aynı kayıpsız maliyet dilimleme
                cost += slice_cost(l["total_cost"], l["qty"], l["qty"] - l["remaining"], take)
            left -= take
        self.o_cost.set_value(cost)

    def calc_target(self) -> None:
        for v in self.t_out.values():
            v.setText("—")
        self.t_err.setText("")
        if self.t_cost.is_empty() or self.t_target.is_empty():
            return
        try:
            r = self.svc.calc_target_price(self.t_cost.value(), self.t_target.value(), self.t_method.value())
        except UserError as e:
            self.t_err.setText(str(e))
            return
        self.t_out["price"].setText(f"{fmt_gb(r['price'])}   ({fmt_gb_m(r['price'])})")
        rounded = round_up_to(r["price"], NOAH_PER_M)
        self.t_out["rounded"].setText(fmt_gb(rounded))
        self.t_out["tax"].setText(fmt_gb(r["tax"]))
        self.t_out["net"].setText(fmt_gb(r["net"]))
        self.t_out["profit"].setText(fmt_pl(r["profit"]))

    def calc_offer(self) -> None:
        for v in self.o_out.values():
            v.setText("—")
        self.o_err.setText("")
        if self.o_offer.is_empty() or self.o_cost.is_empty():
            return
        try:
            r = self.svc.calc_offer(self.o_cost.value(), self.o_offer.value(), self.o_method.value())
        except UserError as e:
            self.o_err.setText(str(e))
            return
        self.o_out["tax"].setText(fmt_gb(r["tax"]))
        self.o_out["net"].setText(fmt_gb(r["net"]))
        self.o_out["profit"].setText(fmt_pl(r["profit"]))
        c = pl_color(r["profit"])
        self.o_out["profit"].setStyleSheet("font-size: 13pt; font-weight: 600;" + (f"color: {c};" if c else ""))
        self.o_out["pct"].setText(fmt_percent(r["percent"]))
