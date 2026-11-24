from datetime import date

import pytest

from app.core.errors import UserError
from tests.conftest import GB, M


def lots_of(svc, name, upgrade=0):
    pid = [p for p in svc.products() if p["name"] == name and p["upgrade"] == upgrade][0]["id"]
    return pid, svc.lots_for_product(pid)


def assert_consistent(svc):
    """Bütün türetilmiş değerlerin kaynak verilerle tutarlı olduğunu doğrular."""
    c = svc.conn
    assert svc.integrity_ok()
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    for lot in c.execute("SELECT * FROM lots"):
        used = c.execute("SELECT COALESCE(SUM(qty),0), COALESCE(SUM(cost),0) FROM consumptions WHERE lot_id=?",
                         (lot["id"],)).fetchone()
        assert lot["remaining"] == lot["qty"] - used[0] >= 0
        if lot["remaining"] == 0:
            assert used[1] == lot["total_cost"]  # tükenen partinin maliyeti tam dağıtılmış
    for li in c.execute("SELECT l.remaining, li.qty FROM listings li JOIN lots l ON l.id=li.lot_id"):
        assert 0 < li["qty"] <= li["remaining"]
    # bakiye = başlangıç + nakit akışları
    flows = 0
    for t in c.execute("SELECT * FROM transactions"):
        if t["type"] == "purchase":
            flows -= c.execute("SELECT SUM(qty*unit_price) FROM lots WHERE tx_id=?", (t["id"],)).fetchone()[0]
        elif t["type"] == "sale":
            flows += t["gross_amount"] - t["tax_amount"]
        else:
            flows += t["cash_in"] - t["cash_out"]
    assert svc.balance() == svc.initial_balance + flows


# --------------------------------------------------------------------------- #
def test_purchase_updates_stock_and_balance(svc):
    svc.set_initial_balance(100 * GB)
    svc.record_purchase("Shard", 8, 1, 30 * GB, "2026-11-01", "Acil satan oyuncudan alındı.")
    assert svc.balance() == 70 * GB
    s = svc.snapshot()
    assert s["stock_units"] == 1 and s["stock_cost"] == 30 * GB
    hist = svc.list_transactions()
    assert hist[0]["type"] == "purchase" and hist[0]["note"] == "Acil satan oyuncudan alındı."
    assert_consistent(svc)


def test_spec_balance_example(svc):
    svc.set_initial_balance(100 * GB)
    svc.record_purchase("Shard", 8, 1, 30 * GB, "2026-11-01")
    assert svc.balance() == 70 * GB
    pid, lots = lots_of(svc, "Shard", 8)
    svc.record_sale(pid, {lots[0]["id"]: 1}, 40 * GB, "trade", "2026-11-02")
    assert svc.balance() == 110 * GB


def test_weighted_average_and_lots(svc):
    for d, p in [("2026-11-01", 10), ("2026-11-02", 12), ("2026-11-03", 14)]:
        svc.record_purchase("Shard", 8, 1, p * GB, d)
    ov = svc.stock_overview()
    assert len(ov) == 1
    row = ov[0]
    assert row["remaining"] == 3 and row["remaining_cost"] == 36 * GB and row["avg_cost"] == 12 * GB
    assert row["display"] == "Shard +8" and row["status"] == "Stokta"
    assert row["days_held"] == 6  # 01.11 -> 07.11


def test_upgrade_levels_are_separate_products(svc):
    svc.record_purchase("Shard", 7, 1, GB, "2026-11-01")
    svc.record_purchase("shard", 8, 1, GB, "2026-11-01")
    svc.record_purchase("  SHARD ", 8, 1, GB, "2026-11-01")
    assert len(svc.item_names()) == 1  # aynı item adı farklı yazımla tekrar oluşmadı
    assert sorted(p["display"] for p in svc.products()) == ["Shard +7", "Shard +8"]


