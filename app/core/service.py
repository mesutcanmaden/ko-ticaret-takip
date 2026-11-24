"""Uygulamanın iş mantığı. Arayüz yalnızca bu sınıfı kullanır.

Her yazma işlemi tek bir transaction içinde yapılır; ardından ledger.rebuild()
bütün hesapları yeniden kurar. Herhangi bir kural ihlalinde (stok eksiye düşmesi,
tarih sırası hatası vb.) transaction tamamen geri alınır.
"""
from __future__ import annotations

import difflib
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Iterable

from . import ledger
from .db import Database
from .errors import LedgerError, UserError
from .ledger import TYPE_NAMES
from .upgrades import display_name, is_valid as upgrade_is_valid, split_name_upgrade  # noqa: F401
from .money import (
    MAX_NOAH,
    evaluate_offer,
    min_sale_price,
    sale_tax,
)

DEFAULT_TAX_BPS = 300
MAX_QTY = 1_000_000
NAME_MAX_LEN = 80

METHOD_NAMES = {"market": "Pazar", "trade": "Trade"}
PERIODS = {"today": "Bugün", "week": "Bu Hafta", "month": "Bu Ay", "all": "Tüm Zamanlar"}


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def clean_name(name: str) -> str:
    s = " ".join(str(name or "").split())
    if not s:
        raise UserError("Item adı boş bırakılamaz.")
    if len(s) > NAME_MAX_LEN:
        raise UserError(f"Item adı en fazla {NAME_MAX_LEN} karakter olabilir.")
    return s


def name_key(name: str) -> str:
    """Büyük/küçük harf ve boşluk farklarını yok sayan (Türkçe uyumlu) anahtar."""
    s = " ".join(str(name or "").split())
    s = s.replace("İ", "i").replace("I", "ı").lower()
    return s




def to_iso(d) -> str:
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    s = str(d).strip()
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        pass
    try:
        return datetime.strptime(s, "%d.%m.%Y").date().isoformat()
    except ValueError:
        raise UserError(f"Geçersiz tarih: '{d}'") from None


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    y, m, d = iso[:10].split("-")
    return f"{d}.{m}.{y}"


def days_between(a_iso: str, b_iso: str) -> int:
    return (date.fromisoformat(b_iso[:10]) - date.fromisoformat(a_iso[:10])).days


def _check_amount(v: int, field: str, allow_zero: bool = True) -> int:
    if v is None:
        raise UserError(f"{field} girilmelidir.")
    v = int(v)
    if v < 0:
        raise UserError(f"{field} negatif olamaz.")
    if not allow_zero and v == 0:
        raise UserError(f"{field} sıfır olamaz.")
    if v > MAX_NOAH:
        raise UserError(f"{field} çok büyük.")
    return v


def _check_qty(q: int, field: str = "Adet") -> int:
    q = int(q)
    if q <= 0:
        raise UserError(f"{field} en az 1 olmalıdır.")
    if q > MAX_QTY:
        raise UserError(f"{field} çok büyük.")
    return q


def _check_upgrade(u) -> int:
    u = int(u or 0)
    if not upgrade_is_valid(u):
        raise UserError("Geçersiz upgrade seviyesi. Listeden seçin: Yok, +1 … +10 veya Reb1 … Reb21.")
    return u


