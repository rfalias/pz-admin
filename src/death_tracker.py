import re
import sqlite3
from pathlib import Path

DIED_RE = re.compile(
    r"^\[(?P<ts>\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\] "
    r"user (?P<username>\S+) died at \((?P<x>-?\d+),(?P<y>-?\d+),(?P<z>-?\d+)\) "
    r"\((?P<pvp>[^)]+)\)\."
)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS log_progress ("
        "filename TEXT PRIMARY KEY, bytes_read INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS deaths ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "username TEXT NOT NULL,"
        "x INTEGER, y INTEGER, z INTEGER,"
        "pvp TEXT,"
        "occurred_at TEXT,"
        "source_file TEXT,"
        "UNIQUE(username, occurred_at, x, y, z))"
    )
    return conn


def _parse_timestamp(ts: str) -> str:
    """PZ logs use DD-MM-YY HH:MM:SS.mmm. Return an ISO-ish string, assuming 2000s."""
    day, month, year = ts[0:2], ts[3:5], ts[6:8]
    rest = ts[9:]
    return f"20{year}-{month}-{day} {rest}"


def _iter_user_log_files(logs_dir: Path):
    if not logs_dir.exists():
        return []
    return sorted(logs_dir.rglob("*_user.txt"))


def scan_logs(logs_dir: Path, db_path: Path) -> int:
    """Parse any new lines appended to *_user.txt log files since the last
    scan and record new death events. Returns the number of new deaths found.
    Safe to call frequently - tracks a byte offset per file so it never
    re-reads already-processed data."""
    conn = _connect(db_path)
    new_deaths = 0
    try:
        for path in _iter_user_log_files(logs_dir):
            key = str(path)
            row = conn.execute(
                "SELECT bytes_read FROM log_progress WHERE filename = ?", (key,)
            ).fetchone()
            offset = row[0] if row else 0

            with path.open("rb") as f:
                f.seek(offset)
                chunk = f.read()

            if not chunk:
                continue

            last_newline = chunk.rfind(b"\n")
            if last_newline == -1:
                continue  # no complete line yet, wait for more data

            usable = chunk[:last_newline + 1]
            text = usable.decode("utf-8", errors="replace")

            for line in text.splitlines():
                m = DIED_RE.match(line.strip())
                if not m:
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO deaths "
                    "(username, x, y, z, pvp, occurred_at, source_file) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        m.group("username"),
                        int(m.group("x")),
                        int(m.group("y")),
                        int(m.group("z")),
                        m.group("pvp"),
                        _parse_timestamp(m.group("ts")),
                        key,
                    ),
                )
                if cur.rowcount:
                    new_deaths += 1

            conn.execute(
                "INSERT INTO log_progress (filename, bytes_read) VALUES (?, ?) "
                "ON CONFLICT(filename) DO UPDATE SET bytes_read = excluded.bytes_read",
                (key, offset + len(usable)),
            )
            conn.commit()
    finally:
        conn.close()
    return new_deaths


def get_death_counts(db_path: Path) -> dict:
    """Return {username_lower: death_count}."""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT username, COUNT(*) FROM deaths GROUP BY username"
        ).fetchall()
        return {username.lower(): count for username, count in rows}
    finally:
        conn.close()


def get_death_leaderboard(db_path: Path) -> list[dict]:
    """Return [{username, count}], sorted by most deaths first, preserving
    the display casing of the username (unlike get_death_counts)."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT username, COUNT(*) as count FROM deaths "
            "GROUP BY username ORDER BY count DESC, username COLLATE NOCASE"
        ).fetchall()
        return [{"username": username, "count": count} for username, count in rows]
    finally:
        conn.close()