def test_market_vs_trade_profit(svc):
    svc.record_purchase("Kılıç", 0, 2, 10 * GB, "2026-11-01")
    pid, lots = lots_of(svc, "Kılıç")
    pv = svc.preview_sale(pid, {lots[0]["id"]: 1}, 15 * GB, "market", "2026-11-05")
    assert pv["tax"] == 45 * M and pv["profit"] == 455 * M
    t1 = svc.record_sale(pid, {lots[0]["id"]: 1}, 15 * GB, "market", "2026-11-05")
    t2 = svc.record_sale(pid, {lots[0]["id"]: 1}, 15 * GB, "trade", "2026-11-05")
    d1, d2 = svc.transaction_detail(t1)["tx"], svc.transaction_detail(t2)["tx"]
    assert d1["realized_pl"] == 455 * M and d1["tax_bps"] == 300 and d1["tax_amount"] == 45 * M
    assert d2["realized_pl"] == 5 * GB and d2["tax_amount"] == 0
    assert_consistent(svc)


def test_tax_rate_change_does_not_alter_history(svc):
    svc.record_purchase("A", 0, 2, 10 * GB, "2026-11-01")
    pid, lots = lots_of(svc, "A")
    t1 = svc.record_sale(pid, {lots[0]["id"]: 1}, 15 * GB, "market", "2026-11-02")
    svc.set_tax_bps(500)
    t2 = svc.record_sale(pid, {lots[0]["id"]: 1}, 15 * GB, "market", "2026-11-02")
    svc.recompute()
    assert svc.transaction_detail(t1)["tx"]["tax_amount"] == 45 * M
    assert svc.transaction_detail(t2)["tx"]["tax_amount"] == 75 * M


def test_partial_sale_and_multi_lot_sale(svc):
    svc.record_purchase("Taş", 0, 10, 1 * GB, "2026-11-01")
    svc.record_purchase("Taş", 0, 5, 2 * GB, "2026-11-02")
    pid, lots = lots_of(svc, "Taş")
    a, b = lots[0]["id"], lots[1]["id"]
    svc.record_sale(pid, {a: 4}, 6 * GB, "trade", "2026-11-03")
    pid, lots = lots_of(svc, "Taş")
    assert lots[0]["remaining"] == 6
    tid = svc.record_sale(pid, {a: 6, b: 2}, 20 * GB, "trade", "2026-11-04")
    tx = svc.transaction_detail(tid)["tx"]
    assert tx["cost_basis"] == 6 * GB + 4 * GB and tx["realized_pl"] == 10 * GB
    assert svc.snapshot()["stock_units"] == 3
    assert_consistent(svc)


def test_cannot_oversell(svc):
    svc.record_purchase("Taş", 0, 2, GB, "2026-11-01")
    pid, lots = lots_of(svc, "Taş")
    with pytest.raises(UserError):
        svc.record_sale(pid, {lots[0]["id"]: 3}, GB, "trade", "2026-11-02")
    assert svc.snapshot()["stock_units"] == 2


def test_sale_before_purchase_date_rejected(svc):
    svc.record_purchase("Taş", 0, 2, GB, "2026-11-05")
    pid, lots = lots_of(svc, "Taş")
    with pytest.raises(UserError):
        svc.record_sale(pid, {lots[0]["id"]: 1}, GB, "trade", "2026-11-01")
    assert svc.list_transactions(types=["sale"]) == []


def test_sale_lot_must_match_product(svc):
    svc.record_purchase("A", 0, 1, GB, "2026-11-01")
    svc.record_purchase("B", 0, 1, GB, "2026-11-01")
    pa, _ = lots_of(svc, "A")
    _, lb = lots_of(svc, "B")
    with pytest.raises(UserError):
        svc.record_sale(pa, {lb[0]["id"]: 1}, GB, "trade", "2026-11-02")


