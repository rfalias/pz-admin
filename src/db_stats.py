import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import character_blob


def _last_connection_epoch(value: str | None) -> float | None:
    """PZ stores lastConnection as a naive UTC timestamp string; convert it to
    a Unix epoch so the client can render it in the viewer's local timezone."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def list_users(db_path: Path) -> list[dict]:
    """Return registered (whitelisted) users with their role name and last connection time."""
    if not db_path.exists():
        return []
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT w.username, w.displayName, w.steamid, w.lastConnection,
                   COALESCE(r.name, w.role) AS role_name
            FROM whitelist w
            LEFT JOIN role r ON r.id = w.role
            ORDER BY w.lastConnection DESC NULLS LAST, w.username COLLATE NOCASE
            """
        ).fetchall()
        users = [dict(row) for row in rows]
        for u in users:
            u["lastConnectionEpoch"] = _last_connection_epoch(u["lastConnection"])
        return users
    finally:
        conn.close()


def list_characters(save_db_path: Path) -> dict:
    """Return a dict of username (lowercase) -> character info, decoded from
    the per-save players.db networkPlayers table. Best-effort: any row whose
    blob can't be parsed is skipped rather than failing the whole call."""
    if not save_db_path.exists():
        return {}
    uri = f"file:{save_db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT username, name, steamid, x, y, z, isDead, data FROM networkPlayers"
        ).fetchall()
        characters = {}
        for row in rows:
            username = row["username"]
            if not username:
                continue
            info = {
                "display_name": row["name"],
                "steamid": row["steamid"],
                "x": row["x"],
                "y": row["y"],
                "z": row["z"],
                "is_dead": bool(row["isDead"]),
            }
            try:
                info["character"] = character_blob.parse_character(row["data"])
            except Exception:
                info["character"] = None
            characters[username.lower()] = info
        return characters
    finally:
        conn.close()
