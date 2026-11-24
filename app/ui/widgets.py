"""Ortak arayüz parçaları."""
from __future__ import annotations

import math
import weakref
from datetime import date

from PySide6.QtCore import QDate, QPointF, QRectF, QStringListModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QCompleter, QDateEdit, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QToolButton,
    QToolTip, QVBoxLayout, QWidget,
)

from ..core.errors import MoneyError, UserError
from ..core import upgrades
from ..core.money import fmt_gb, gb_number, m_number, parse_gb, parse_gb_m, parse_m, split_gb_m
from . import theme

ALIGN_L = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
ALIGN_R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
ALIGN_C = Qt.AlignmentFlag.AlignCenter
NONE_KEY = -(10 ** 30)


# --------------------------------------------------------------------------- #
# Mesajlar
# --------------------------------------------------------------------------- #
def warn(parent, text: str, title: str = "Uyarı") -> None:
    QMessageBox.warning(parent, title, text)


def info(parent, text: str, title: str = "Bilgi") -> None:
    QMessageBox.information(parent, title, text)


def confirm(parent, text: str, title: str = "Onay", danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    yes = box.addButton("Evet", QMessageBox.ButtonRole.YesRole)
    no = box.addButton("Vazgeç", QMessageBox.ButtonRole.NoRole)
    box.setDefaultButton(no if danger else yes)
    box.exec()
    return box.clickedButton() is yes


def safe(parent, fn, *args, **kwargs):
    """Kullanıcı hatalarını anlaşılır mesajla gösterir. Başarılıysa sonucu, değilse None döner."""
    try:
        return fn(*args, **kwargs)
    except UserError as e:
        warn(parent, str(e))
        return None


# --------------------------------------------------------------------------- #
# Biçimlendirme yardımcıları
# --------------------------------------------------------------------------- #
def pl_color(v) -> str | None:
    if v is None:
        return None
    return theme.GREEN if v > 0 else theme.RED if v < 0 else None


def fmt_pl(v) -> str:
    return "—" if v is None else fmt_gb(v, signed=True)


def fmt_days(d) -> str:
    return "—" if d is None else f"{d} gün"


# --------------------------------------------------------------------------- #
# Para girişi
# --------------------------------------------------------------------------- #
class MoneyInput(QWidget):
    """Üç yöntemle para girişi:
        "m"   : yalnızca M  (105  -> 105 M = 1,05 GB)
        "gb"  : ondalıklı GB (12,5)
        "gbm" : ayrı GB + M alanları (12 / 50)
    """

    changed = Signal()
    _instances: "weakref.WeakSet[MoneyInput]" = weakref.WeakSet()
    default_mode = "m"
    MODES = ("m", "gb", "gbm")

    def __init__(self, field: str = "Tutar", allow_empty: bool = False, parent=None):
        super().__init__(parent)
        self.field = field
        self.allow_empty = allow_empty
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.gb = QLineEdit()
        self.gb.setMinimumWidth(80)
        self.gb_lbl = QLabel("GB")
        self.m = QLineEdit()
        self.m.setPlaceholderText("0")
        self.m.setMinimumWidth(60)
        self.m_lbl = QLabel("M")
        self.toggle = QToolButton()
        self.toggle.setObjectName("Mini")
        self.toggle.setText("⇄")
        self.toggle.setToolTip("Giriş yöntemini değiştir: M  →  ondalıklı GB  →  GB + M")
        self.conv = QLabel("")
        self.conv.setObjectName("Muted")
        self.toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for w in (self.gb, self.gb_lbl, self.m, self.m_lbl, self.conv, self.toggle):
            lay.addWidget(w)
        self.gb.textChanged.connect(self._on_change)
        self.m.textChanged.connect(self._on_change)
        self.toggle.clicked.connect(self._toggle)
        self.mode = "m"
        self.set_mode(MoneyInput.default_mode)
        MoneyInput._instances.add(self)

    @classmethod
    def apply_default_mode(cls, mode: str) -> None:
        cls.default_mode = mode
        for inst in list(cls._instances):
            try:
                if inst.is_empty():
                    inst.set_mode(mode)
            except RuntimeError:  # silinmiş widget
                pass

    def set_mode(self, mode: str) -> None:
        val = self.value_or_none() if not self.is_empty() else None
        if mode not in self.MODES:
            mode = "m"
        self.mode = mode
        two = mode == "gbm"
        self.m.setVisible(two)
        self.m_lbl.setVisible(two)
        self.gb_lbl.setText("M" if mode == "m" else "GB")
        self.gb.setPlaceholderText({"m": "örn. 105", "gb": "örn. 12,5", "gbm": "GB"}[mode])
        self.conv.setVisible(mode == "m")
        if val is not None:
            self.set_value(val)

    def _toggle(self) -> None:
        i = self.MODES.index(self.mode)
        self.set_mode(self.MODES[(i + 1) % len(self.MODES)])

    def is_empty(self) -> bool:
        return not self.gb.text().strip() and (self.mode == "gb" or not self.m.text().strip())

    def value(self) -> int:
        if self.is_empty():
            if self.allow_empty:
                return 0
            raise MoneyError(f"{self.field} boş bırakılamaz.")
        if self.mode == "m":
            return parse_m(self.gb.text(), self.field)
        if self.mode == "gb":
            return parse_gb(self.gb.text(), self.field)
        return parse_gb_m(self.gb.text(), self.m.text(), self.field)

    def value_or_none(self) -> int | None:
        try:
            return self.value()
        except MoneyError:
            return None

    def set_value(self, noah: int | None) -> None:
        self.gb.blockSignals(True)
        self.m.blockSignals(True)
        if noah is None:
            self.gb.clear()
            self.m.clear()
        elif self.mode == "m":
            self.gb.setText(m_number(noah))
            self.m.clear()
        elif self.mode == "gb":
            self.gb.setText(gb_number(noah).replace(".", ""))
            self.m.clear()
        else:
            g, m = split_gb_m(noah)
            self.gb.setText(g)
            self.m.setText(m)
        self.gb.blockSignals(False)
        self.m.blockSignals(False)
        self._on_change()

    def clear(self) -> None:
        self.set_value(None)

    def _mark(self, w: QLineEdit, bad: bool) -> None:
        if w.property("invalid") != bad:
            w.setProperty("invalid", bad)
            w.style().unpolish(w)
            w.style().polish(w)

    def _on_change(self) -> None:
        bad = not self.is_empty() and self.value_or_none() is None
        self._mark(self.gb, bad)
        self._mark(self.m, bad)
        if bad:
            try:
                self.value()
            except MoneyError as e:
                self.setToolTip(str(e))
        else:
            v = self.value_or_none()
            self.setToolTip(fmt_gb(v) if v is not None else "")
        v = None if bad or self.is_empty() else self.value_or_none()
        # M modunda yazılan tutarın GB karşılığı yanında gösterilir: 105 M -> "= 1,05 GB"
        self.conv.setText(f"= {fmt_gb(v)}" if v is not None else "")
        self.changed.emit()

    def setFocus(self) -> None:  # noqa: N802 (Qt adlandırması)
        self.gb.setFocus()


# --------------------------------------------------------------------------- #
# Upgrade seçimi (açılır liste)
# --------------------------------------------------------------------------- #
class UpgradeCombo(QComboBox):
    """Yok, +1 … +10, Reb1 … Reb21. QSpinBox ile aynı arayüz: value() / setValue() / valueChanged."""

    valueChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        for u in upgrades.LEVELS:
            self.addItem(upgrades.combo_label(u), u)
        self.setMaxVisibleItems(16)
        self.setMinimumWidth(110)
        self.currentIndexChanged.connect(lambda _i: self.valueChanged.emit(self.value()))

    def value(self) -> int:
        v = self.currentData()
        return int(v) if v is not None else 0

    def setValue(self, u: int) -> None:  # noqa: N802
        u = int(u or 0)
        i = self.findData(u)
        if i < 0:  # eski sürümde girilmiş, listede olmayan seviye
            self.addItem(upgrades.combo_label(u), u)
            i = self.count() - 1
        self.setCurrentIndex(i)


# --------------------------------------------------------------------------- #
# Tarih girişi
# --------------------------------------------------------------------------- #
class DateInput(QDateEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("dd.MM.yyyy")
        self.setDate(QDate.currentDate())
        self.setMinimumWidth(120)

    def iso(self) -> str:
        return self.date().toString("yyyy-MM-dd")

    def set_iso(self, iso: str) -> None:
        self.setDate(QDate.fromString(iso[:10], "yyyy-MM-dd"))

    def py_date(self) -> date:
        return date.fromisoformat(self.iso())


# --------------------------------------------------------------------------- #
# Item adı girişi + otomatik tamamlama
# --------------------------------------------------------------------------- #
class ItemNameInput(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Item adı yazın… (örn. Shard)")
        self._model = QStringListModel(self)
        comp = QCompleter(self._model, self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        comp.setMaxVisibleItems(12)
        self.setCompleter(comp)

    def set_suggestions(self, names: list[str]) -> None:
        self._model.setStringList(names)


# --------------------------------------------------------------------------- #
# Tablo
# --------------------------------------------------------------------------- #
class SortItem(QTableWidgetItem):
    def __init__(self, text: str, key=None):
        super().__init__(text)
        self._key = key if key is not None else text.lower()

    def __lt__(self, other):  # noqa: D401
        k2 = getattr(other, "_key", other.text().lower())
        try:
            return self._key < k2
        except TypeError:
            return str(self._key) < str(k2)


class Cell:
    __slots__ = ("text", "key", "align", "color", "bold")

    def __init__(self, text, key=None, align="l", color=None, bold=False):
        self.text = "" if text is None else str(text)
        self.key = key
        self.align = align
        self.color = color
        self.bold = bold


def money_cell(noah, signed: bool = False, color: bool = False) -> Cell:
    if noah is None:
        return Cell("—", NONE_KEY, "r")
    return Cell(fmt_gb(noah, signed=signed), noah, "r", pl_color(noah) if color else None)


def num_cell(n, suffix: str = "") -> Cell:
    if n is None:
        return Cell("—", NONE_KEY, "r")
    return Cell(f"{n}{suffix}", n, "r")


def date_cell(iso: str | None) -> Cell:
    from ..core.service import fmt_date
    return Cell(fmt_date(iso), iso or "", "c")


class Table(QTableWidget):
    def __init__(self, headers: list[str], stretch: int | None = None, sortable: bool = True, parent=None):
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(30)
        self.setWordWrap(False)
        self._sortable = sortable
        h = self.horizontalHeader()
        # Başlangıçta hiçbir sütuna göre sıralama yapılmaz (veri, servisin verdiği sırada gösterilir).
        h.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(sortable)
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h.setHighlightSections(False)
        if stretch is not None:
            h.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
        else:
            h.setStretchLastSection(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def set_rows(self, rows: list[list], row_data: list | None = None) -> None:
        self.setSortingEnabled(False)
        self.clearContents()
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                if not isinstance(cell, Cell):
                    cell = Cell(cell)
                it = SortItem(cell.text, cell.key)
                it.setTextAlignment(ALIGN_R if cell.align == "r" else ALIGN_C if cell.align == "c" else ALIGN_L)
                if cell.color:
                    it.setForeground(QColor(cell.color))
                if cell.bold:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if c == 0 and row_data is not None:
                    it.setData(Qt.ItemDataRole.UserRole, row_data[r])
                self.setItem(r, c, it)
        self.setSortingEnabled(self._sortable)

    def reset_sort(self) -> None:
        """Kullanıcının başlığa tıklayarak seçtiği sıralamayı kaldırır."""
        self.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    def selected_data(self):
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None
        it = self.item(rows[0].row(), 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def row_data(self, row: int):
        it = self.item(row, 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None


# --------------------------------------------------------------------------- #
# Kart / başlık / dönem seçici
# --------------------------------------------------------------------------- #
class Card(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.t = QLabel(title)
        self.t.setObjectName("CardTitle")
        self.v = QLabel("—")
        self.v.setObjectName("CardValue")
        self.v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.s = QLabel("")
        self.s.setObjectName("CardSub")
        lay.addWidget(self.t)
        lay.addWidget(self.v)
        lay.addWidget(self.s)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(170)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.v.setText(value)
        self.v.setStyleSheet(f"color: {color};" if color else "")
        self.s.setText(sub)


def page_title(text: str, sub: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 6)
    lay.setSpacing(0)
    t = QLabel(text)
    t.setObjectName("PageTitle")
    lay.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setObjectName("Muted")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


def section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Section")
    return lbl


def muted(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(True)
    return lbl


class PeriodSelector(QWidget):
    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        from ..core.service import PERIODS
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for key, text in PERIODS.items():
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("seg", True)
            b.clicked.connect(lambda _=False, k=key: self._select(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        self.current = "all"
        self.buttons["all"].setChecked(True)

    def _select(self, key: str) -> None:
        self.current = key
        self.changed.emit(key)


# --------------------------------------------------------------------------- #
# Basit grafikler (QPainter; ek kütüphane gerektirmez)
# --------------------------------------------------------------------------- #
class BarChart(QWidget):
    """Pozitif değerler yeşil, negatifler kırmızı çubuk."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: list[tuple[str, int]] = []
        self.setMinimumHeight(200)
        self.setMouseTracking(True)
        self._bars: list[tuple[QRectF, str]] = []

    def set_data(self, data: list[tuple[str, int]]) -> None:
        self.data = data
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.PANEL))
        area = QRectF(self.rect()).adjusted(70, 14, -14, -30)
        self._bars = []
        small = QFont(self.font())
        small.setPointSizeF(8)
        p.setFont(small)
        if not self.data or all(v == 0 for _, v in self.data):
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), int(ALIGN_C), "Bu dönemde gerçekleşen kâr/zarar yok")
            p.end()
            return
        vals = [v for _, v in self.data]
        top, bot = max(0, max(vals)), max(0, -min(vals))
        span = (top + bot) or 1
        zero_y = area.top() + area.height() * top / span
        # eksen
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawLine(QPointF(area.left(), zero_y), QPointF(area.right(), zero_y))
        p.setPen(QColor(theme.MUTED))
        lab_rect_w = 64
        p.drawText(QRectF(0, area.top() - 7, lab_rect_w, 14), int(ALIGN_R), gb_number(top, 2) if top else "")
        p.drawText(QRectF(0, zero_y - 7, lab_rect_w, 14), int(ALIGN_R), "0 GB")
        if bot:
            p.drawText(QRectF(0, area.bottom() - 7, lab_rect_w, 14), int(ALIGN_R), "-" + gb_number(bot, 2))
        n = len(self.data)
        step = area.width() / n
        bw = max(2.0, min(40.0, step * 0.65))
        every = max(1, math.ceil(n * 46 / max(1.0, area.width())))
        for i, (label, v) in enumerate(self.data):
            x = area.left() + i * step + (step - bw) / 2
            h = area.height() * abs(v) / span
            rect = QRectF(x, zero_y - h, bw, h) if v >= 0 else QRectF(x, zero_y, bw, h)
            if v:
                p.fillRect(rect, QColor(theme.GREEN if v > 0 else theme.RED))
            hit = QRectF(area.left() + i * step, area.top(), step, area.height())
            self._bars.append((hit, f"{label}: {fmt_gb(v, signed=True)}"))
            if i % every == 0:
                p.setPen(QColor(theme.MUTED))
                p.drawText(QRectF(area.left() + i * step - 10, area.bottom() + 6, step + 20, 16),
                           int(ALIGN_C), label)
        p.end()

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position()
        for rect, text in self._bars:
            if rect.contains(pos):
                QToolTip.showText(event.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()


class PriceChart(QWidget):
    """Alış (altın) ve satış (yeşil) birim fiyatlarını tarihe göre gösterir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buys: list[tuple[str, int]] = []
        self.sells: list[tuple[str, int]] = []
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        self._pts: list[tuple[QPointF, str]] = []

    def set_data(self, buys, sells) -> None:
        self.buys, self.sells = list(buys), list(sells)
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        from ..core.service import fmt_date
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.PANEL))
        small = QFont(self.font())
        small.setPointSizeF(8)
        p.setFont(small)
        allp = self.buys + self.sells
        self._pts = []
        if not allp:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), int(ALIGN_C), "Fiyat geçmişi yok")
            p.end()
            return
        area = QRectF(self.rect()).adjusted(70, 26, -16, -26)
        xs = [date.fromisoformat(d).toordinal() for d, _ in allp]
        x0, x1 = min(xs), max(xs)
        vmax = max(v for _, v in allp) or 1
        vmin = min(v for _, v in allp)
        lo = 0 if vmin < vmax * 0.5 else vmin * 0.9
        span_v = (vmax * 1.05 - lo) or 1

        def pt(d, v):
            x = date.fromisoformat(d).toordinal()
            fx = 0.5 if x1 == x0 else (x - x0) / (x1 - x0)
            return QPointF(area.left() + fx * area.width(), area.bottom() - (v - lo) / span_v * area.height())

        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawLine(QPointF(area.left(), area.bottom()), QPointF(area.right(), area.bottom()))
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(0, area.top() - 7, 64, 14), int(ALIGN_R), gb_number(int(vmax), 2) + " GB")
        p.drawText(QRectF(0, area.bottom() - 7, 64, 14), int(ALIGN_R), gb_number(int(lo), 2) + " GB")
        p.drawText(QRectF(area.left(), area.bottom() + 6, 120, 14), int(ALIGN_L), fmt_date(date.fromordinal(x0).isoformat()))
        p.drawText(QRectF(area.right() - 120, area.bottom() + 6, 120, 14), int(ALIGN_R),
                   fmt_date(date.fromordinal(x1).isoformat()))
        for series, color, name in ((self.buys, theme.ACCENT, "Alış"), (self.sells, theme.GREEN, "Satış")):
            pts = [pt(d, v) for d, v in sorted(series)]
            p.setPen(QPen(QColor(color), 1.6))
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
            p.setBrush(QColor(color))
            for (d, v), q in zip(sorted(series), pts):
                p.drawEllipse(q, 3.5, 3.5)
                self._pts.append((q, f"{name} · {fmt_date(d)} · {fmt_gb(v)}"))
        # lejant
        lx = area.left()
        for color, name in ((theme.ACCENT, "Alış birim fiyatı"), (theme.GREEN, "Satış birim fiyatı")):
            p.setBrush(QColor(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(lx + 5, 12), 4, 4)
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(lx + 14, 4, 140, 16), int(ALIGN_L), name)
            lx += 150
        p.end()

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position()
        for q, text in self._pts:
            if (q.x() - pos.x()) ** 2 + (q.y() - pos.y()) ** 2 < 49:
                QToolTip.showText(event.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color: {theme.BORDER};")
    return f