def test_listing_states(svc, clock):
    svc.record_purchase("Taş", 0, 10, GB, "2026-11-01")
    pid, lots = lots_of(svc, "Taş")
    lid = lots[0]["id"]
    svc.set_listing(lid, 4, "2026-11-03")
    row = svc.stock_overview()[0]
    assert row["listed"] == 4 and row["in_stock"] == 6 and row["remaining"] == 10
    assert row["status"] == "Kısmen satışta" and row["days_listed"] == 4
    assert svc.snapshot()["listed_units"] == 4
    assert svc.snapshot()["stock_units"] == 10  # satışa çıkarmak mülkiyetten düşürmez
    with pytest.raises(UserError):
        svc.set_listing(lid, 11)
    # pazar satışı önce satıştakilerden düşer
    t = svc.record_sale(pid, {lid: 3}, 3 * GB, "market", "2026-11-06")
    _, lots = lots_of(svc, "Taş")
    assert lots[0]["listed"] == 1 and lots[0]["remaining"] == 7
    # trade satışı önce stoktakilerden düşer
    svc.record_sale(pid, {lid: 6}, 6 * GB, "trade", "2026-11-06")
    _, lots = lots_of(svc, "Taş")
    assert lots[0]["listed"] == 1 and lots[0]["remaining"] == 1
    assert svc.stock_overview()[0]["status"] == "Satışta"
    # satış silinince satıştaki adetler geri döner
    svc.delete_transaction(t)
    _, lots = lots_of(svc, "Taş")
    assert lots[0]["remaining"] == 4 and lots[0]["listed"] == 4
    assert lots[0]["listed_since"] == "2026-11-03"
    svc.set_listing(lid, 0)
    assert svc.snapshot()["listed_units"] == 0
    assert_consistent(svc)


def test_sold_out_status(svc):
    svc.record_purchase("A", 0, 1, GB, "2026-11-01")
    pid, lots = lots_of(svc, "A")
    svc.record_sale(pid, {lots[0]["id"]: 1}, 2 * GB, "trade", "2026-11-02")
    assert svc.stock_overview() == []
    full = svc.stock_overview(include_sold=True)
    assert full[0]["status"] == "Satıldı"
    h = svc.product_history(pid)
    assert h["realized"] == GB and h["avg_buy"] == GB and h["avg_sell"] == 2 * GB


# --------------------------------------------------------------------------- #
# GB hareketleri
# --------------------------------------------------------------------------- #
def test_cash_movements_not_profit(svc):
    svc.set_initial_balance(10 * GB)
    t = svc.record_cash("deposit", 5 * GB, "2026-11-01", "Görevden geldi")
    svc.record_cash("withdraw", 2 * GB, "2026-11-01")
    assert svc.balance() == 13 * GB
    tot = svc.period_totals("all")
    assert tot["profit"] == 0 and tot["loss"] == 0
    svc.update_cash(t, 7 * GB, "2026-11-01", "")
    assert svc.balance() == 15 * GB
    with pytest.raises(UserError):
        svc.record_cash("deposit", 0, "2026-11-01")
    assert_consistent(svc)


# --------------------------------------------------------------------------- #
# Takas
# --------------------------------------------------------------------------- #
def test_trade_spec_example(svc):
    """20 GB maliyetli item -> 15 GB değerli item + 5 GB."""
    svc.set_initial_balance(100 * GB)
    svc.record_purchase("Zırh", 0, 1, 20 * GB, "2026-11-01")
    _, lots = lots_of(svc, "Zırh")
    given = [(lots[0]["id"], 1)]
    received = [{"name": "Yüzük", "upgrade": 1, "qty": 1, "agreed_value": 15 * GB}]
    pv = svc.preview_trade(given, received, 0, 5 * GB, "2026-11-02")
    assert pv["given_cost"] == 20 * GB and pv["basis"] == 15 * GB
    assert pv["received"][0]["cost"] == 15 * GB and pv["realized"] == 0
    assert svc.list_transactions(types=["trade"]) == []  # önizleme kayıt oluşturmaz
    svc.record_trade(given, received, 0, 5 * GB, "2026-11-02", "Takasla alındı.")
    assert svc.balance() == 85 * GB
    pid, rl = lots_of(svc, "Yüzük", 1)
    assert rl[0]["total_cost"] == 15 * GB and rl[0]["source"] == "Takas"
    assert svc.period_totals("all")["net_profit"] == 0  # takas otomatik kâr üretmez
    # alınan item 18 GB'a satılınca gerçek kâr oluşur: 18 - 15 = 3
    svc.record_sale(pid, {rl[0]["id"]: 1}, 18 * GB, "trade", "2026-11-03")
    assert svc.period_totals("all")["net_profit"] == 3 * GB
    assert_consistent(svc)


