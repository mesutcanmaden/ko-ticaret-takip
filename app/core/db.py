"""SQLite bağlantısı, şema ve transaction yönetimi."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

# Tablolar:
#   settings       : ayarlar (anahtar/değer)
#   item_names     : item adları (yeniden adlandırılabilir; bağlantılar id üzerinden)
#   products       : ürün = item adı + upgrade seviyesi
#   transactions   : bütün işlemler (alış, satış, takas, GB ekleme/çıkarma)
#   tx_notes       : işlem notları
#   lots           : alış partileri (alıştan veya takastan gelen)
#   consumptions   : satış/takasta hangi partiden kaç adet kullanıldığı (satış-parti eşleştirmesi)
#   listings       : stok durumu - bir partinin kaç adedi pazarda satışta
#
# "Türetilmiş" (derived) sütunlar: lots.total_cost, lots.remaining, consumptions.cost,
# transactions.net_cash / cost_basis / realized_pl. Bunlar her yazma işleminden sonra
# ledger.rebuild() ile kaynak verilerden YENİDEN hesaplanır; böylece düzenleme/silme
# sonrasında tutarsızlık oluşamaz.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item_names (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    name_key   TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY,
    item_name_id INTEGER NOT NULL REFERENCES item_names(id) ON DELETE RESTRICT,
    upgrade      INTEGER NOT NULL DEFAULT 0 CHECK (upgrade >= 0),
    UNIQUE (item_name_id, upgrade)
);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY,
    type         TEXT NOT NULL CHECK (type IN ('purchase','sale','trade','deposit','withdraw')),
    tx_date      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    sale_method  TEXT CHECK (sale_method IN ('market','trade')),
    gross_amount INTEGER NOT NULL DEFAULT 0 CHECK (gross_amount >= 0),
    tax_bps      INTEGER NOT NULL DEFAULT 0 CHECK (tax_bps >= 0 AND tax_bps < 10000),
    tax_amount   INTEGER NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    cash_in      INTEGER NOT NULL DEFAULT 0 CHECK (cash_in >= 0),
    cash_out     INTEGER NOT NULL DEFAULT 0 CHECK (cash_out >= 0),
    net_cash     INTEGER NOT NULL DEFAULT 0,
    cost_basis   INTEGER NOT NULL DEFAULT 0,
    realized_pl  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_tx_date ON transactions (tx_date, id);

CREATE TABLE IF NOT EXISTS tx_notes (
    tx_id INTEGER PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
    text  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lots (
    id           INTEGER PRIMARY KEY,
    tx_id        INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    qty          INTEGER NOT NULL CHECK (qty > 0),
    unit_price   INTEGER CHECK (unit_price >= 0),
    agreed_value INTEGER CHECK (agreed_value >= 0),
    total_cost   INTEGER NOT NULL DEFAULT 0,
    remaining    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_lots_tx ON lots (tx_id);
CREATE INDEX IF NOT EXISTS ix_lots_product ON lots (product_id);

CREATE TABLE IF NOT EXISTS consumptions (
    id           INTEGER PRIMARY KEY,
    tx_id        INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    lot_id       INTEGER NOT NULL REFERENCES lots(id) ON DELETE RESTRICT,
    qty          INTEGER NOT NULL CHECK (qty > 0),
    listed_used  INTEGER NOT NULL DEFAULT 0 CHECK (listed_used >= 0),
    listed_since TEXT,
    cost         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_cons_tx ON consumptions (tx_id);
CREATE INDEX IF NOT EXISTS ix_cons_lot ON consumptions (lot_id);

CREATE TABLE IF NOT EXISTS listings (
    lot_id INTEGER PRIMARY KEY REFERENCES lots(id) ON DELETE CASCADE,
    qty    INTEGER NOT NULL CHECK (qty > 0),
    since  TEXT NOT NULL
);
"""

REQUIRED_TABLES = {
    "settings", "item_names", "products", "transactions",
    "tx_notes", "lots", "consumptions", "listings",
}


def configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA journal_mode = DELETE")


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = self._open()
        self.migrate()

    def _open(self) -> sqlite3.Connection:
        # isolation_level=None: transaction'ları kendimiz BEGIN/COMMIT ile yönetiriz.
        conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=10)
        configure(conn)
        return conn

    def reopen(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
        self.conn = self._open()
        self.migrate()

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                "Bu veritabanı programın daha yeni bir sürümüyle oluşturulmuş. "
                "Lütfen programın güncel sürümünü kullanın."
            )
        if version < 1:
            self.conn.executescript("BEGIN;" + SCHEMA_SQL + f"PRAGMA user_version = {SCHEMA_VERSION};COMMIT;")
        # İleride yeni sürümler: if version < 2: ...

    @contextmanager
    def transaction(self):
        """Atomik işlem: ya hepsi kaydedilir ya hiçbiri. İç içe kullanımda SAVEPOINT kullanılır."""
        conn = self.conn
        if conn.in_transaction:
            conn.execute("SAVEPOINT sp")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK TO sp")
                conn.execute("RELEASE sp")
                raise
            else:
                conn.execute("RELEASE sp")
        else:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    @contextmanager
    def dry_run(self):
        """Önizleme: işlemi gerçekten yapar, sonuçları okutur, sonra HER ZAMAN geri alır."""
        conn = self.conn
        if conn.in_transaction:
            raise RuntimeError("dry_run iç içe kullanılamaz")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        finally:
            conn.execute("ROLLBACK")
