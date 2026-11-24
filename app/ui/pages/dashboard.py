from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ...core.money import fmt_gb
from ...core.service import PERIODS
from .. import theme
from ..widgets import Card, Cell, PeriodSelector, Table, date_cell, money_cell, muted, page_title, section
from .base import Page


class DashboardPage(Page):
    title = "Ana Sayfa"

    def __init__(self, ctx):
        super().__init__(ctx, scroll=True)
        top = QHBoxLayout()
        top.addWidget(page_title("Ana Sayfa", "Ticaretinizin genel durumu"))
        top.addStretch(1)
        self.period = PeriodSelector()
        self.period.changed.connect(lambda _k: self.refresh())
        top.addWidget(self.period)
        self.lay.addLayout(top)

        # Hızlı işlemler
        q = QHBoxLayout()
        q.setSpacing(8)
        for text, slot, primary in (
            ("＋ Item Al", lambda: ctx.main.go("buy"), True),
            ("Item Sat", lambda: ctx.main.go("sell"), True),
            ("Takas", lambda: ctx.main.go("sell", tab=1), False),
            ("GB Ekle", lambda: ctx.main.cash_dialog("deposit"), False),
            ("GB Çıkar", lambda: ctx.main.cash_dialog("withdraw"), False),
            ("↶ Son İşlemi Geri Al", lambda: ctx.main.undo_last(), False),
        ):
            b = QPushButton(text)
            if primary:
                b.setObjectName("Primary")
            b.clicked.connect(slot)
            q.addWidget(b)
        q.addStretch(1)
        self.lay.addLayout(q)

        # Anlık durum kartları (dönemden bağımsız)
        self.lay.addWidget(section("Şu anki durum"))
        g1 = QGridLayout()
        g1.setSpacing(10)
        self.c_balance = Card("Kullanılabilir GB")
        self.c_stock = Card("Stoktaki item (adet)")
        self.c_listed = Card("Satışta bekleyen (adet)")
        self.c_cost = Card("Stoktaki itemlerin alış maliyeti")
        for i, c in enumerate((self.c_balance, self.c_stock, self.c_listed, self.c_cost)):
            g1.addWidget(c, 0, i)
        self.lay.addLayout(g1)

        self.period_lbl = section("")
        self.lay.addWidget(self.period_lbl)
        g2 = QGridLayout()
        g2.setSpacing(10)
        self.c_net = Card("Gerçekleşen net kâr")
        self.c_profit = Card("Gerçekleşen toplam kâr")
        self.c_loss = Card("Gerçekleşen toplam zarar")
        self.c_buy = Card("Toplam alış tutarı")
        self.c_sell = Card("Toplam satış tutarı")
        self.c_count = Card("Tamamlanan satış sayısı")
        for i, c in enumerate((self.c_net, self.c_profit, self.c_loss, self.c_buy, self.c_sell, self.c_count)):
            g2.addWidget(c, i // 3, i % 3)
        self.lay.addLayout(g2)
        self.lay.addWidget(muted("Kâr/zarar yalnızca tamamlanan satış ve takaslardan hesaplanır. "
                                 "Stoktaki itemlerin maliyeti kâr değildir; GB ekleme/çıkarma kâr sayılmaz."))

        # Son işlemler
        rec = QHBoxLayout()
        rec.setSpacing(12)
        left, right = QWidget(), QWidget()
        ll, rl = QVBoxLayout(left), QVBoxLayout(right)
        ll.setContentsMargins(0, 0, 0, 0)
        rl.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(section("Son alışlar"))
        self.t_buys = Table(["Tarih", "Item", "Adet", "Tutar"], stretch=1, sortable=False)
        self.t_buys.setMinimumHeight(250)
        ll.addWidget(self.t_buys)
        rl.addWidget(section("Son satışlar"))
        self.t_sales = Table(["Tarih", "Item", "Adet", "Satış", "Kâr/Zarar"], stretch=1, sortable=False)
        self.t_sales.setMinimumHeight(250)
        rl.addWidget(self.t_sales)
        rec.addWidget(left, 1)
        rec.addWidget(right, 1)
        self.lay.addLayout(rec)
        self.t_buys.doubleClicked.connect(lambda _i: self._open(self.t_buys))
        self.t_sales.doubleClicked.connect(lambda _i: self._open(self.t_sales))
        self.lay.addStretch(1)

    def _open(self, table: Table) -> None:
        tid = table.selected_data()
        if tid:
            self.ctx.main.show_detail(tid)

    def refresh(self) -> None:
        d = self.svc.dashboard(self.period.current)
        bal = d["balance"]
        self.c_balance.set(fmt_gb(bal), "Negatifse başlangıç GB'nizi veya GB Ekle'yi kontrol edin" if bal < 0 else "",
                           theme.RED if bal < 0 else theme.ACCENT)
        self.c_stock.set(str(d["stock_units"]), f"{d['stock_kinds']} farklı item")
        self.c_listed.set(str(d["listed_units"]))
        self.c_cost.set(fmt_gb(d["stock_cost"]), "Henüz satılmadı — kâr değildir")
        self.period_lbl.setText(f"Dönem: {PERIODS[self.period.current]}")
        net = d["net_profit"]
        self.c_net.set(fmt_gb(net, signed=True), "Kâr − zarar",
                       theme.GREEN if net > 0 else theme.RED if net < 0 else None)
        self.c_profit.set(fmt_gb(d["profit"]), "Kârlı işlemlerin toplamı", theme.GREEN if d["profit"] else None)
        self.c_loss.set(fmt_gb(d["loss"]), "Zararlı işlemlerin toplamı", theme.RED if d["loss"] else None)
        self.c_buy.set(fmt_gb(d["purchase_total"]), f"{d['purchase_count']} alış")
        self.c_sell.set(fmt_gb(d["sales_gross"]), f"Vergi: {fmt_gb(d['tax_total'])} · Net: {fmt_gb(d['sales_net'])}")
        self.c_count.set(str(d["sale_count"]), f"{d['sold_units']} adet item")
        self.t_buys.set_rows(
            [[date_cell(t["date"]), t["items"], Cell(t["qty"], align="r"), money_cell(t["amount"])]
             for t in d["recent_purchases"]], [t["id"] for t in d["recent_purchases"]])
        self.t_sales.set_rows(
            [[date_cell(t["date"]), t["items"], Cell(t["qty"], align="r"), money_cell(t["amount"]),
              money_cell(t["realized"], signed=True, color=True)] for t in d["recent_sales"]],
            [t["id"] for t in d["recent_sales"]])

