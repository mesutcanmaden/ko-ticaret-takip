"""Upgrade seviyeleri.

Veritabanında tam sayı olarak saklanır:
    0          -> upgrade yok
    1 .. 10    -> düz itemler  (+1 … +10)
    101 .. 121 -> rebirth      (Reb1 … Reb21)
"""
from __future__ import annotations

import re

NORMAL_MAX = 10
REB_BASE = 100
REB_MAX = 21

LEVELS: list[int] = [0] + list(range(1, NORMAL_MAX + 1)) + [REB_BASE + i for i in range(1, REB_MAX + 1)]
_VALID = set(LEVELS)


def is_valid(u: int) -> bool:
    return u in _VALID


def label(u: int) -> str:
    """Kısa etiket: '+8', 'Reb3' veya '' (upgrade yok)."""
    u = int(u or 0)
    if u == 0:
        return ""
    if u > REB_BASE:
        return f"Reb{u - REB_BASE}"
    return f"+{u}"


def combo_label(u: int) -> str:
    """Açılır listede görünen metin."""
    return label(u) or "Yok"


def display_name(name: str, upgrade: int) -> str:
    lab = label(upgrade)
    return f"{name} {lab}" if lab else name


_RE = re.compile(r"^(.*?)\s*(?:\+\s*(\d{1,2})|reb\s*(\d{1,2}))$", re.IGNORECASE)


def split_name_upgrade(text: str) -> tuple[str, int | None]:
    """'Shard +8' -> ('Shard', 8); 'Shard Reb3' -> ('Shard', 103); 'Shard' -> ('Shard', None).

    Listede olmayan bir seviye (+15, Reb30) yazılırsa ad olduğu gibi bırakılır (upgrade=None).
    """
    s = " ".join(str(text or "").split())
    m = _RE.match(s)
    if m and m.group(1).strip():
        u = int(m.group(2)) if m.group(2) is not None else REB_BASE + int(m.group(3))
        if is_valid(u) and u != 0:
            return m.group(1).strip(), u
    return s, None
