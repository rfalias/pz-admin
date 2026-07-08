import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


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


def scan_logs(death_log_path: Path, db_path: Path) -> int:
    """Read new lines appended to DeathTracker.log and persist deaths.
    Tracks a byte offset so it never re-reads already-processed data.
    Returns the number of new deaths found."""
    if not death_log_path.exists():
        return 0

    conn = _connect(db_path)
    new_deaths = 0
    key = str(death_log_path)
    try:
        row = conn.execute(
            "SELECT bytes_read FROM log_progress WHERE filename = ?", (key,)
        ).fetchone()
        offset = row[0] if row else 0

        with death_log_path.open("rb") as f:
            f.seek(offset)
            chunk = f.read()

        if not chunk:
            return 0

        last_newline = chunk.rfind(b"\n")
        if last_newline == -1:
            return 0  # incomplete line, wait for more data

        usable = chunk[: last_newline + 1]

        for raw_line in usable.decode("utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            username = entry.get("username")
            ts = entry.get("timestamp")
            if not username or ts is None:
                continue

            occurred_at = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S.000"
            )
            cur = conn.execute(
                "INSERT OR IGNORE INTO deaths "
                "(username, x, y, z, pvp, occurred_at, source_file) "
                "VALUES (?, ?, ?, ?, NULL, ?, ?)",
                (username, entry.get("x"), entry.get("y"), entry.get("z"), occurred_at, key),
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
    """Return [{username, count}] sorted by most deaths first."""
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
