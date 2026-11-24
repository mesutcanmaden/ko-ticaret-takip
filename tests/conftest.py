import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import Database  # noqa: E402
from app.core.service import TradeService  # noqa: E402

GB = 100_000_000
M = 1_000_000


class Clock:
    def __init__(self, d=date(2026, 11, 7)):
        self.d = d

    def __call__(self):
        return self.d


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def svc(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("KO_TICARET_DATA_DIR", str(tmp_path / "data"))
    db = Database(tmp_path / "test.db")
    s = TradeService(db, today=clock)
    s.set_setting("backup_dir", str(tmp_path / "yedek"))
    yield s
    db.close()
