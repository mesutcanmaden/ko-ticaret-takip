"""Defter yeniden hesaplama motoru.

Kaynak veriler (işlemler, partiler, parti kullanımları) kronolojik sırayla
(tarih, sonra kayıt sırası) baştan oynatılır ve bütün türetilmiş değerler
(parti maliyetleri, kalan adetler, satış maliyetleri, gerçekleşen kâr/zarar,
bakiye etkileri) yeniden hesaplanır.

Bu sayede geçmiş bir alışın fiyatı değiştiğinde ya da bir satış silindiğinde
bağlı her şey (takasla gelen itemlerin maliyeti dahil) otomatik ve tutarlı
olarak güncellenir. Kural ihlalinde LedgerError fırlatılır ve çağıran
transaction geri alınır.

Takas maliyet yöntemi (maliyet aktarımı):
    Verilen itemlerin gerçek maliyeti  C
    Verilen GB                          O
    Alınan GB                           I
    Aktarılacak maliyet tabanı      B = C + O - I
    * Alınan item varsa ve B >= 0: B, alınan itemlere anlaşılan değerleriyle
      orantılı dağıtılır. Gerçekleşen kâr/zarar = 0 (kâr, alınan item satılınca oluşur).
    * Alınan item varsa ve B < 0 : alınan itemlerin maliyeti 0, gerçekleşen kâr = -B
      (verdiklerinizin toplam maliyetinden fazla GB aldınız).
    * Alınan item yoksa (item -> GB takası): gerçekleşen kâr/zarar = I - O - C.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

from .errors import LedgerError
from .money import distribute, slice_cost
from .upgrades import display_name

TYPE_NAMES = {
    "purchase": "Alış",
    "sale": "Satış",
    "trade": "Takas",
    "deposit": "GB Ekleme",
    "withdraw": "GB Çıkarma",
}


def _product_names(conn: sqlite3.Connection) -> dict[int, str]:
    rows = conn.execute(
        "SELECT p.id, n.name, p.upgrade FROM products p JOIN item_names n ON n.id = p.item_name_id"
    ).fetchall()
    return {r["id"]: display_name(r["name"], r["upgrade"]) for r in rows}


def _fmt_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def rebuild(conn: sqlite3.Connection) -> None:
    """Bütün türetilmiş değerleri yeniden hesaplar. Bir transaction içinde çağrılmalıdır."""
    names = _product_names(conn)
    txs = conn.execute("SELECT * FROM transactions ORDER BY tx_date, id").fetchall()
    lots = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM lots ORDER BY id")}
    lots_by_tx: dict[int, list[dict]] = defaultdict(list)
    for lot in lots.values():
        lots_by_tx[lot["tx_id"]].append(lot)
    cons_by_tx: dict[int, list[dict]] = defaultdict(list)
    for c in conn.execute("SELECT * FROM consumptions ORDER BY id"):
        cons_by_tx[c["tx_id"]].append(dict(c))

    tx_dates = {t["id"]: t["tx_date"] for t in txs}
    active: set[int] = set()
    consumed: dict[int, int] = defaultdict(int)
    lot_cost: dict[int, int] = {}
    cons_cost: dict[int, int] = {}
    tx_updates: list[tuple[int, int, int, int]] = []

    def consume(tx, rows) -> int:
        total = 0
        for c in rows:
            lot = lots.get(c["lot_id"])
            if lot is None:  # FK ile engellenir; yine de koruma
                raise LedgerError(f"#{tx['id']} numaralı işlem silinmiş bir partiye bağlı.")
            pname = names.get(lot["product_id"], "?")
            if c["lot_id"] not in active:
                raise LedgerError(
                    f"#{tx['id']} numaralı {TYPE_NAMES[tx['type']].lower()} işlemi "
                    f"({_fmt_date(tx['tx_date'])}), '{pname}' itemini bu itemin alındığı tarihten "
                    f"({_fmt_date(tx_dates[lot['tx_id']])}) önce kullanıyor. Tarihleri kontrol edin."
                )
            left = lot["qty"] - consumed[c["lot_id"]]
            if c["qty"] > left:
                raise LedgerError(
                    f"Stok yetersiz: '{pname}' (parti #{lot['id']}) için {c['qty']} adet "
                    f"kullanılmak isteniyor ancak o tarihte yalnızca {left} adet mevcut "
                    f"(işlem #{tx['id']})."
                )
            cost = slice_cost(lot_cost[c["lot_id"]], lot["qty"], consumed[c["lot_id"]], c["qty"])
            consumed[c["lot_id"]] += c["qty"]
            cons_cost[c["id"]] = cost
            total += cost
        return total

    for tx in txs:
        t = tx["type"]
        tid = tx["id"]
        my_lots = lots_by_tx.get(tid, [])
        my_cons = cons_by_tx.get(tid, [])
        if t == "purchase":
            if my_cons or not my_lots:
                raise LedgerError(f"#{tid} numaralı alış kaydı bozuk.")
            total = 0
            for lot in my_lots:
                if lot["unit_price"] is None:
                    raise LedgerError(f"#{tid} numaralı alışın birim fiyatı eksik.")
                lot_cost[lot["id"]] = lot["unit_price"] * lot["qty"]
                total += lot_cost[lot["id"]]
                active.add(lot["id"])
            tx_updates.append((-total, total, 0, tid))
        elif t == "sale":
            if my_lots or not my_cons:
                raise LedgerError(f"#{tid} numaralı satış kaydı bozuk.")
            cost = consume(tx, my_cons)
            net = tx["gross_amount"] - tx["tax_amount"]
            if net < 0:
                raise LedgerError(f"#{tid} numaralı satışta vergi brüt tutardan büyük.")
            tx_updates.append((net, cost, net - cost, tid))
        elif t == "trade":
            given = consume(tx, my_cons)
            basis = given + tx["cash_out"] - tx["cash_in"]
            if my_lots:
                if basis >= 0:
                    shares = distribute(basis, [(l["agreed_value"] or 0) * l["qty"] for l in my_lots])
                    realized = 0
                else:
                    shares = [0] * len(my_lots)
                    realized = -basis
                for lot, share in zip(my_lots, shares):
                    lot_cost[lot["id"]] = share
                    active.add(lot["id"])
            else:
                realized = tx["cash_in"] - tx["cash_out"] - given
            tx_updates.append((tx["cash_in"] - tx["cash_out"], given, realized, tid))
        elif t == "deposit":
            tx_updates.append((tx["cash_in"], 0, 0, tid))
        elif t == "withdraw":
            tx_updates.append((-tx["cash_out"], 0, 0, tid))
        else:  # pragma: no cover - CHECK kısıtı engeller
            raise LedgerError(f"Bilinmeyen işlem türü: {t}")

    for lid in lots:
        if lid not in active:  # kendisini oluşturan işlem yok (olmamalı)
            raise LedgerError(f"Parti #{lid} geçersiz bir işleme bağlı.")

    conn.executemany(
        "UPDATE transactions SET net_cash=?, cost_basis=?, realized_pl=? WHERE id=?", tx_updates
    )
    conn.executemany(
        "UPDATE lots SET total_cost=?, remaining=? WHERE id=?",
        [(lot_cost[lid], lots[lid]["qty"] - consumed[lid], lid) for lid in lots],
    )
    conn.executemany("UPDATE consumptions SET cost=? WHERE id=?", [(v, k) for k, v in cons_cost.items()])
    # Satıştaki adet, kalan adetten fazla olamaz (önce tükenen partiler silinir).
    conn.execute(
        "DELETE FROM listings WHERE (SELECT remaining FROM lots WHERE lots.id = listings.lot_id) <= 0"
    )
    conn.execute(
        "UPDATE listings SET qty = (SELECT remaining FROM lots WHERE lots.id = listings.lot_id) "
        "WHERE qty > (SELECT remaining FROM lots WHERE lots.id = listings.lot_id)"
    )

