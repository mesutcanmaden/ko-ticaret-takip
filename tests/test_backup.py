import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core import backup
from app.core.db import Database
from app.core.errors import UserError
from app.core.service import TradeService
from tests.conftest import GB


def test_backup_and_restore_roundtrip(svc, tmp_path):
    svc.set_initial_balance(10 * GB)
    svc.record_purchase("A", 0, 1, 3 * GB, "2026-11-01")
    p = backup.make_backup(svc)
    assert p.exists() and p.name.startswith("yedek_")
    backup.validate_backup(p)
    # yedekten sonra değişiklik
    svc.record_purchase("B", 0, 1, 4 * GB, "2026-11-02")
    assert svc.balance() == 3 * GB
    safety = backup.restore_backup(svc, p)
    assert safety.exists() and safety.name.startswith("geri_yukleme_oncesi_")
    assert svc.balance() == 7 * GB
    assert [x["name"] for x in svc.products()] == ["A"]
    # yedek klasörü ayarı korunur
    assert svc.get_setting("backup_dir") == str(tmp_path / "yedek")
    # güvenlik yedeğiyle geri dönüş mümkün
    backup.restore_backup(svc, safety)
    assert svc.balance() == 3 * GB


def test_keep_last_10(svc):
    folder = backup.backup_dir(svc)
    for i in range(13):
        (folder / f"yedek_2026-01-{i + 1:02d}_00-00-00.db").write_bytes(b"x")
    backup.make_backup(svc)
    files = backup.list_backups(folder, backup.PREFIX)
    assert len(files) == 10
    assert all("2026-01-01" not in f.name for f in files)


def test_auto_backup_interval(svc):
    assert backup.auto_backup_due(svc)
    assert backup.maybe_auto_backup(svc) is not None
    assert backup.maybe_auto_backup(svc) is None  # hemen tekrar alınmaz
    later = datetime.now() + timedelta(days=3, minutes=1)
    assert backup.auto_backup_due(svc, later)
    assert backup.maybe_auto_backup(svc, later) is not None


def test_backup_failure_raises_user_error(svc, tmp_path):
    bad = tmp_path / "dosya.txt"
    bad.write_text("x")
    with pytest.raises(UserError):
        backup.make_backup(svc, folder=bad)  # klasör değil


def test_restore_rejects_foreign_files(svc, tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database at all" * 100)
    with pytest.raises(UserError):
        backup.restore_backup(svc, junk)
    other = tmp_path / "other.db"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE x(a)")
    con.commit()
    con.close()
    with pytest.raises(UserError):
        backup.restore_backup(svc, other)
    with pytest.raises(UserError):
        backup.restore_backup(svc, tmp_path / "yok.db")


def test_persistence_and_crash_safety(tmp_path):
    path = tmp_path / "kalici.db"
    db = Database(path)
    s = TradeService(db)
    s.record_purchase("A", 0, 1, GB, "2026-11-01")
    # yarım kalan (commit edilmemiş) işlem: program çöktü gibi bağlantı kapanır
    db.conn.execute("BEGIN")
    db.conn.execute("INSERT INTO transactions(type, tx_date, created_at, cash_in) VALUES "
                    "('deposit','2026-11-01','x',5)")
    db.conn.close()
    db2 = Database(path)
    s2 = TradeService(db2)
    assert len(s2.list_transactions()) == 1
    assert s2.balance() == -GB
    db2.close()


def test_data_dir_created(tmp_path, monkeypatch):
    from app.core import paths
    monkeypatch.setenv("KO_TICARET_DATA_DIR", str(tmp_path / "yeni" / "klasor"))
    assert paths.db_path().parent.exists()
    assert paths.default_backup_dir().exists()
    assert isinstance(paths.resource_path("assets"), Path)