def test_trade_cost_distribution_multi(svc):
    svc.record_purchase("A", 0, 1, 10 * GB, "2026-11-01")
    _, la = lots_of(svc, "A")
    rec = [{"name": "B", "qty": 3, "agreed_value": 2 * GB}, {"name": "C", "qty": 1, "agreed_value": 4 * GB}]
    svc.record_trade([(la[0]["id"], 1)], rec, 1, 0, "2026-11-02")  # 1 Noah da verildi
    _, lb = lots_of(svc, "B")
    _, lc = lots_of(svc, "C")
    assert lb[0]["total_cost"] + lc[0]["total_cost"] == 10 * GB + 1
    assert lb[0]["total_cost"] in (6 * GB, 6 * GB + 1)  # 6/10 oranı (fark en fazla 1 Noah)
    # 3 adetlik B'nin parça parça satışı toplam maliyeti tam tüketir
    pb, _ = lots_of(svc, "B")
    for d in ("2026-11-03", "2026-11-04", "2026-11-05"):
        _, lb = lots_of(svc, "B")
        svc.record_sale(pb, {lb[0]["id"]: 1}, GB, "trade", d)
    assert_consistent(svc)


def test_trade_more_cash_than_cost_realizes_profit(svc):
    svc.record_purchase("A", 0, 1, 5 * GB, "2026-11-01")
    _, la = lots_of(svc, "A")
    pv = svc.preview_trade([(la[0]["id"], 1)], [{"name": "B", "qty": 1, "agreed_value": GB}], 0, 7 * GB,
                           "2026-11-02")
    assert pv["realized"] == 2 * GB and pv["received"][0]["cost"] == 0


def test_trade_item_for_gb_only(svc):
    svc.record_purchase("A", 0, 1, 5 * GB, "2026-11-01")
    _, la = lots_of(svc, "A")
    t = svc.record_trade([(la[0]["id"], 1)], [], 0, 4 * GB, "2026-11-02")
    assert svc.transaction_detail(t)["tx"]["realized_pl"] == -GB


def test_trade_validation_and_atomicity(svc):
    svc.set_initial_balance(10 * GB)
    svc.record_purchase("A", 0, 1, 5 * GB, "2026-11-01")
    _, la = lots_of(svc, "A")
    before = (svc.balance(), svc.snapshot(), len(svc.list_transactions()))
    with pytest.raises(UserError):
        svc.record_trade([(la[0]["id"], 2)], [{"name": "B", "qty": 1}], 0, 0, "2026-11-02")
    with pytest.raises(UserError):
        svc.record_trade([], [], 0, 0, "2026-11-02")
    with pytest.raises(UserError):  # tarih alıştan önce -> tamamen geri alınır
        svc.record_trade([(la[0]["id"], 1)], [{"name": "B", "qty": 1}], 0, 0, "2026-10-01")
    assert (svc.balance(), svc.snapshot(), len(svc.list_transactions())) == before
    assert [p["name"] for p in svc.products()] == ["A"]  # yarım kalan ürün kaydı da geri alındı


