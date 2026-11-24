"""Diyalog pencereleri: GB hareketi, işlem detayı, düzenleme, ilk kurulum."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
)

from ..core.errors import UserError
from ..core.money import fmt_gb, fmt_rate, parse_tax_rate
from ..core.service import MAX_QTY, METHOD_NAMES, fmt_date, split_name_upgrade
from . import theme
from .pages.buy import resolve_item_name
from .pages.sell import MethodChooser
from .widgets import (
    Cell, DateInput, ItemNameInput, MoneyInput, Table, UpgradeCombo, confirm, date_cell, fmt_pl, money_cell, muted, num_cell,
    pl_color, section, warn,
)


def _buttons(dlg: QDialog, ok_text: str = "Kaydet") -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
    bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


class _FormDialog(QDialog):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.form = QFormLayout(self)
        self.form.setVerticalSpacing(10)

    def accept(self) -> None:
        try:
            if self.apply() is False:  # kullanıcı vazgeçti; pencere açık kalır
                return
        except UserError as e:
            warn(self, str(e))
            return
        super().accept()

    def apply(self) -> bool | None:  # alt sınıflar uygular
        raise NotImplementedError


# --------------------------------------------------------------------------- #
class CashDialog(_FormDialog):
    """GB Ekle / GB Çıkar (yeni kayıt veya düzenleme)."""

    def __init__(self, parent, svc, kind: str, tx_id: int | None = None):
        title = ("GB Ekle" if kind == "deposit" else "GB Çıkar") + (" — düzenle" if tx_id else "")
        super().__init__(parent, title)
        self.svc, self.kind, self.tx_id = svc, kind, tx_id
        self.form.addRow(muted("Program dışındaki Noah değişikliklerini düzeltmek içindir "
                               "(örn. görev ödülü, başka karaktere aktarım). Ticaret kârı sayılmaz."))
        self.amount = MoneyInput("Miktar")
        self.form.addRow("Miktar", self.amount)
        self.date = DateInput()
        self.form.addRow("Tarih", self.date)
        self.note = QLineEdit()
        self.note.setMaxLength(500)
        self.note.setPlaceholderText("İsteğe bağlı açıklama")
        self.form.addRow("Açıklama", self.note)
        self.form.addRow(muted(f"Şu anki kullanılabilir GB: {fmt_gb(svc.balance())}"))
        if tx_id:
            d = svc.transaction_detail(tx_id)
            t = d["tx"]
            self.amount.set_value(t["cash_in"] or t["cash_out"])
            self.date.set_iso(t["tx_date"])
            self.note.setText(d["summary"]["note"])
        self.form.addRow(_buttons(self))
        self.amount.setFocus()

    def apply(self):
        amount = self.amount.value()
        if self.tx_id:
            self.svc.update_cash(self.tx_id, amount, self.date.iso(), self.note.text())
            return
        if self.kind == "withdraw" and amount > self.svc.balance():
            if not confirm(self, "Çıkarılacak miktar kullanılabilir GB'den fazla. Bakiye eksiye düşecek.\n"
                                 "Yine de kaydedilsin mi?", "Bakiye yetersiz"):
                return False
        self.svc.record_cash(self.kind, amount, self.date.iso(), self.note.text())


# --------------------------------------------------------------------------- #
class EditPurchaseDialog(_FormDialog):
    def __init__(self, parent, svc, tx_id: int):
        super().__init__(parent, f"Alışı düzenle — #{tx_id}")
        self.svc, self.tx_id = svc, tx_id
        d = svc.transaction_detail(tx_id)
        lot = d["lots"][0]
        used = lot["qty"] - lot["remaining"]
        self.name = ItemNameInput()
        self.name.set_suggestions(svc.completion_list())
        self.name.setText(lot["name"])
        self.form.addRow("Item adı", self.name)
        self.upgrade = UpgradeCombo()
        self.upgrade.setValue(lot["upgrade"])
        self.form.addRow("Upgrade", self.upgrade)
        self.qty = QSpinBox()
        self.qty.setRange(max(1, used), MAX_QTY)
        self.qty.setValue(lot["qty"])
        self.form.addRow("Adet", self.qty)
        self.price = MoneyInput("Birim alış fiyatı")
        self.price.set_value(lot["unit_price"])
        self.form.addRow("Birim alış fiyatı", self.price)
        self.date = DateInput()
        self.date.set_iso(d["tx"]["tx_date"])
        self.form.addRow("Alış tarihi", self.date)
        self.note = QLineEdit(d["summary"]["note"])
        self.note.setMaxLength(500)
        self.form.addRow("Açıklama", self.note)
        if used:
            self.form.addRow(muted(f"Bu partiden {used} adet satılmış/takas edilmiş. Adet bundan az olamaz; "
                                   f"item adı/upgrade değiştirilemez. Fiyat değişirse bağlı satışların kârı ve "
                                   f"takasla gelen itemlerin maliyeti otomatik güncellenir."))
            self.name.setEnabled(False)
            self.upgrade.setEnabled(False)
        self.form.addRow(_buttons(self))

    def apply(self):
        name, up = split_name_upgrade(self.name.text())
        up = self.upgrade.value() if up is None else up
        if self.name.isEnabled():
            resolved = resolve_item_name(self, self.svc, name)
            if resolved is None:
                return False
            name = resolved
        self.svc.update_purchase(self.tx_id, name, up, self.qty.value(), self.price.value(), self.date.iso(),
                                 self.note.text())


class EditSaleDialog(_FormDialog):
    def __init__(self, parent, svc, tx_id: int):
        super().__init__(parent, f"Satışı düzenle — #{tx_id}")
        self.svc, self.tx_id = svc, tx_id
        d = svc.transaction_detail(tx_id)
        t = d["tx"]
        self.form.addRow(QLabel(f"<b>{d['summary']['items']}</b>"))
        self.form.addRow(muted("Satılan adet veya parti değiştirilecekse satışı silip yeniden girin."))
        self.gross = MoneyInput("Toplam satış fiyatı")
        self.gross.set_value(t["gross_amount"])
        self.form.addRow("Toplam satış fiyatı", self.gross)
        self.method = MethodChooser()
        self.method.set_value(t["sale_method"])
        self.form.addRow("Satış yöntemi", self.method)
        self.rate = QLineEdit(fmt_rate(t["tax_bps"] if t["sale_method"] == "market" else svc.tax_bps).lstrip("%"))
        self.rate.setMaximumWidth(100)
        self.form.addRow("Bu satışın vergi oranı (%)", self.rate)
        self.method.toggled.connect(lambda on: self.rate.setEnabled(on))
        self.rate.setEnabled(t["sale_method"] == "market")
        self.date = DateInput()
        self.date.set_iso(t["tx_date"])
        self.form.addRow("Satış tarihi", self.date)
        self.note = QLineEdit(d["summary"]["note"])
        self.note.setMaxLength(500)
        self.form.addRow("İşlem notu", self.note)
        self.form.addRow(_buttons(self))

    def apply(self) -> None:
        method = self.method.value()
        bps = parse_tax_rate(self.rate.text()) if method == "market" else 0
        self.svc.update_sale(self.tx_id, self.gross.value(), method, bps, self.date.iso(), self.note.text())


class EditTradeDialog(_FormDialog):
    def __init__(self, parent, svc, tx_id: int):
        super().__init__(parent, f"Takası düzenle — #{tx_id}")
        self.svc, self.tx_id = svc, tx_id
        d = svc.transaction_detail(tx_id)
        self.form.addRow(muted("Takasın içeriği değiştirilecekse takası silip yeniden girin. "
                               "Burada tarih ve not düzenlenebilir."))
        self.date = DateInput()
        self.date.set_iso(d["tx"]["tx_date"])
        self.form.addRow("Takas tarihi", self.date)
        self.note = QLineEdit(d["summary"]["note"])
        self.note.setMaxLength(500)
        self.form.addRow("Not", self.note)
        self.form.addRow(_buttons(self))

    def apply(self) -> None:
        self.svc.update_trade(self.tx_id, self.date.iso(), self.note.text())


# --------------------------------------------------------------------------- #
class DetailDialog(QDialog):
    def __init__(self, parent, svc, tx_id: int):
        super().__init__(parent)
        d = svc.transaction_detail(tx_id)
        t, s = d["tx"], d["summary"]
        self.setWindowTitle(f"İşlem #{tx_id} — {s['type_name']}")
        self.setMinimumSize(640, 420)
        lay = QVBoxLayout(self)
        g = QGridLayout()
        g.setHorizontalSpacing(18)
        rows: list[tuple[str, str, str | None]] = [
            ("İşlem türü", s["type_name"], None), ("Tarih", fmt_date(t["tx_date"]), None),
            ("Kayıt zamanı", t["created_at"].replace("T", " "), None),
        ]
        typ = t["type"]
        if typ == "purchase":
            rows.append(("Toplam alış tutarı", fmt_gb(t["cost_basis"]), None))
        elif typ == "sale":
            rows += [("Satış yöntemi", METHOD_NAMES.get(t["sale_method"], ""), None),
                     ("Brüt satış", fmt_gb(t["gross_amount"]), None),
                     ("Uygulanan vergi oranı", fmt_rate(t["tax_bps"]) if t["sale_method"] == "market" else "Vergisiz",
                      None),
                     ("Vergi tutarı", fmt_gb(t["tax_amount"]), None),
                     ("Net satış", fmt_gb(t["net_cash"]), None),
                     ("Satılan itemlerin gerçek maliyeti", fmt_gb(t["cost_basis"]), None),
                     ("Net kâr / zarar", fmt_pl(t["realized_pl"]), pl_color(t["realized_pl"]))]
        elif typ == "trade":
            rows += [("Verilen itemlerin maliyeti", fmt_gb(t["cost_basis"]), None),
                     ("Verilen GB", fmt_gb(t["cash_out"]), None), ("Alınan GB", fmt_gb(t["cash_in"]), None),
                     ("Gerçekleşen kâr / zarar", fmt_pl(t["realized_pl"]), pl_color(t["realized_pl"]))]
        else:
            rows.append(("Miktar", fmt_gb(t["cash_in"] or t["cash_out"]), None))
        rows.append(("Kullanılabilir GB etkisi", fmt_gb(t["net_cash"], signed=True), pl_color(t["net_cash"])))
        if s["note"]:
            rows.append(("Not", s["note"], None))
        for i, (k, v, c) in enumerate(rows):
            g.addWidget(muted(k), i, 0)
            lbl = QLabel(v)
            lbl.setWordWrap(True)
            if c:
                lbl.setStyleSheet(f"color: {c}; font-weight: 600;")
            g.addWidget(lbl, i, 1)
        lay.addLayout(g)

        if d["lots"]:
            lay.addWidget(section("Gelen itemler (alış partileri)" if typ == "purchase" else "Alınan itemler"))
            tb = Table(["Parti", "Item", "Adet", "Kalan", "Birim maliyet", "Toplam maliyet"]
                       + (["Anlaşılan birim değer"] if typ == "trade" else []), stretch=1, sortable=False)
            tb.set_rows([[Cell(f"#{l['id']}", align="r"), l["display"], num_cell(l["qty"]), num_cell(l["remaining"]),
                          money_cell(l["unit_cost"]), money_cell(l["total_cost"])]
                         + ([money_cell(l["agreed_value"])] if typ == "trade" else []) for l in d["lots"]])
            tb.setMaximumHeight(160)
            lay.addWidget(tb)
        if d["consumptions"]:
            lay.addWidget(section("Kullanılan partiler (satılan / verilen itemler)"))
            tb = Table(["Parti", "Item", "Parti tarihi", "Adet", "Maliyet", "Elde tutma"], stretch=1, sortable=False)
            tb.set_rows([[Cell(f"#{c['lot_id']}", align="r"), c["display"], date_cell(c["lot_date"]),
                          num_cell(c["qty"]), money_cell(c["cost"]), Cell(f"{c['days']} gün", align="r")]
                         for c in d["consumptions"]])
            tb.setMaximumHeight(160)
            lay.addWidget(tb)
        if d["dependents"]:
            w = muted("Bu işlemle gelen itemler şu işlemlerde kullanılmış: "
                      + ", ".join(f"#{x}" for x in d["dependents"])
                      + ". Bu nedenle silinemez; önce o işlemler silinmelidir.")
            w.setStyleSheet(f"color: {theme.ACCENT};")
            lay.addWidget(w)
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.button(QDialogButtonBox.StandardButton.Close).setText("Kapat")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


# --------------------------------------------------------------------------- #
class InitialSetupDialog(_FormDialog):
    def __init__(self, parent, svc):
        super().__init__(parent, "Hoş geldiniz")
        self.svc = svc
        self.form.addRow(QLabel("<b>KO Ticaret Takip</b>'e hoş geldiniz."))
        self.form.addRow(muted("Başlamak için şu an elinizde bulunan kullanılabilir GB miktarını girin. "
                               "Bu değer Ayarlar'dan sonradan değiştirilebilir. Bilmiyorsanız boş bırakın (0)."))
        self.amount = MoneyInput("Başlangıç GB", allow_empty=True)
        self.form.addRow("Başlangıç GB", self.amount)
        self.form.addRow(_buttons(self, "Başla"))

    def apply(self) -> None:
        self.svc.set_initial_balance(self.amount.value())
        self.svc.mark_initialized()

