from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

from ...core.errors import UserError
from ...core.money import fmt_gb
from ...core.service import MAX_QTY, display_name, split_name_upgrade
from .. import theme
from ..widgets import (
    Cell, DateInput, ItemNameInput, MoneyInput, Table, UpgradeCombo, confirm, date_cell, money_cell, muted, page_title, section,
    warn,
)
from .base import Page


def resolve_item_name(parent, svc, name: str) -> str | None:
    """Mükerrer kaydı önler: benzer isim varsa kullanıcıya sorar. None = vazgeçildi."""
    existing = svc.existing_name(name)
    if existing:
        return existing
    similar = svc.similar_names(name)
    if not similar:
        return name
    box = QMessageBox(parent)
    box.setWindowTitle("Benzer item bulundu")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(f"'{name}' kayıtlı değil, ancak benzer bir item var:\n\n" + "\n".join(f"• {s}" for s in similar)
                + "\n\nKayıtlı olanı kullanmak ister misiniz?")
    use = box.addButton(f"'{similar[0]}' kullan", QMessageBox.ButtonRole.AcceptRole)
    new = box.addButton("Yeni item olarak kaydet", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Vazgeç", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(use)
    box.exec()
    clicked = box.clickedButton()
    if clicked is use:
        return similar[0]
    if clicked is new:
        return name
    return None


class BuyPage(Page):
    title = "Item Al"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.lay.addWidget(page_title("Item Al", "Yeni alış kaydı. Item adı ve upgrade seviyesi birlikte ürünü belirler."))
        row = QHBoxLayout()
        row.setSpacing(16)

        box = QGroupBox("Alış bilgileri")
        form = QFormLayout(box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)
        self.name = ItemNameInput()
        self.name.textChanged.connect(self._name_hint)
        self.name.editingFinished.connect(self._split_upgrade)
        self.hint = muted("")
        nw = QWidget()
        nl = QVBoxLayout(nw)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(2)
        nl.addWidget(self.name)
        nl.addWidget(self.hint)
        form.addRow("Item adı", nw)
        self.upgrade = UpgradeCombo()
        self.upgrade.valueChanged.connect(self._name_hint)
        form.addRow("Upgrade seviyesi", self.upgrade)
        self.qty = QSpinBox()
        self.qty.setRange(1, MAX_QTY)
        self.qty.valueChanged.connect(self._update_total)
        form.addRow("Adet", self.qty)
        self.price = MoneyInput("Birim alış fiyatı")
        self.price.changed.connect(self._update_total)
        self.price.gb.returnPressed.connect(self.save)
        self.price.m.returnPressed.connect(self.save)
        form.addRow("Birim alış fiyatı", self.price)
        self.total = QLabel("—")
        self.total.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 600;")
        form.addRow("Toplam tutar", self.total)
        self.date = DateInput()
        form.addRow("Alış tarihi", self.date)
        self.note = QLineEdit()
        self.note.setPlaceholderText("İsteğe bağlı (örn. Acil satan oyuncudan alındı.)")
        self.note.setMaxLength(500)
        self.note.returnPressed.connect(self.save)
        form.addRow("Açıklama", self.note)
        self.balance_lbl = muted("")
        form.addRow("", self.balance_lbl)
        btns = QHBoxLayout()
        self.save_btn = QPushButton("Alışı Kaydet")
        self.save_btn.setObjectName("Primary")
        self.save_btn.clicked.connect(self.save)
        clear = QPushButton("Temizle")
        clear.clicked.connect(self.clear)
        btns.addWidget(self.save_btn)
        btns.addWidget(clear)
        btns.addStretch(1)
        form.addRow(btns)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {theme.GREEN};")
        self.status.setWordWrap(True)
        form.addRow(self.status)
        box.setMinimumWidth(430)
        box.setMaximumWidth(560)
        row.addWidget(box, 0)

        right = QVBoxLayout()
        right.addWidget(section("Son alışlar"))
        self.recent = Table(["#", "Tarih", "Item", "Adet", "Birim", "Toplam", "Not"], stretch=2)
        self.recent.doubleClicked.connect(lambda _i: self._open())
        right.addWidget(self.recent)
        right.addWidget(muted("Ayrıntı veya düzenleme için satıra çift tıklayın."))
        row.addLayout(right, 1)
        self.lay.addLayout(row, 1)

    # ------------------------------------------------------------------ #
    def _split_upgrade(self) -> None:
        name, up = split_name_upgrade(self.name.text())
        if up is not None:
            self.name.blockSignals(True)
            self.name.setText(name)
            self.name.blockSignals(False)
            self.upgrade.setValue(up)
            self._name_hint()

    def _name_hint(self) -> None:
        raw = self.name.text().strip()
        if not raw:
            self.hint.setText("")
            return
        name, up = split_name_upgrade(raw)
        up = self.upgrade.value() if up is None else up
        existing = self.svc.existing_name(name)
        if existing:
            disp = display_name(existing, up)
            stock = next((p for p in self.svc.products_in_stock() if p["display"] == disp), None)
            self.hint.setText(f"Kayıtlı item: {disp}" + (f" · stokta {stock['remaining']} adet" if stock else ""))
        else:
            sim = self.svc.similar_names(name)
            self.hint.setText("Yeni item olarak kaydedilecek" + (f" · benzer: {', '.join(sim)}" if sim else ""))

    def _update_total(self) -> None:
        v = self.price.value_or_none()
        if v is None or self.price.is_empty():
            self.total.setText("—")
        else:
            self.total.setText(fmt_gb(v * self.qty.value()))

    def _open(self) -> None:
        tid = self.recent.selected_data()
        if tid:
            self.ctx.main.show_detail(tid)

    def clear(self) -> None:
        self.name.clear()
        self.upgrade.setValue(0)
        self.qty.setValue(1)
        self.price.clear()
        self.note.clear()
        self.status.setText("")
        self.name.setFocus()

    def prefill(self, product_id: int | None = None) -> None:
        if product_id:
            p = self.svc.product(product_id)
            self.name.setText(p["name"])
            self.upgrade.setValue(p["upgrade"])
            self.price.setFocus()

    def save(self) -> None:
        self._split_upgrade()
        try:
            raw = self.name.text().strip()
            if not raw:
                raise UserError("Item adı boş bırakılamaz.")
            unit = self.price.value()
            name = resolve_item_name(self, self.svc, raw)
            if name is None:
                return
            qty = self.qty.value()
            total = unit * qty
            bal = self.svc.balance()
            if total > bal and not confirm(
                    self, f"Kullanılabilir GB ({fmt_gb(bal)}) bu alış için yetersiz ({fmt_gb(total)}).\n\n"
                          f"Program dışında GB kazandıysanız önce 'GB Ekle' ile ekleyebilirsiniz.\n"
                          f"Yine de kaydedilsin mi?", "Bakiye yetersiz"):
                return
            self.svc.record_purchase(name, self.upgrade.value(), qty, unit, self.date.iso(), self.note.text())
        except UserError as e:
            warn(self, str(e))
            return
        disp = display_name(name, self.upgrade.value())
        self.qty.setValue(1)
        self.price.clear()
        self.note.clear()
        self.changed()
        self.status.setText(f"✓ Kaydedildi: {disp} ×{qty} — {fmt_gb(total)}")
        self.name.setFocus()
        self.name.selectAll()

    def refresh(self) -> None:
        self.name.set_suggestions(self.svc.completion_list())
        self.balance_lbl.setText(f"Kullanılabilir: {fmt_gb(self.svc.balance())}")
        rows, data = [], []
        for t in self.svc.list_transactions(types=["purchase"], limit=60):
            d = self.svc.transaction_detail(t["id"])
            lot = d["lots"][0] if d["lots"] else None
            rows.append([Cell(f"#{t['id']}", t["id"], "r"), date_cell(t["date"]), t["items"],
                         Cell(t["qty"], t["qty"], "r"), money_cell(lot["unit_price"] if lot else None),
                         money_cell(t["amount"]), t["note"]])
            data.append(t["id"])
        self.recent.set_rows(rows, data)
        self._name_hint()
