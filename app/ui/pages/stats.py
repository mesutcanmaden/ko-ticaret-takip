from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ...core.money import fmt_gb
from ...core.service import PERIODS
from .. import theme
from ..widgets import BarChart, Card, Cell, PeriodSelector, Table, money_cell, muted, num_cell, page_title, section
from .base import Page


class StatsPage(Page):
    title = "İstatistikler"

    def __init__(self, ctx):
        super().__init__(ctx, scroll=True)
        top = QHBoxLayout()
        top.addWidget(page_title("İstatistikler", "Yalnızca gerçekleşen (tamamlanmış) satış ve takaslar"))
        top.addStretch(1)
        self.period = PeriodSelector()
        self.period.changed.connect(lambda _k: self.refresh())
        top.addWidget(self.period)
        self.lay.addLayout(top)

        g = QGridLayout()
        g.setSpacing(10)
        self.cards = {}
        for i, (k, t) in enumerate((("net", "Gerçekleşen net kâr"), ("profit", "Gerçekleşen kâr"),
                                    ("loss", "Gerçekleşen zarar"), ("sales", "Toplam satış tutarı"),
                                    ("buys", "Toplam alış tutarı"), ("units", "Satılan item sayısı"),
                                    ("days", "Ortalama satış süresi"), ("tax", "Ödenen pazar vergisi"))):
            self.cards[k] = Card(t)
            g.addWidget(self.cards[k], i // 4, i % 4)
        self.lay.addLayout(g)

        self.chart_title = section("Kâr-zarar grafiği")
        self.lay.addWidget(self.chart_title)
        self.chart = BarChart()
        self.chart.setMinimumHeight(240)
        self.lay.addWidget(self.chart)

        row = QHBoxLayout()
        row.setSpacing(12)
        for attr, title in (("t_top", "En kârlı itemler"), ("t_loss", "En çok zarar ettiren itemler")):
            w = QWidget()
            l = QVBoxLayout(w)
            l.setContentsMargins(0, 0, 0, 0)
            l.addWidget(section(title))
            t = Table(["Item", "Satış sayısı", "Adet", "Satış tutarı", "Kâr/Zarar"], stretch=0)
            t.setMinimumHeight(260)
            l.addWidget(t)
            setattr(self, attr, t)
            row.addWidget(w, 1)
        self.lay.addLayout(row)
        self.trade_lbl = muted("")
        self.lay.addWidget(self.trade_lbl)
        self.lay.addWidget(muted("Henüz satılmamış itemlerin değeri kâr olarak gösterilmez. Kâr hesabında her satışın "
                                 "gerçek parti maliyeti ve o satışta uygulanan vergi kullanılır."))
        self.lay.addStretch(1)

    def refresh(self) -> None:
        p = self.period.current
        d = self.svc.statistics(p)
        net = d["net_profit"]
        self.cards["net"].set(fmt_gb(net, signed=True), PERIODS[p],
                              theme.GREEN if net > 0 else theme.RED if net < 0 else None)
        self.cards["profit"].set(fmt_gb(d["profit"]), "", theme.GREEN if d["profit"] else None)
        self.cards["loss"].set(fmt_gb(d["loss"]), "", theme.RED if d["loss"] else None)
        self.cards["sales"].set(fmt_gb(d["sales_gross"]), f"{d['sale_count']} satış · net {fmt_gb(d['sales_net'])}")
        self.cards["buys"].set(fmt_gb(d["purchase_total"]), f"{d['purchase_count']} alış")
        self.cards["units"].set(str(d["sold_units"]))
        self.cards["days"].set(f"{str(d['avg_days_to_sell']).replace('.', ',')} gün"
                               if d["avg_days_to_sell"] is not None else "—", "Alıştan satışa (adet ağırlıklı)")
        self.cards["tax"].set(fmt_gb(d["tax_total"]))
        self.chart_title.setText("Kâr-zarar grafiği · " + ("aylık" if p == "all" else "günlük"))
        self.chart.set_data(d["chart"])

        def rows(items):
            return [[Cell(a["display"], bold=True), num_cell(a["count"]), num_cell(a["qty"]), money_cell(a["gross"]),
                     money_cell(a["realized"], signed=True, color=True)] for a in items]

        self.t_top.set_rows(rows(d["top_profit"]))
        self.t_loss.set_rows(rows(d["top_loss"]))
        self.trade_lbl.setText(f"Takaslardan gerçekleşen kâr/zarar ({PERIODS[p].lower()}): "
                               f"{fmt_gb(d['trade_realized'], signed=True)} · Takas sayısı: {d['trade_count']}")
