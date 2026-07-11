"""Reads the PlayerShops mod's JSON-lines transaction log (one flat JSON
object per line: `shop_buy` or `stall_sell`, see the mod's
PlayerShopsServer.lua appendTransactionLine/logShopBuy/logStallSell)."""
import json
import os
from pathlib import Path

TYPES = {
    "shop_buy": "Shop buy",
    "stall_sell": "Stall sell",
}


def _tail_lines(path: Path, n: int) -> list[str]:
    """Read the last n lines of a (possibly large) file without loading it fully."""
    if not path.exists() or n <= 0:
        return []
    chunk_size = 4096
    data = b""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        remaining = f.tell()
        while remaining > 0 and data.count(b"\n") <= n:
            step = min(chunk_size, remaining)
            remaining -= step
            f.seek(remaining)
            data = f.read(step) + data
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    return [line.decode("utf-8", errors="replace") for line in lines[-n:]]


def read_transactions(path: Path, limit: int = 200, types: list[str] | None = None) -> list[dict]:
    """Most-recent-first transaction entries, optionally filtered by type."""
    entries = []
    for raw_line in _tail_lines(path, limit if not types else limit * 4):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if types and entry.get("type") not in types:
            continue
        entries.append(entry)
    entries.reverse()
    return entries[:limit]