def test_buy_with_gb_and_item(svc):
    svc.record_purchase("A", 0, 1, 5 * GB, "2026-11-01")
    _, la = lots_of(svc, "A")
    svc.record_trade([(la[0]["id"], 1)], [{"name": "B", "qty": 1, "agreed_value": 8 * GB}], 3 * GB, 0,
                     "2026-11-02")
    _, lb = lots_of(svc, "B")
    assert lb[0]["total_cost"] == 8 * GB


# --------------------------------------------------------------------------- #
# Düzenleme / silme / geri alma
# --------------------------------------------------------------------------- #
def test_edit_purchase_price_propagates(svc):
    svc.record_purchase("A", 0, 2, 10 * GB, "2026-11-01")
    pid, la = lots_of(svc, "A")
    sale = svc.record_sale(pid, {la[0]["id"]: 1}, 15 * GB, "trade", "2026-11-02")
    trade = svc.record_trade([(la[0]["id"], 1)], [{"name": "B", "qty": 1, "agreed_value": GB}], 0, 0,
                             "2026-11-03")
    tx = svc.list_transactions(types=["purchase"])[0]
    svc.update_purchase(tx["id"], "A", 0, 2, 12 * GB, "2026-11-01", "düzeltildi")
    assert svc.transaction_detail(sale)["tx"]["realized_pl"] == 3 * GB
    _, lb = lots_of(svc, "B")
    assert lb[0]["total_cost"] == 12 * GB  # takasla gelen itemin maliyeti de güncellendi
    assert svc.transaction_detail(trade)["tx"]["cost_basis"] == 12 * GB
    assert_consistent(svc)


def test_edit_purchase_guards(svc):
    svc.record_purchase("A", 0, 5, GB, "2026-11-01")
    pid, la = lots_of(svc, "A")
    svc.record_sale(pid, {la[0]["id"]: 3}, 3 * GB, "trade", "2026-11-02")
    ptx = svc.list_transactions(types=["purchase"])[0]["id"]
    with pytest.raises(UserError):
        svc.update_purchase(ptx, "A", 0, 2, GB, "2026-11-01")  # satılandan az
    with pytest.raises(UserError):
        svc.update_purchase(ptx, "Başka", 0, 5, GB, "2026-11-01")  # satış yapılmış partide item değişmez
    with pytest.raises(UserError):
        svc.update_purchase(ptx, "A", 0, 5, GB, "2026-11-05")  # satıştan sonraya alınamaz
    svc.update_purchase(ptx, "A", 0, 3, GB, "2026-11-01")
    assert svc.snapshot()["stock_units"] == 0
    assert_consistent(svc)


def test_edit_sale(svc):
    svc.set_initial_balance(0)
    svc.record_purchase("A", 0, 1, 10 * GB, "2026-11-01")
    pid, la = lots_of(svc, "A")
    t = svc.record_sale(pid, {la[0]["id"]: 1}, 15 * GB, "market", "2026-11-02")
    svc.update_sale(t, 20 * GB, "market", None, "2026-11-03", "fiyat düzeltildi")
    tx = svc.transaction_detail(t)["tx"]
    assert tx["tax_amount"] == 60 * M and tx["realized_pl"] == 940 * M
    svc.update_sale(t, 20 * GB, "trade", None, "2026-11-03", "")
    assert svc.transaction_detail(t)["tx"]["realized_pl"] == 10 * GB
    assert svc.balance() == 10 * GB
    assert_consistent(svc)


def test_delete_purchase_blocked_when_sold(svc):
    svc.record_purchase("A", 0, 1, GB, "2026-11-01")
    pid, la = lots_of(svc, "A")
    s = svc.record_sale(pid, {la[0]["id"]: 1}, GB, "trade", "2026-11-02")
    p = svc.list_transactions(types=["purchase"])[0]["id"]
    with pytest.raises(UserError):
        svc.delete_transaction(p)
    svc.delete_transaction(s)
    svc.delete_transaction(p)
    assert svc.list_transactions() == [] and svc.balance() == 0
    assert_consistent(svc)


def test_delete_trade_blocked_when_received_sold(svc):
    svc.record_purchase("A", 0, 1, GB, "2026-11-01")
    _, la = lots_of(svc, "A")
    t = svc.record_trade([(la[0]["id"], 1)], [{"name": "B", "qty": 1}], 0, 0, "2026-11-02")
    pb, lb = lots_of(svc, "B")
    svc.record_sale(pb, {lb[0]["id"]: 1}, GB, "trade", "2026-11-03")
    with pytest.raises(UserError):
        svc.delete_transaction(t)
    assert svc.dependents(t)


def test_undo_last(svc):
    svc.set_initial_balance(50 * GB)
    svc.record_purchase("A", 0, 2, 10 * GB, "2026-11-01")
    pid, la = lots_of(svc, "A")
    svc.set_listing(la[0]["id"], 2)
    svc.record_sale(pid, {la[0]["id"]: 1}, 15 * GB, "market", "2026-11-02")
    svc.record_cash("deposit", GB, "2026-11-02")
    assert svc.undo_last()["type"] == "deposit"
    undone = svc.undo_last()
    assert undone["type"] == "sale"
    assert svc.balance() == 30 * GB
    _, la = lots_of(svc, "A")
    assert la[0]["remaining"] == 2 and la[0]["listed"] == 2
    assert svc.undo_last()["type"] == "purchase"
    assert svc.balance() == 50 * GB
    with pytest.raises(UserError):
        svc.undo_last()
    assert_consistent(svc)


def test_undo_blocked_by_dependency(svc):
    svc.record_purchase("A", 0, 1, GB, "2026-11-01")
    pid, la = lots_of(svc, "A")
    sale = svc.record_sale(pid, {la[0]["id"]: 1}, GB, "trade", "2026-11-03")
    # geriye tarihli yeni bir alış "son işlem" olur; geri alınabilir
    svc.record_purchase("B", 0, 1, GB, "2026-10-01")
    assert svc.undo_last()["items"].startswith("B")
    assert svc.last_transaction()["id"] == sale


# --------------------------------------------------------------------------- #
# İsimler
# --------------------------------------------------------------------------- #
def test_rename_keeps_links(svc):
    svc.record_purchase("Shard", 8, 1, GB, "2026-11-01")
    pid, la = lots_of(svc, "Shard", 8)
    svc.record_sale(pid, {la[0]["id"]: 1}, 2 * GB, "trade", "2026-11-02")
    nid = svc.item_names()[0]["id"]
    svc.rename_item(nid, "Shard of Power")
    assert svc.product(pid)["display"] == "Shard of Power +8"
    assert "Shard of Power +8" in svc.list_transactions()[0]["items"]
    svc.record_purchase("Kılıç", 0, 1, GB, "2026-11-01")
    with pytest.raises(UserError):
        svc.rename_item(nid, "kılıç")


def test_similar_names_and_completion(svc):
    from app.core.service import split_name_upgrade
    svc.record_purchase("Shard", 8, 1, GB, "2026-11-01")
    assert svc.similar_names("Shrad") == ["Shard"]
    assert svc.similar_names("shard") == []  # aynı isim -> mükerrer değil, mevcut kullanılır
    assert svc.similar_names("Sha rd") == ["Shard"]
    assert "Shard +8" in svc.completion_list()
    assert split_name_upgrade("Shard +8") == ("Shard", 8)
    assert split_name_upgrade("Shard+10") == ("Shard", 10)
    assert split_name_upgrade("Shard") == ("Shard", None)
    assert svc.existing_name("SHARD") == "Shard"


def test_turkish_case_keys(svc):
    svc.record_purchase("İksir", 0, 1, GB, "2026-11-01")
    svc.record_purchase("iksir", 0, 1, GB, "2026-11-01")
    svc.record_purchase("Işık", 0, 1, GB, "2026-11-01")
    svc.record_purchase("ışık", 0, 1, GB, "2026-11-01")
    assert len(svc.item_names()) == 2


# --------------------------------------------------------------------------- #
# İstatistik / ana sayfa
# --------------------------------------------------------------------------- #
def test_dashboard_and_stats_periods(svc, clock):
    svc.set_initial_balance(100 * GB)
    svc.record_purchase("A", 0, 3, 10 * GB, "2026-10-01")
    pid, la = lots_of(svc, "A")
    svc.record_sale(pid, {la[0]["id"]: 1}, 15 * GB, "trade", "2026-10-15")    # +5 ekim
    svc.record_sale(pid, {la[0]["id"]: 1}, 8 * GB, "trade", "2026-11-03")     # -2 bu hafta (Pzt 02.11)
    svc.record_sale(pid, {la[0]["id"]: 1}, 15 * GB, "market", "2026-11-07")   # +4,55 bugün
    allp = svc.dashboard("all")
    assert allp["profit"] == 955 * M and allp["loss"] == 2 * GB and allp["net_profit"] == 755 * M
    assert allp["purchase_total"] == 30 * GB and allp["sale_count"] == 3
    assert allp["stock_units"] == 0 and allp["stock_cost"] == 0
    assert svc.period_totals("today")["net_profit"] == 455 * M
    assert svc.period_totals("week")["net_profit"] == 255 * M
    assert svc.period_totals("month")["purchase_total"] == 0
    st = svc.statistics("all")
    assert st["top_profit"][0]["display"] == "A"
    assert st["sold_units"] == 3
    assert st["avg_days_to_sell"] is not None
    assert len(svc.profit_chart("week")) == 7
    assert svc.profit_chart("all")[-1][0] == "11.2026"
    assert sum(v for _, v in svc.profit_chart("all")) == 755 * M


def test_history_filters(svc):
    svc.record_purchase("Shard", 8, 1, GB, "2026-11-01", "ucuz")
    svc.record_purchase("Kılıç", 0, 1, GB, "2026-11-02")
    pid, la = lots_of(svc, "Shard", 8)
    svc.record_sale(pid, {la[0]["id"]: 1}, 3 * GB, "trade", "2026-11-03")
    svc.record_cash("deposit", GB, "2026-11-04")
    assert len(svc.list_transactions(search="sha")) == 2
    assert len(svc.list_transactions(search="ucuz")) == 1
    assert len(svc.list_transactions(types=["deposit"])) == 1
    assert len(svc.list_transactions(date_from="2026-11-02", date_to="2026-11-03")) == 2
    assert svc.list_transactions(sort="profit_desc")[0]["type"] == "sale"


def test_calculators_do_not_write(svc):
    n = len(svc.list_transactions())
    r = svc.calc_target_price(10 * GB, 2 * GB, "market")
    assert r["net"] >= 12 * GB and r["profit"] >= 2 * GB
    assert svc.calc_target_price(10 * GB, 2 * GB, "trade")["price"] == 12 * GB
    o = svc.calc_offer(10 * GB, 15 * GB, "market")
    assert o["profit"] == 455 * M
    assert len(svc.list_transactions()) == n


def test_bulk_random_consistency(svc):
    """Rastgele çok sayıda işlem sonrası bütün kurallar tutarlı kalmalı."""
    import random
    rnd = random.Random(42)
    svc.set_initial_balance(1000 * GB)
    names = ["A", "B", "C"]
    for i in range(300):
        d = date(2026, 1, 1).toordinal() + i // 3
        day = date.fromordinal(d).isoformat()
        r = rnd.random()
        try:
            if r < 0.4:
                svc.record_purchase(rnd.choice(names), rnd.randint(0, 2), rnd.randint(1, 5),
                                    rnd.randint(1, 10 ** 9), day)
            elif r < 0.75:
                lots = svc.available_lots()
                if lots:
                    lot = rnd.choice(lots)
                    svc.record_sale(lot["product_id"], {lot["id"]: rnd.randint(1, lot["remaining"])},
                                    rnd.randint(0, 2 * 10 ** 9), rnd.choice(["market", "trade"]), day)
            elif r < 0.85:
                lots = svc.available_lots()
                if lots:
                    lot = rnd.choice(lots)
                    svc.record_trade([(lot["id"], 1)], [{"name": rnd.choice(names), "qty": rnd.randint(1, 3),
                                                        "agreed_value": rnd.randint(0, 10 ** 9)}],
                                     rnd.randint(0, 10 ** 8), rnd.randint(0, 10 ** 8), day)
            elif r < 0.9:
                lots = svc.available_lots()
                if lots:
                    lot = rnd.choice(lots)
                    svc.set_listing(lot["id"], rnd.randint(0, lot["remaining"]))
            elif r < 0.95:
                txs = svc.list_transactions()
                if txs:
                    try:
                        svc.delete_transaction(rnd.choice(txs)["id"])
                    except UserError:
                        pass
            else:
                svc.record_cash(rnd.choice(["deposit", "withdraw"]), rnd.randint(1, 10 ** 9), day)
        except UserError:
            pass
    assert_consistent(svc)


def test_price_mode_setting(svc):
    assert svc.price_mode == "m"  # varsayılan: yalnızca M
    for mode in ("gb", "gbm", "m"):
        svc.set_price_mode(mode)
        assert svc.price_mode == mode
    with pytest.raises(UserError):
        svc.set_price_mode("x")


def test_upgrade_levels_normal_and_rebirth(svc):
    from app.core import upgrades
    from app.core.service import split_name_upgrade
    assert len(upgrades.LEVELS) == 1 + 10 + 21
    assert [upgrades.combo_label(u) for u in upgrades.LEVELS[:3]] == ["Yok", "+1", "+2"]
    assert upgrades.combo_label(upgrades.LEVELS[-1]) == "Reb21"
    assert split_name_upgrade("Shard Reb3") == ("Shard", 103)
    assert split_name_upgrade("shard reb 21") == ("shard", 121)
    assert split_name_upgrade("Shard +10") == ("Shard", 10)
    assert split_name_upgrade("Shard +11") == ("Shard +11", None)  # listede yok
    assert split_name_upgrade("Shard Reb22") == ("Shard Reb22", None)
    svc.record_purchase("Kılıç", 103, 1, GB, "2026-11-01")
    svc.record_purchase("Kılıç", 3, 1, GB, "2026-11-01")
    names = sorted(p["display"] for p in svc.products())
    assert names == ["Kılıç +3", "Kılıç Reb3"]  # +3 ve Reb3 ayrı ürünler
    assert "Kılıç Reb3" in svc.list_transactions()[-1]["items"] or "Kılıç Reb3" in svc.list_transactions()[0]["items"]
    for bad in (11, 30, 100, 122, -1):
        with pytest.raises(UserError):
            svc.record_purchase("Kılıç", bad, 1, GB, "2026-11-01")
    # takasla Reb item alma
    _, la = lots_of(svc, "Kılıç", 3)
    svc.record_trade([(la[0]["id"], 1)], [{"name": "Zırh", "upgrade": 121, "qty": 1}], 0, 0, "2026-11-02")
    assert any(p["display"] == "Zırh Reb21" for p in svc.products())


def test_legacy_upgrade_value_still_usable(svc):
    """Eski sürümde +15 gibi listede olmayan bir seviye girildiyse kayıt kullanılmaya devam eder."""
    with svc.db.transaction() as c:
        c.execute("INSERT INTO item_names(name, name_key, created_at) VALUES ('Eski','eski','x')")
        c.execute("INSERT INTO products(item_name_id, upgrade) VALUES (1, 15)")
    svc.record_purchase("Eski", 15, 1, GB, "2026-11-01")
    assert svc.products()[0]["display"] == "Eski +15"
