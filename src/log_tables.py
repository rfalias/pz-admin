import os
import re
from pathlib import Path

CATEGORIES = {
    "user": "User",
    "chat": "Chat",
    "connections": "Connections",
    "admin": "Admin",
    "cmd": "Command",
    "DebugLog-server": "Debug",
}

DEFAULT_CATEGORIES = ["user", "chat", "connections", "admin", "cmd"]

LINE_RE = re.compile(r"^\[(?P<ts>\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]\s*(?P<message>.*)$")


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


def _latest_file(logs_dir: Path, suffix: str) -> Path | None:
    """The active log file for a category - PZ prefixes each with a session
    timestamp, so the current one is whichever sorts last by name."""
    matches = sorted(logs_dir.glob(f"*_{suffix}.txt"))
    return matches[-1] if matches else None


def _sort_key(ts: str, seq: int) -> tuple:
    """PZ timestamps are DD-MM-YY HH:MM:SS.mmm, which isn't lexicographically
    sortable, so convert to a proper chronological tuple. `seq` breaks ties
    between lines with identical timestamps, preserving file order."""
    try:
        dd, mm, yy = ts[0:2], ts[3:5], ts[6:8]
        hh, mi, rest = ts[9:].split(":", 2)
        ss, ms = rest.split(".")
        return (int(yy), int(mm), int(dd), int(hh), int(mi), int(ss), int(ms), seq)
    except (ValueError, IndexError):
        return (0, 0, 0, 0, 0, 0, 0, seq)


def read_logs(logs_dir: Path, categories: list[str], lines_per_category: int) -> list[dict]:
    """Tail each selected category's current log file and merge them into one
    chronological list of {timestamp, category, message} entries."""
    if not logs_dir.exists():
        return []

    raw_entries = []
    seq = 0
    for category in categories:
        if category not in CATEGORIES:
            continue
        path = _latest_file(logs_dir, category)
        if not path:
            continue
        label = CATEGORIES[category]
        for raw_line in _tail_lines(path, lines_per_category):
            line = raw_line.strip()
            if not line:
                continue
            m = LINE_RE.match(line)
            ts = m.group("ts") if m else ""
            message = m.group("message") if m else line
            raw_entries.append(
                {"timestamp": ts, "category": label, "message": message, "_seq": seq}
            )
            seq += 1

    raw_entries.sort(key=lambda e: _sort_key(e["timestamp"], e["_seq"]), reverse=True)
    for entry in raw_entries:
        del entry["_seq"]
    return raw_entries
