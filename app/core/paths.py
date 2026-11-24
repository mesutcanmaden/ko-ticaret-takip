"""Kalıcı kullanıcı veri klasörü.

Windows'ta: %LOCALAPPDATA%\\KOTicaretTakip
Veritabanı EXE'nin bulunduğu klasörden bağımsızdır; EXE taşınsa / silinse bile veriler korunur.
Testler için KO_TICARET_DATA_DIR ortam değişkeniyle değiştirilebilir.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "KO Ticaret Takip"
APP_DIR_NAME = "KOTicaretTakip"
APP_VERSION = "1.0.0"
DB_FILE_NAME = "ticaret.db"


def data_dir() -> Path:
    override = os.environ.get("KO_TICARET_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform.startswith("win"):
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        base = Path(root) / APP_DIR_NAME
    else:
        base = Path.home() / ".local" / "share" / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / DB_FILE_NAME


def default_backup_dir() -> Path:
    p = data_dir() / "Yedekler"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_path() -> Path:
    return data_dir() / "hata_kaydi.log"


def resource_path(relative: str) -> Path:
    """PyInstaller ile paketlenmiş halde de çalışan kaynak dosya yolu."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative
