"""Yedekleme ve geri yükleme.

* Yedekler SQLite'ın çevrimiçi yedekleme API'siyle alınır: program açıkken bile tutarlı kopya.
* Dosya adı: yedek_YYYY-AA-GG_SS-DD-ss.db
* Son 10 yedek saklanır, eskileri silinir.
* Son başarılı yedekten 3 gün geçtiyse açılışta otomatik yedek alınır.
* Geri yüklemeden önce mevcut veriler 'geri_yukleme_oncesi_...' adıyla yedeklenir.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import ledger
from .db import REQUIRED_TABLES, SCHEMA_VERSION, configure
from .errors import UserError
from .paths import default_backup_dir
from .service import TradeService

PREFIX = "yedek_"
SAFETY_PREFIX = "geri_yukleme_oncesi_"
KEEP = 10
AUTO_INTERVAL = timedelta(days=3)


def backup_dir(service: TradeService) -> Path:
    p = service.get_setting("backup_dir")
    path = Path(p) if p else default_backup_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _unique_name(folder: Path, prefix: str, now: datetime) -> Path:
    base = f"{prefix}{now.strftime('%Y-%m-%d_%H-%M-%S')}"
    p = folder / f"{base}.db"
    i = 2
    while p.exists():
        p = folder / f"{base}_{i}.db"
        i += 1
    return p


def _copy_db(src: sqlite3.Connection, dest_path: Path) -> None:
    tmp = dest_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    dest = sqlite3.connect(str(tmp))
    try:
        src.backup(dest)
        ok = dest.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise UserError("Yedek dosyası doğrulanamadı.")
    finally:
        dest.close()
    tmp.replace(dest_path)


def list_backups(folder: Path, prefix: str | None = None) -> list[Path]:
    if not folder.exists():
        return []
    pats = [prefix] if prefix else [PREFIX, SAFETY_PREFIX]
    files = [f for f in folder.glob("*.db") if any(f.name.startswith(pp) for pp in pats)]
    return sorted(files, key=lambda f: f.name, reverse=True)


def cleanup(folder: Path, prefix: str = PREFIX, keep: int = KEEP) -> list[Path]:
    removed = []
    for f in list_backups(folder, prefix)[keep:]:
        try:
            f.unlink()
            removed.append(f)
        except OSError:
            pass
    return removed


def make_backup(service: TradeService, prefix: str = PREFIX, folder: Path | None = None) -> Path:
    folder = folder or backup_dir(service)
    now = datetime.now()
    path = _unique_name(folder, prefix, now)
    try:
        _copy_db(service.conn, path)
    except (OSError, sqlite3.Error) as e:
        raise UserError(f"Yedek alınamadı: {e}") from e
    if prefix == PREFIX:
        service.set_setting("last_backup_at", now.isoformat(timespec="seconds"))
    cleanup(folder, prefix)
    return path


def last_backup_at(service: TradeService) -> datetime | None:
    v = service.get_setting("last_backup_at")
    try:
        return datetime.fromisoformat(v) if v else None
    except ValueError:
        return None


def auto_backup_due(service: TradeService, now: datetime | None = None) -> bool:
    last = last_backup_at(service)
    now = now or datetime.now()
    return last is None or now - last >= AUTO_INTERVAL


def maybe_auto_backup(service: TradeService, now: datetime | None = None) -> Path | None:
    """Gerekiyorsa otomatik yedek alır. Hata olursa UserError fırlatır (program çalışmaya devam eder)."""
    if auto_backup_due(service, now):
        return make_backup(service)
    return None


def validate_backup(path: Path) -> None:
    if not path.exists():
        raise UserError("Yedek dosyası bulunamadı.")
    try:
        con = sqlite3.connect(str(path))
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise UserError("Yedek dosyası bozuk.")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED_TABLES <= tables:
                raise UserError("Seçilen dosya bu programa ait bir yedek değil.")
            v = con.execute("PRAGMA user_version").fetchone()[0]
            if v > SCHEMA_VERSION:
                raise UserError("Bu yedek programın daha yeni bir sürümüyle alınmış.")
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        raise UserError(f"Seçilen dosya geçerli bir veritabanı değil: {e}") from e


def restore_backup(service: TradeService, path: Path) -> Path:
    """Yedeği geri yükler. Önce mevcut verilerin güvenlik yedeğini alır. Güvenlik yedeğinin yolunu döner."""
    path = Path(path)
    validate_backup(path)
    keep_dir = service.get_setting("backup_dir")
    folder = backup_dir(service)
    safety = make_backup(service, SAFETY_PREFIX, folder)
    src = sqlite3.connect(str(path))
    try:
        src.backup(service.conn)
    except sqlite3.Error as e:
        raise UserError(f"Geri yükleme başarısız: {e}. Güvenlik yedeği: {safety.name}") from e
    finally:
        src.close()
    service.db.reopen()
    configure(service.conn)
    # Yedekleme klasörü ayarı makineye özgüdür; geri yüklenen veride ezilmesin.
    if keep_dir:
        service.set_setting("backup_dir", keep_dir)
    service.set_setting("last_backup_at", datetime.now().isoformat(timespec="seconds"))
    service._ensure_defaults()
    with service.db.transaction() as c:
        ledger.rebuild(c)
    return safety