def _round_div(a: int, b: int) -> int:
    if b == 0:
        return 0
    return int((Decimal(a) / Decimal(b)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


class TradeService:
    def __init__(self, db: Database, today: Callable[[], date] = date.today):
        self.db = db
        self._today = today
        self._ensure_defaults()

    # ------------------------------------------------------------------ #
    # Genel
    # ------------------------------------------------------------------ #
    @property
    def conn(self) -> sqlite3.Connection:
        return self.db.conn

    def today(self) -> date:
        return self._today()

    def today_iso(self) -> str:
        return self.today().isoformat()

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _ensure_defaults(self) -> None:
        defaults = {"tax_bps": str(DEFAULT_TAX_BPS), "price_mode": "m", "initial_balance": "0"}
        with self.db.transaction() as c:
            for k, v in defaults.items():
                c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))

    def _write(self, fn):
        """Yazma işlemi + yeniden hesaplama, tek transaction."""
        with self.db.transaction() as c:
            result = fn(c)
            ledger.rebuild(c)
            return result

    # ------------------------------------------------------------------ #
    # Ayarlar
    # ------------------------------------------------------------------ #
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    @property
    def tax_bps(self) -> int:
        return int(self.get_setting("tax_bps", str(DEFAULT_TAX_BPS)))

    def set_tax_bps(self, bps: int) -> None:
        bps = int(bps)
        if bps < 0 or bps >= 10000:
            raise UserError("Vergi oranı %0 ile %100 arasında olmalıdır.")
        self.set_setting("tax_bps", str(bps))

    @property
    def price_mode(self) -> str:
        return self.get_setting("price_mode", "m") or "m"

    def set_price_mode(self, mode: str) -> None:
        if mode not in ("gb", "gbm", "m"):
            raise UserError("Geçersiz fiyat giriş yöntemi.")
        self.set_setting("price_mode", mode)

    @property
    def initial_balance(self) -> int:
        return int(self.get_setting("initial_balance", "0"))

    def set_initial_balance(self, noah: int) -> None:
        _check_amount(noah, "Başlangıç GB")
        self.set_setting("initial_balance", str(int(noah)))

    def is_initialized(self) -> bool:
        return self.get_setting("initialized") == "1"

    def mark_initialized(self) -> None:
        self.set_setting("initialized", "1")

    # ------------------------------------------------------------------ #
    # Item adları ve ürünler
    # ------------------------------------------------------------------ #
    def _get_or_create_product(self, c: sqlite3.Connection, name: str, upgrade: int) -> int:
        name = clean_name(name)
        upgrade = int(upgrade or 0)
        key = name_key(name)
        r = c.execute("SELECT id FROM item_names WHERE name_key=?", (key,)).fetchone()
        if r:
            nid = r["id"]
        else:
            nid = c.execute(
                "INSERT INTO item_names(name, name_key, created_at) VALUES (?, ?, ?)",
                (name, key, self._now()),
            ).lastrowid
        r = c.execute("SELECT id FROM products WHERE item_name_id=? AND upgrade=?", (nid, upgrade)).fetchone()
        if r:  # mevcut ürün (eski sürümde girilmiş farklı bir seviye olsa bile) kullanılmaya devam eder
            return r["id"]
        _check_upgrade(upgrade)
        return c.execute("INSERT INTO products(item_name_id, upgrade) VALUES (?, ?)", (nid, upgrade)).lastrowid

    def item_names(self) -> list[dict]:
        rows = self.conn.execute("SELECT id, name FROM item_names ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def completion_list(self) -> list[str]:
        """Otomatik tamamlama önerileri: kayıtlı ürünler ('Shard +8') ve item adları."""
        out: list[str] = []
        seen = set()
        for p in self.products():
            for s in (p["display"], p["name"]):
                if s not in seen:
                    seen.add(s)
                    out.append(s)
        return sorted(out, key=lambda s: name_key(s))

    def products(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT p.id, p.upgrade, n.id AS name_id, n.name FROM products p "
            "JOIN item_names n ON n.id = p.item_name_id ORDER BY n.name COLLATE NOCASE, p.upgrade"
        ).fetchall()
        return [
            {"id": r["id"], "name_id": r["name_id"], "name": r["name"], "upgrade": r["upgrade"],
             "display": display_name(r["name"], r["upgrade"])}
            for r in rows
        ]

    def product(self, product_id: int) -> dict:
        r = self.conn.execute(
            "SELECT p.id, p.upgrade, n.id AS name_id, n.name FROM products p "
            "JOIN item_names n ON n.id = p.item_name_id WHERE p.id=?", (product_id,)
        ).fetchone()
        if not r:
            raise UserError("Item bulunamadı.")
        return {"id": r["id"], "name_id": r["name_id"], "name": r["name"], "upgrade": r["upgrade"],
                "display": display_name(r["name"], r["upgrade"])}

    def existing_name(self, name: str) -> str | None:
        """Aynı anahtarla kayıtlı isim varsa onun kayıtlı yazımını döner."""
        r = self.conn.execute("SELECT name FROM item_names WHERE name_key=?", (name_key(name),)).fetchone()
        return r["name"] if r else None

    def similar_names(self, name: str, limit: int = 3) -> list[str]:
        """Yazımı çok benzeyen (ama aynı olmayan) kayıtlı isimler — mükerrer kaydı önlemek için."""
        key = name_key(name)
        rows = self.conn.execute("SELECT name, name_key FROM item_names").fetchall()
        by_key = {r["name_key"]: r["name"] for r in rows}
        if key in by_key:
            return []
        squash = lambda s: re.sub(r"[\s\-_.'`]", "", s)  # noqa: E731
        sk = squash(key)
        exact_squash = [n for k, n in by_key.items() if squash(k) == sk]
        close = difflib.get_close_matches(key, list(by_key), n=limit, cutoff=0.8)
        out = exact_squash + [by_key[k] for k in close if by_key[k] not in exact_squash]
        return out[:limit]

    def rename_item(self, name_id: int, new_name: str) -> None:
        new_name = clean_name(new_name)
        key = name_key(new_name)
        with self.db.transaction() as c:
            r = c.execute("SELECT id FROM item_names WHERE name_key=? AND id<>?", (key, name_id)).fetchone()
            if r:
                raise UserError(f"'{new_name}' adında başka bir item zaten var.")
            cur = c.execute("UPDATE item_names SET name=?, name_key=? WHERE id=?", (new_name, key, name_id))
            if cur.rowcount != 1:
                raise UserError("Item bulunamadı.")

    # ------------------------------------------------------------------ #
    # Notlar
    # ------------------------------------------------------------------ #
    def _set_note(self, c: sqlite3.Connection, tx_id: int, note: str | None) -> None:
        note = (note or "").strip()
        if len(note) > 500:
            raise UserError("Not en fazla 500 karakter olabilir.")
        if note:
            c.execute(
                "INSERT INTO tx_notes(tx_id, text) VALUES (?, ?) "
                "ON CONFLICT(tx_id) DO UPDATE SET text=excluded.text", (tx_id, note)
            )
        else:
            c.execute("DELETE FROM tx_notes WHERE tx_id=?", (tx_id,))

    def _insert_tx(self, c, type_: str, tx_date, **fields) -> int:
        cols = ["type", "tx_date", "created_at"] + list(fields)
        vals = [type_, to_iso(tx_date), self._now()] + list(fields.values())
        q = f"INSERT INTO transactions({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        return c.execute(q, vals).lastrowid

    def _tx(self, tx_id: int, c=None) -> sqlite3.Row:
        r = (c or self.conn).execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if not r:
            raise UserError(f"#{tx_id} numaralı işlem bulunamadı.")
        return r

    # ------------------------------------------------------------------ #
    # Alış
    # ------------------------------------------------------------------ #
    def record_purchase(self, name: str, upgrade: int, qty: int, unit_price: int, tx_date, note: str = "") -> int:
        qty = _check_qty(qty)
        unit_price = _check_amount(unit_price, "Birim alış fiyatı")
        if unit_price * qty > MAX_NOAH:
            raise UserError("Toplam alış tutarı çok büyük.")

        def op(c):
            pid = self._get_or_create_product(c, name, upgrade)
            tid = self._insert_tx(c, "purchase", tx_date)
            c.execute("INSERT INTO lots(tx_id, product_id, qty, unit_price) VALUES (?, ?, ?, ?)",
                      (tid, pid, qty, unit_price))
            self._set_note(c, tid, note)
            return tid

        return self._write(op)

    def update_purchase(self, tx_id: int, name: str, upgrade: int, qty: int, unit_price: int, tx_date,
                        note: str = "") -> None:
        qty = _check_qty(qty)
        unit_price = _check_amount(unit_price, "Birim alış fiyatı")

        def op(c):
            tx = self._tx(tx_id, c)
            if tx["type"] != "purchase":
                raise UserError("Bu işlem bir alış değil.")
            lot = c.execute("SELECT * FROM lots WHERE tx_id=?", (tx_id,)).fetchone()
            used = c.execute("SELECT COALESCE(SUM(qty),0) FROM consumptions WHERE lot_id=?",
                             (lot["id"],)).fetchone()[0]
            pid = self._get_or_create_product(c, name, upgrade)
            if pid != lot["product_id"] and used:
                raise UserError("Bu alış partisinden satış/takas yapılmış; item adı veya upgrade "
                                "değiştirilemez. Önce bağlı işlemleri silin.")
            if qty < used:
                raise UserError(f"Bu partiden {used} adet satılmış/takas edilmiş; adet {used}'den az olamaz.")
            c.execute("UPDATE lots SET product_id=?, qty=?, unit_price=? WHERE id=?",
                      (pid, qty, unit_price, lot["id"]))
            c.execute("UPDATE transactions SET tx_date=? WHERE id=?", (to_iso(tx_date), tx_id))
            self._set_note(c, tx_id, note)

        self._write(op)

    # ------------------------------------------------------------------ #
    # Satış
    # ------------------------------------------------------------------ #
    def _norm_alloc(self, allocations) -> dict[int, int]:
        items = allocations.items() if isinstance(allocations, dict) else allocations
        out: dict[int, int] = defaultdict(int)
        for lot_id, q in items:
            q = int(q)
            if q < 0:
                raise UserError("Adet negatif olamaz.")
            if q:
                out[int(lot_id)] += q
        if not out:
            raise UserError("Satılacak adet seçilmedi.")
        return dict(out)

    def _insert_sale(self, c, product_id: int, alloc: dict[int, int], gross: int, method: str, tx_date,
                     note: str, tax_bps: int | None) -> int:
        if method not in METHOD_NAMES:
            raise UserError("Geçersiz satış yöntemi.")
        gross = _check_amount(gross, "Satış fiyatı")
        bps = self.tax_bps if tax_bps is None else int(tax_bps)
        if method != "market":
            bps = 0
        tax = sale_tax(gross, method, bps)
        for lot_id, q in alloc.items():
            lot = c.execute("SELECT * FROM lots WHERE id=?", (lot_id,)).fetchone()
            if not lot or lot["product_id"] != product_id:
                raise UserError("Seçilen parti bu iteme ait değil.")
            if q > lot["remaining"]:
                raise UserError(f"Parti #{lot_id} içinde yalnızca {lot['remaining']} adet var; {q} adet satılamaz.")
        tid = self._insert_tx(c, "sale", tx_date, sale_method=method, gross_amount=gross,
                              tax_bps=bps, tax_amount=tax)
        for lot_id, q in alloc.items():
            lot = c.execute("SELECT remaining FROM lots WHERE id=?", (lot_id,)).fetchone()
            lst = c.execute("SELECT qty, since FROM listings WHERE lot_id=?", (lot_id,)).fetchone()
            listed = lst["qty"] if lst else 0
            if method == "market":
                used = min(listed, q)  # pazar satışı önce satıştaki adetlerden düşer
            else:
                used = max(0, q - (lot["remaining"] - listed))  # trade önce stoktakilerden düşer
            c.execute("INSERT INTO consumptions(tx_id, lot_id, qty, listed_used, listed_since) VALUES (?,?,?,?,?)",
                      (tid, lot_id, q, used, lst["since"] if (lst and used) else None))
            if used:
                if listed - used > 0:
                    c.execute("UPDATE listings SET qty=? WHERE lot_id=?", (listed - used, lot_id))
                else:
                    c.execute("DELETE FROM listings WHERE lot_id=?", (lot_id,))
        self._set_note(c, tid, note)
        return tid

    def record_sale(self, product_id: int, allocations, gross: int, method: str, tx_date, note: str = "",
                    tax_bps: int | None = None) -> int:
        alloc = self._norm_alloc(allocations)
        return self._write(lambda c: self._insert_sale(c, product_id, alloc, gross, method, tx_date, note, tax_bps))

    def preview_sale(self, product_id: int, allocations, gross: int, method: str, tx_date,
                     tax_bps: int | None = None) -> dict:
        """Kaydetmeden önce satışın sonucunu gösterir (gerçek hesap motoruyla, sonra geri alınır)."""
        alloc = self._norm_alloc(allocations)
        with self.db.dry_run() as c:
            tid = self._insert_sale(c, product_id, alloc, gross, method, tx_date, "", tax_bps)
            ledger.rebuild(c)
            t = self._tx(tid, c)
            return {"gross": t["gross_amount"], "tax": t["tax_amount"], "tax_bps": t["tax_bps"],
                    "net": t["net_cash"], "cost": t["cost_basis"], "profit": t["realized_pl"],
                    "qty": sum(alloc.values())}

    def update_sale(self, tx_id: int, gross: int, method: str, tax_bps: int | None, tx_date, note: str = "") -> None:
        gross = _check_amount(gross, "Satış fiyatı")
        if method not in METHOD_NAMES:
            raise UserError("Geçersiz satış yöntemi.")

        def op(c):
            tx = self._tx(tx_id, c)
            if tx["type"] != "sale":
                raise UserError("Bu işlem bir satış değil.")
            bps = (tx["tax_bps"] if tax_bps is None else int(tax_bps)) if method == "market" else 0
            if bps < 0 or bps >= 10000:
                raise UserError("Vergi oranı %0 ile %100 arasında olmalıdır.")
            c.execute("UPDATE transactions SET gross_amount=?, sale_method=?, tax_bps=?, tax_amount=?, tx_date=? "
                      "WHERE id=?", (gross, method, bps, sale_tax(gross, method, bps), to_iso(tx_date), tx_id))
            self._set_note(c, tx_id, note)

        self._write(op)

    # ------------------------------------------------------------------ #
    # Takas
    # ------------------------------------------------------------------ #
    def _insert_trade(self, c, given, received, cash_out: int, cash_in: int, tx_date, note: str) -> int:
        cash_out = _check_amount(cash_out or 0, "Verilen GB")
        cash_in = _check_amount(cash_in or 0, "Alınan GB")
        given_alloc = self._norm_alloc(given) if given else {}
        rec = []
        for r in received or []:
            rec.append({
                "name": clean_name(r["name"]),
                "upgrade": int(r.get("upgrade", 0) or 0),
                "qty": _check_qty(r["qty"], "Alınan item adedi"),
                "agreed_value": _check_amount(r.get("agreed_value", 0) or 0, "Anlaşılan değer"),
            })
        if not given_alloc and not rec:
            raise UserError("Takasta en az bir verilen veya alınan item olmalıdır.")
        if not given_alloc and not cash_out:
            raise UserError("Takasta hiçbir şey verilmiyor. Verilen item veya GB ekleyin.")
        if not rec and not cash_in:
            raise UserError("Takasta hiçbir şey alınmıyor. Alınan item veya GB ekleyin.")
        for lot_id, q in given_alloc.items():
            lot = c.execute("SELECT remaining FROM lots WHERE id=?", (lot_id,)).fetchone()
            if not lot:
                raise UserError(f"Parti #{lot_id} bulunamadı.")
            if q > lot["remaining"]:
                raise UserError(f"Parti #{lot_id} içinde yalnızca {lot['remaining']} adet var.")
        tid = self._insert_tx(c, "trade", tx_date, cash_in=cash_in, cash_out=cash_out)
        for lot_id, q in given_alloc.items():
            lot = c.execute("SELECT remaining FROM lots WHERE id=?", (lot_id,)).fetchone()
            lst = c.execute("SELECT qty, since FROM listings WHERE lot_id=?", (lot_id,)).fetchone()
            listed = lst["qty"] if lst else 0
            used = max(0, q - (lot["remaining"] - listed))
            c.execute("INSERT INTO consumptions(tx_id, lot_id, qty, listed_used, listed_since) VALUES (?,?,?,?,?)",
                      (tid, lot_id, q, used, lst["since"] if (lst and used) else None))
            if used:
                if listed - used > 0:
                    c.execute("UPDATE listings SET qty=? WHERE lot_id=?", (listed - used, lot_id))
                else:
                    c.execute("DELETE FROM listings WHERE lot_id=?", (lot_id,))
        for r in rec:
            pid = self._get_or_create_product(c, r["name"], r["upgrade"])
            c.execute("INSERT INTO lots(tx_id, product_id, qty, agreed_value) VALUES (?, ?, ?, ?)",
                      (tid, pid, r["qty"], r["agreed_value"]))
        self._set_note(c, tid, note)
        return tid

    def record_trade(self, given, received, cash_out: int, cash_in: int, tx_date, note: str = "") -> int:
        return self._write(lambda c: self._insert_trade(c, given, received, cash_out, cash_in, tx_date, note))

    def preview_trade(self, given, received, cash_out: int, cash_in: int, tx_date) -> dict:
        with self.db.dry_run() as c:
            tid = self._insert_trade(c, given, received, cash_out, cash_in, tx_date, "")
            ledger.rebuild(c)
            t = self._tx(tid, c)
            lots = c.execute(
                "SELECT l.qty, l.agreed_value, l.total_cost, n.name, p.upgrade FROM lots l "
                "JOIN products p ON p.id=l.product_id JOIN item_names n ON n.id=p.item_name_id "
                "WHERE l.tx_id=? ORDER BY l.id", (tid,)).fetchall()
            basis = t["cost_basis"] + t["cash_out"] - t["cash_in"]
            return {
                "given_cost": t["cost_basis"],
                "cash_out": t["cash_out"],
                "cash_in": t["cash_in"],
                "basis": basis,
                "assigned_total": sum(r["total_cost"] for r in lots),
                "received": [{"display": display_name(r["name"], r["upgrade"]), "qty": r["qty"],
                              "agreed_value": r["agreed_value"], "cost": r["total_cost"],
                              "unit_cost": _round_div(r["total_cost"], r["qty"])} for r in lots],
                "realized": t["realized_pl"],
                "balance_effect": t["net_cash"],
            }

    def update_trade(self, tx_id: int, tx_date, note: str = "") -> None:
        def op(c):
            tx = self._tx(tx_id, c)
            if tx["type"] != "trade":
                raise UserError("Bu işlem bir takas değil.")
            c.execute("UPDATE transactions SET tx_date=? WHERE id=?", (to_iso(tx_date), tx_id))
            self._set_note(c, tx_id, note)

        self._write(op)

    # ------------------------------------------------------------------ #
    # GB ekleme / çıkarma
    # ------------------------------------------------------------------ #
    def record_cash(self, kind: str, amount: int, tx_date, note: str = "") -> int:
        if kind not in ("deposit", "withdraw"):
            raise UserError("Geçersiz bakiye işlemi.")
        amount = _check_amount(amount, "Miktar", allow_zero=False)

        def op(c):
            fields = {"cash_in": amount} if kind == "deposit" else {"cash_out": amount}
            tid = self._insert_tx(c, kind, tx_date, **fields)
            self._set_note(c, tid, note)
            return tid

        return self._write(op)

    def update_cash(self, tx_id: int, amount: int, tx_date, note: str = "") -> None:
        amount = _check_amount(amount, "Miktar", allow_zero=False)

        def op(c):
            tx = self._tx(tx_id, c)
            if tx["type"] == "deposit":
                c.execute("UPDATE transactions SET cash_in=?, tx_date=? WHERE id=?", (amount, to_iso(tx_date), tx_id))
            elif tx["type"] == "withdraw":
                c.execute("UPDATE transactions SET cash_out=?, tx_date=? WHERE id=?", (amount, to_iso(tx_date), tx_id))
            else:
                raise UserError("Bu işlem bir GB hareketi değil.")
            self._set_note(c, tx_id, note)

        self._write(op)

    # ------------------------------------------------------------------ #
    # Silme ve geri alma
    # ------------------------------------------------------------------ #
    def dependents(self, tx_id: int) -> list[int]:
        """Bu işlemle gelen partileri kullanan diğer işlemler."""
        rows = self.conn.execute(
            "SELECT DISTINCT c.tx_id FROM consumptions c JOIN lots l ON l.id=c.lot_id "
            "WHERE l.tx_id=? AND c.tx_id<>? ORDER BY c.tx_id", (tx_id, tx_id)).fetchall()
        return [r[0] for r in rows]

    def delete_transaction(self, tx_id: int) -> None:
        deps = self.dependents(tx_id)
        if deps:
            nums = ", ".join(f"#{d}" for d in deps)
            raise UserError(
                f"Bu işlemle gelen itemler daha sonra başka işlemlerde kullanılmış ({nums}). "
                f"Stok ve maliyetlerin bozulmaması için önce o işlemleri silmelisiniz."
            )

        def op(c):
            tx = self._tx(tx_id, c)
            restore = c.execute("SELECT lot_id, listed_used, listed_since FROM consumptions "
                                "WHERE tx_id=? AND listed_used>0", (tx_id,)).fetchall()
            try:
                c.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
            except sqlite3.IntegrityError:
                raise UserError("Bu işleme bağlı başka kayıtlar olduğu için silinemedi.") from None
            ledger.rebuild(c)
            # Silinen satışta pazardan düşülen adetler tekrar "Satışta" durumuna döner.
            for r in restore:
                lot = c.execute("SELECT remaining FROM lots WHERE id=?", (r["lot_id"],)).fetchone()
                if not lot:
                    continue
                cur = c.execute("SELECT qty, since FROM listings WHERE lot_id=?", (r["lot_id"],)).fetchone()
                new_qty = min((cur["qty"] if cur else 0) + r["listed_used"], lot["remaining"])
                since = cur["since"] if cur else (r["listed_since"] or tx["tx_date"])
                if new_qty > 0:
                    c.execute("INSERT INTO listings(lot_id, qty, since) VALUES (?,?,?) "
                              "ON CONFLICT(lot_id) DO UPDATE SET qty=excluded.qty, since=excluded.since",
                              (r["lot_id"], new_qty, since))

        self._write(op)

    def last_transaction(self) -> dict | None:
        r = self.conn.execute("SELECT id FROM transactions ORDER BY id DESC LIMIT 1").fetchone()
        return self.transaction_summary(r["id"]) if r else None

    def undo_last(self) -> dict:
        last = self.last_transaction()
        if not last:
            raise UserError("Geri alınacak işlem yok.")
        self.delete_transaction(last["id"])
        return last

    # ------------------------------------------------------------------ #
    # Satışa çıkarma (stok durumu)
    # ------------------------------------------------------------------ #
    def set_listing(self, lot_id: int, qty: int, since=None) -> None:
        qty = int(qty)
        with self.db.transaction() as c:
            lot = c.execute("SELECT remaining FROM lots WHERE id=?", (lot_id,)).fetchone()
            if not lot:
                raise UserError("Parti bulunamadı.")
            if qty < 0 or qty > lot["remaining"]:
                raise UserError(f"Satışa çıkarılacak adet 0 ile {lot['remaining']} arasında olmalıdır.")
            cur = c.execute("SELECT since FROM listings WHERE lot_id=?", (lot_id,)).fetchone()
            if qty == 0:
                c.execute("DELETE FROM listings WHERE lot_id=?", (lot_id,))
                return
            since_iso = to_iso(since) if since else (cur["since"] if cur else self.today_iso())
            c.execute("INSERT INTO listings(lot_id, qty, since) VALUES (?,?,?) "
                      "ON CONFLICT(lot_id) DO UPDATE SET qty=excluded.qty, since=excluded.since",
                      (lot_id, qty, since_iso))

    # ------------------------------------------------------------------ #
    # Sorgular
    # ------------------------------------------------------------------ #
    def balance(self) -> int:
        s = self.conn.execute("SELECT COALESCE(SUM(net_cash),0) FROM transactions").fetchone()[0]
        return self.initial_balance + s

    def _lot_rows(self, where: str = "", params: Iterable = ()) -> list[dict]:
        rows = self.conn.execute(
            "SELECT l.*, t.tx_date, t.type AS src_type, p.upgrade, n.name, n.id AS name_id, "
            "COALESCE(li.qty,0) AS listed, li.since AS listed_since, "
            "COALESCE((SELECT SUM(cost) FROM consumptions c WHERE c.lot_id=l.id),0) AS used_cost "
            "FROM lots l JOIN transactions t ON t.id=l.tx_id JOIN products p ON p.id=l.product_id "
            "JOIN item_names n ON n.id=p.item_name_id LEFT JOIN listings li ON li.lot_id=l.id "
            f"{where} ORDER BY t.tx_date, l.id", tuple(params)).fetchall()
        today = self.today_iso()
        out = []
        for r in rows:
            d = dict(r)
            d["display"] = display_name(r["name"], r["upgrade"])
            d["remaining_cost"] = r["total_cost"] - r["used_cost"]
            d["unit_cost"] = _round_div(r["total_cost"], r["qty"])
            d["source"] = "Alış" if r["src_type"] == "purchase" else "Takas"
            d["days_held"] = days_between(r["tx_date"], today)
            d["days_listed"] = days_between(r["listed_since"], today) if r["listed_since"] else None
            d["in_stock"] = r["remaining"] - d["listed"]
            out.append(d)
        return out

    def lots_for_product(self, product_id: int, only_available: bool = False) -> list[dict]:
        where = "WHERE l.product_id=?" + (" AND l.remaining>0" if only_available else "")
        return self._lot_rows(where, (product_id,))

    def available_lots(self) -> list[dict]:
        return self._lot_rows("WHERE l.remaining>0")

    def products_in_stock(self) -> list[dict]:
        agg: dict[int, dict] = {}
        for lot in self.available_lots():
            a = agg.setdefault(lot["product_id"], {"id": lot["product_id"], "display": lot["display"],
                                                   "remaining": 0, "listed": 0})
            a["remaining"] += lot["remaining"]
            a["listed"] += lot["listed"]
        return sorted(agg.values(), key=lambda a: name_key(a["display"]))

    def stock_overview(self, include_sold: bool = False, search: str = "") -> list[dict]:
        today = self.today_iso()
        agg: dict[int, dict] = {}
        for lot in self._lot_rows():
            a = agg.setdefault(lot["product_id"], {
                "product_id": lot["product_id"], "name_id": lot["name_id"], "display": lot["display"],
                "acquired": 0, "remaining": 0, "listed": 0, "remaining_cost": 0,
                "oldest": None, "listed_since": None, "lot_count": 0,
            })
            a["acquired"] += lot["qty"]
            a["remaining"] += lot["remaining"]
            a["listed"] += lot["listed"]
            a["remaining_cost"] += lot["remaining_cost"]
            if lot["remaining"] > 0:
                a["lot_count"] += 1
                if a["oldest"] is None or lot["tx_date"] < a["oldest"]:
                    a["oldest"] = lot["tx_date"]
            if lot["listed_since"] and (a["listed_since"] is None or lot["listed_since"] < a["listed_since"]):
                a["listed_since"] = lot["listed_since"]
        key = name_key(search) if search else ""
        out = []
        for a in agg.values():
            if not include_sold and a["remaining"] <= 0:
                continue
            if key and key not in name_key(a["display"]):
                continue
            a["in_stock"] = a["remaining"] - a["listed"]
            a["avg_cost"] = _round_div(a["remaining_cost"], a["remaining"]) if a["remaining"] else 0
            if a["remaining"] <= 0:
                a["status"] = "Satıldı"
            elif a["listed"] >= a["remaining"]:
                a["status"] = "Satışta"
            elif a["listed"] > 0:
                a["status"] = "Kısmen satışta"
            else:
                a["status"] = "Stokta"
            a["days_held"] = days_between(a["oldest"], today) if a["oldest"] else None
            a["days_listed"] = days_between(a["listed_since"], today) if a["listed_since"] else None
            out.append(a)
        return sorted(out, key=lambda a: name_key(a["display"]))

    def product_history(self, product_id: int) -> dict:
        lots = self.lots_for_product(product_id)
        buys = [{"tx_id": l["tx_id"], "date": l["tx_date"], "source": l["source"], "qty": l["qty"],
                 "unit": l["unit_cost"], "total": l["total_cost"]} for l in lots]
        rows = self.conn.execute(
            "SELECT t.id, t.type, t.tx_date, t.sale_method, t.gross_amount, t.tax_amount, t.net_cash, "
            "t.realized_pl, SUM(c.qty) AS qty, SUM(c.cost) AS cost FROM consumptions c "
            "JOIN lots l ON l.id=c.lot_id JOIN transactions t ON t.id=c.tx_id "
            "WHERE l.product_id=? GROUP BY t.id ORDER BY t.tx_date, t.id", (product_id,)).fetchall()
        sells = []
        for r in rows:
            is_sale = r["type"] == "sale"
            sells.append({
                "tx_id": r["id"], "date": r["tx_date"], "type": r["type"],
                "kind": f"Satış ({METHOD_NAMES.get(r['sale_method'], '')})" if is_sale else "Takasta verildi",
                "qty": r["qty"], "cost": r["cost"],
                "gross": r["gross_amount"] if is_sale else None,
                "unit": _round_div(r["gross_amount"], r["qty"]) if is_sale else None,
                "net": r["net_cash"] if is_sale else None,
                "profit": r["realized_pl"] if is_sale else None,
            })
        sale_rows = [s for s in sells if s["type"] == "sale"]
        tot_q = sum(b["qty"] for b in buys)
        sold_q = sum(s["qty"] for s in sale_rows)
        return {
            "product": self.product(product_id),
            "buys": buys,
            "sells": sells,
            "avg_buy": _round_div(sum(b["total"] for b in buys), tot_q) if tot_q else None,
            "avg_sell": _round_div(sum(s["gross"] for s in sale_rows), sold_q) if sold_q else None,
            "realized": sum(s["profit"] for s in sale_rows),
            "sold_qty": sold_q,
            "profit_total": sum(s["profit"] for s in sale_rows if s["profit"] > 0),
            "loss_total": -sum(s["profit"] for s in sale_rows if s["profit"] < 0),
        }

    # --- işlem listesi ------------------------------------------------- #
    def _tx_lines(self, tx_ids: list[int] | None = None) -> tuple[dict, dict]:
        lots_q = ("SELECT l.tx_id, l.qty, p.upgrade, n.name FROM lots l JOIN products p ON p.id=l.product_id "
                  "JOIN item_names n ON n.id=p.item_name_id")
        cons_q = ("SELECT c.tx_id, c.qty, p.upgrade, n.name FROM consumptions c JOIN lots l ON l.id=c.lot_id "
                  "JOIN products p ON p.id=l.product_id JOIN item_names n ON n.id=p.item_name_id")
        params: tuple = ()
        if tx_ids is not None:
            ph = ",".join("?" * len(tx_ids)) or "NULL"
            lots_q += f" WHERE l.tx_id IN ({ph})"
            cons_q += f" WHERE c.tx_id IN ({ph})"
            params = tuple(tx_ids)
        lots_by: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        cons_by: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in self.conn.execute(lots_q + " ORDER BY l.id", params):
            lots_by[r["tx_id"]][display_name(r["name"], r["upgrade"])] += r["qty"]
        for r in self.conn.execute(cons_q + " ORDER BY c.id", params):
            cons_by[r["tx_id"]][display_name(r["name"], r["upgrade"])] += r["qty"]
        return lots_by, cons_by

    @staticmethod
    def _items_text(d: dict[str, int]) -> str:
        return ", ".join(f"{k} ×{v}" for k, v in d.items())

    def _summarize(self, t, lots_by, cons_by, note: str | None) -> dict:
        typ = t["type"]
        got, gave = lots_by.get(t["id"], {}), cons_by.get(t["id"], {})
        if typ == "purchase":
            items, qty, amount = self._items_text(got), sum(got.values()), t["cost_basis"]
        elif typ == "sale":
            items, qty, amount = self._items_text(gave), sum(gave.values()), t["gross_amount"]
        elif typ == "trade":
            parts = []
            if gave:
                parts.append("Verilen: " + self._items_text(gave))
            if t["cash_out"]:
                parts.append("Verilen GB")
            if got:
                parts.append("Alınan: " + self._items_text(got))
            if t["cash_in"]:
                parts.append("Alınan GB")
            items, qty, amount = " · ".join(parts), sum(gave.values()) + sum(got.values()), t["net_cash"]
        else:
            items, qty, amount = "—", None, t["cash_in"] or t["cash_out"]
        type_name = TYPE_NAMES[typ]
        if typ == "sale":
            type_name += f" ({METHOD_NAMES.get(t['sale_method'], '')})"
        return {
            "id": t["id"], "date": t["tx_date"], "type": typ, "type_name": type_name,
            "items": items, "qty": qty, "amount": amount, "net_cash": t["net_cash"],
            "realized": t["realized_pl"] if typ in ("sale", "trade") else None,
            "note": note or "", "method": t["sale_method"], "created_at": t["created_at"],
            "item_names": list(got) + list(gave),
        }

    def transaction_summary(self, tx_id: int) -> dict:
        t = self._tx(tx_id)
        lots_by, cons_by = self._tx_lines([tx_id])
        n = self.conn.execute("SELECT text FROM tx_notes WHERE tx_id=?", (tx_id,)).fetchone()
        return self._summarize(t, lots_by, cons_by, n["text"] if n else "")

    def list_transactions(self, search: str = "", types: Iterable[str] | None = None,
                          date_from=None, date_to=None, sort: str = "date_desc", limit: int | None = None) -> list[dict]:
        where, params = [], []
        if types:
            types = list(types)
            where.append(f"t.type IN ({','.join('?' * len(types))})")
            params += types
        if date_from:
            where.append("t.tx_date >= ?")
            params.append(to_iso(date_from))
        if date_to:
            where.append("t.tx_date <= ?")
            params.append(to_iso(date_to))
        q = ("SELECT t.*, n.text AS note FROM transactions t LEFT JOIN tx_notes n ON n.tx_id=t.id "
             + ("WHERE " + " AND ".join(where) if where else ""))
        rows = self.conn.execute(q, params).fetchall()
        ids = [r["id"] for r in rows]
        lots_by, cons_by = self._tx_lines(ids if len(ids) < 900 else None)
        out = [self._summarize(r, lots_by, cons_by, r["note"]) for r in rows]
        if search:
            k = name_key(search)
            out = [o for o in out if any(k in name_key(n) for n in o["item_names"]) or k in name_key(o["note"])]
        if sort == "profit_desc":
            out.sort(key=lambda o: (o["realized"] is None, -(o["realized"] or 0), -o["id"]))
        elif sort == "profit_asc":
            out.sort(key=lambda o: (o["realized"] is None, (o["realized"] or 0), -o["id"]))
        elif sort == "date_asc":
            out.sort(key=lambda o: (o["date"], o["id"]))
        else:
            out.sort(key=lambda o: (o["date"], o["id"]), reverse=True)
        return out[:limit] if limit else out

    def transaction_detail(self, tx_id: int) -> dict:
        t = self._tx(tx_id)
        summary = self.transaction_summary(tx_id)
        lots = self.conn.execute(
            "SELECT l.*, p.upgrade, n.name FROM lots l JOIN products p ON p.id=l.product_id "
            "JOIN item_names n ON n.id=p.item_name_id WHERE l.tx_id=? ORDER BY l.id", (tx_id,)).fetchall()
        cons = self.conn.execute(
            "SELECT c.*, l.tx_id AS lot_tx, l.qty AS lot_qty, t2.tx_date AS lot_date, p.upgrade, n.name "
            "FROM consumptions c JOIN lots l ON l.id=c.lot_id JOIN transactions t2 ON t2.id=l.tx_id "
            "JOIN products p ON p.id=l.product_id JOIN item_names n ON n.id=p.item_name_id "
            "WHERE c.tx_id=? ORDER BY c.id", (tx_id,)).fetchall()
        return {
            "tx": dict(t),
            "summary": summary,
            "lots": [dict(r, display=display_name(r["name"], r["upgrade"]),
                          unit_cost=_round_div(r["total_cost"], r["qty"])) for r in lots],
            "consumptions": [dict(r, display=display_name(r["name"], r["upgrade"]),
                                  days=days_between(r["lot_date"], t["tx_date"])) for r in cons],
            "dependents": self.dependents(tx_id),
        }

    # --- dönemler / istatistikler ------------------------------------- #
    def period_range(self, period: str) -> tuple[str | None, str | None]:
        today = self.today()
        if period == "today":
            return today.isoformat(), today.isoformat()
        if period == "week":
            start = today - timedelta(days=today.weekday())
            return start.isoformat(), today.isoformat()
        if period == "month":
            return today.replace(day=1).isoformat(), today.isoformat()
        return None, None

    def _period_where(self, period: str, alias: str = "t") -> tuple[str, list]:
        a, b = self.period_range(period)
        if a is None:
            return "1=1", []
        return f"{alias}.tx_date BETWEEN ? AND ?", [a, b]

    def snapshot(self) -> dict:
        c = self.conn
        units = c.execute("SELECT COALESCE(SUM(remaining),0) FROM lots").fetchone()[0]
        listed = c.execute("SELECT COALESCE(SUM(qty),0) FROM listings").fetchone()[0]
        cost = (c.execute("SELECT COALESCE(SUM(total_cost),0) FROM lots").fetchone()[0]
                - c.execute("SELECT COALESCE(SUM(cost),0) FROM consumptions").fetchone()[0])
        kinds = c.execute("SELECT COUNT(DISTINCT product_id) FROM lots WHERE remaining>0").fetchone()[0]
        return {"balance": self.balance(), "stock_units": units, "listed_units": listed,
                "stock_cost": cost, "stock_kinds": kinds}

    def period_totals(self, period: str) -> dict:
        w, p = self._period_where(period)
        c = self.conn

        def one(sql, extra=()):
            return c.execute(sql + f" AND {w}", list(extra) + p).fetchone()[0] or 0

        sold_units = c.execute(
            f"SELECT COALESCE(SUM(c.qty),0) FROM consumptions c JOIN transactions t ON t.id=c.tx_id "
            f"WHERE t.type='sale' AND {w}", p).fetchone()[0]
        profit = one("SELECT SUM(realized_pl) FROM transactions t WHERE realized_pl>0 AND type IN ('sale','trade')")
        loss = -one("SELECT SUM(realized_pl) FROM transactions t WHERE realized_pl<0 AND type IN ('sale','trade')")
        return {
            "purchase_total": one("SELECT SUM(cost_basis) FROM transactions t WHERE type='purchase'"),
            "purchase_count": one("SELECT COUNT(*) FROM transactions t WHERE type='purchase'"),
            "sales_gross": one("SELECT SUM(gross_amount) FROM transactions t WHERE type='sale'"),
            "sales_net": one("SELECT SUM(net_cash) FROM transactions t WHERE type='sale'"),
            "tax_total": one("SELECT SUM(tax_amount) FROM transactions t WHERE type='sale'"),
            "sale_count": one("SELECT COUNT(*) FROM transactions t WHERE type='sale'"),
            "trade_count": one("SELECT COUNT(*) FROM transactions t WHERE type='trade'"),
            "sold_units": sold_units,
            "profit": profit,
            "loss": loss,
            "net_profit": profit - loss,
        }

    def dashboard(self, period: str) -> dict:
        d = self.snapshot()
        d.update(self.period_totals(period))
        d["recent_purchases"] = self.list_transactions(types=["purchase"], limit=8)
        d["recent_sales"] = self.list_transactions(types=["sale"], limit=8)
        return d

    def statistics(self, period: str) -> dict:
        d = self.period_totals(period)
        w, p = self._period_where(period)
        # Satış -> ürün (bir satış tek bir ürüne aittir)
        rows = self.conn.execute(
            f"SELECT t.id, t.realized_pl, t.gross_amount, l.product_id, SUM(c.qty) AS qty "
            f"FROM transactions t JOIN consumptions c ON c.tx_id=t.id JOIN lots l ON l.id=c.lot_id "
            f"WHERE t.type='sale' AND {w} GROUP BY t.id", p).fetchall()
        per: dict[int, dict] = {}
        for r in rows:
            a = per.setdefault(r["product_id"], {"product_id": r["product_id"], "realized": 0, "qty": 0,
                                                 "gross": 0, "count": 0})
            a["realized"] += r["realized_pl"]
            a["qty"] += r["qty"]
            a["gross"] += r["gross_amount"]
            a["count"] += 1
        names = {pr["id"]: pr["display"] for pr in self.products()}
        for a in per.values():
            a["display"] = names.get(a["product_id"], "?")
        items = list(per.values())
        d["top_profit"] = sorted([a for a in items if a["realized"] > 0], key=lambda a: -a["realized"])[:10]
        d["top_loss"] = sorted([a for a in items if a["realized"] < 0], key=lambda a: a["realized"])[:10]
        # Ortalama satış süresi (alış -> satış, adet ağırlıklı)
        dur = self.conn.execute(
            f"SELECT c.qty, t.tx_date AS sdate, t2.tx_date AS bdate FROM consumptions c "
            f"JOIN transactions t ON t.id=c.tx_id JOIN lots l ON l.id=c.lot_id "
            f"JOIN transactions t2 ON t2.id=l.tx_id WHERE t.type='sale' AND {w}", p).fetchall()
        tq = sum(r["qty"] for r in dur)
        d["avg_days_to_sell"] = (
            (Decimal(sum(r["qty"] * days_between(r["bdate"], r["sdate"]) for r in dur)) / tq)
            .quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if tq else None)
        d["trade_realized"] = self.conn.execute(
            f"SELECT COALESCE(SUM(realized_pl),0) FROM transactions t WHERE type='trade' AND {w}", p).fetchone()[0]
        d["chart"] = self.profit_chart(period)
        return d

    def profit_chart(self, period: str) -> list[tuple[str, int]]:
        """Kâr-zarar grafiği: hafta/ay için günlük, tüm zamanlar için aylık."""
        today = self.today()
        if period in ("today", "week"):
            start = today - timedelta(days=today.weekday())
            days = [start + timedelta(days=i) for i in range(7)]
        elif period == "month":
            start = today.replace(day=1)
            days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
        else:
            days = None
        rows = self.conn.execute(
            "SELECT tx_date, SUM(realized_pl) AS pl FROM transactions WHERE type IN ('sale','trade') "
            "GROUP BY tx_date").fetchall()
        by_day = {r["tx_date"]: r["pl"] for r in rows}
        if days is not None:
            return [(f"{d.day:02d}.{d.month:02d}", by_day.get(d.isoformat(), 0)) for d in days]
        by_month: dict[str, int] = defaultdict(int)
        for k, v in by_day.items():
            by_month[k[:7]] += v
        if not by_month:
            return [(f"{today.month:02d}.{today.year}", 0)]
        first = min(by_month)
        y, m = int(first[:4]), int(first[5:7])
        out = []
        while (y, m) <= (today.year, today.month):
            key = f"{y:04d}-{m:02d}"
            out.append((f"{m:02d}.{y}", by_month.get(key, 0)))
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return out[-24:]

    # ------------------------------------------------------------------ #
    # Hesaplama araçları (kayıt oluşturmaz)
    # ------------------------------------------------------------------ #
    def calc_target_price(self, cost: int, target_profit: int, method: str) -> dict:
        _check_amount(cost, "Alış fiyatı")
        _check_amount(target_profit, "Hedef kâr")
        bps = self.tax_bps
        price = min_sale_price(cost, target_profit, method, bps)
        return {"price": price, **evaluate_offer(cost, price, method, bps), "bps": bps}

    def calc_offer(self, cost: int, offer: int, method: str) -> dict:
        _check_amount(cost, "Maliyet")
        _check_amount(offer, "Teklif")
        return {**evaluate_offer(cost, offer, method, self.tax_bps), "bps": self.tax_bps}

    # ------------------------------------------------------------------ #
    # Bilgi
    # ------------------------------------------------------------------ #
    def db_info(self) -> dict:
        c = self.conn
        counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("transactions", "lots", "item_names", "products")}
        size = self.db.path.stat().st_size if self.db.path.exists() else 0
        return {"path": str(self.db.path), "size": size, **counts}

    def integrity_ok(self) -> bool:
        return self.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    def recompute(self) -> None:
        """Bütün hesapları baştan kurar (bakım amaçlı)."""
        try:
            with self.db.transaction() as c:
                ledger.rebuild(c)
        except LedgerError:
            raise
