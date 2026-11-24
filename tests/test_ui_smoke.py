"""Gerçek PySide6 ile arayüz duman testi (ekransız). PySide6 kurulu değilse atlanır.

Pencereyi açar, bütün sayfaları gezer ve arayüz üzerinden alış, satış, takas,
geri alma ve yedekleme yapar.
"""
import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

GB = 100_000_000


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    from app.ui import theme
    app.setStyleSheet(theme.QSS)
    yield app


@pytest.fixture
def window(qapp, svc, monkeypatch):
    msgs = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: msgs.append(("warning", a[2]))))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: msgs.append(("info", a[2]))))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: msgs.append(("critical", a[2]))))
    import app.ui.dialogs as dlg_mod
    import app.ui.main_window as mw_mod
    import app.ui.pages.buy as buy_mod
    import app.ui.pages.sell as sell_mod
    import app.ui.pages.settings as set_mod
    for m in (dlg_mod, mw_mod, buy_mod, sell_mod, set_mod):
        monkeypatch.setattr(m, "confirm", lambda *a, **k: True)
    from app.ui.main_window import MainWindow
    svc.set_initial_balance(100 * GB)
    w = MainWindow(svc)
    w.resize(1280, 800)
    w.show()
    qapp.processEvents()
    w.msgs = msgs
    yield w
    w.close()


def _errors(w):
    return [m for m in w.msgs if m[0] in ("warning", "critical")]


def test_full_flow(window, svc, qapp):
    w = window
    for i in range(w.nav.count()):
        w.nav.setCurrentRow(i)
        qapp.processEvents()
        w.grab()  # her sayfa gerçekten çizilebiliyor mu
    # Alış
    w.go("buy")
    buy = w.pages["buy"]
    buy.name.setText("Shard +8")
    buy.name.editingFinished.emit()
    assert buy.upgrade.value() == 8
    buy.qty.setValue(2)
    assert buy.price.mode == "m"  # varsayılan: fiyat M olarak yazılır
    buy.price.gb.setText("1000")  # 1000 M = 10 GB
    buy.save()
    assert not _errors(w), w.msgs
    assert svc.balance() == 80 * GB
    # Satış
    pid = svc.products()[0]["id"]
    w.go("sell", product_id=pid)
    sale = w.pages["sell"].sale
    sale.price.gb.setText("1500")
    qapp.processEvents()
    assert sale.pv["profit"].text() == "+4,55 GB"
    sale.save()
    assert not _errors(w), w.msgs
    # Takas
    w.go("sell", tab=1)
    tr = w.pages["sell"].trade
    tr.lot_combo.setCurrentIndex(1)
    tr._add_given()
    tr.rec_name.setText("Yüzük")
    tr.rec_val.gb.setText("1200")
    tr._add_received()
    tr.cash_in.gb.setText("100")
    assert tr.pv["basis"].text() == "9 GB"
    tr.save()
    assert not _errors(w), w.msgs
    # Diğer sayfalar ve grafikler
    for key in ("home", "stock", "history", "stats", "tools", "settings"):
        w.go(key)
        qapp.processEvents()
        w.grab()
    st = w.pages["stock"]
    st.table.selectRow(0)
    qapp.processEvents()
    st.grab()
    # Geri alma
    w.undo_last()
    assert not any(p["display"] == "Yüzük" and svc.lots_for_product(p["id"]) for p in svc.products())
    # Yedek
    w.go("settings")
    w.pages["settings"]._backup_now()
    assert w.pages["settings"].backups.rowCount() >= 1
    assert not _errors(w), w.msgs
