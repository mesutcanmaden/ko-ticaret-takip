from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget


class Bus(QObject):
    """Sayfalar arası haberleşme: veriler değiştiğinde ilgili ekranlar yenilenir."""
    data_changed = Signal()
    settings_changed = Signal()


class Context:
    def __init__(self, service, bus: Bus, main=None):
        self.service = service
        self.bus = bus
        self.main = main


class Page(QWidget):
    title = ""

    def __init__(self, ctx: Context, scroll: bool = False, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.svc = ctx.service
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.body = QWidget()
        self.body.setObjectName("Root")
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(22, 18, 22, 18)
        self.lay.setSpacing(10)
        if scroll:
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setWidget(self.body)
            outer.addWidget(sa)
        else:
            outer.addWidget(self.body)

    def refresh(self) -> None:  # alt sınıflar uygular
        pass

    def changed(self) -> None:
        """Bir kayıt değiştiğinde çağrılır; bütün ekranlar güncellenir."""
        self.ctx.bus.data_changed.emit()
