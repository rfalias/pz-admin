"""Named snapshots of Server/Mods/Sandbox settings that can be applied later.
Mirrors audit_log.py's style - plain sqlite3, no ORM, called from async
route handlers via asyncio.to_thread. `content` is an opaque text blob as
far as this module is concerned; page-specific capture/apply logic lives in
main.py."""
import sqlite3
import time
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS config_versions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "page TEXT NOT NULL,"
        "name TEXT NOT NULL,"
        "description TEXT,"
        "content TEXT NOT NULL,"
        "created_epoch REAL NOT NULL,"
        "created_by TEXT,"
        "is_auto INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_versions_page "
        "ON config_versions(page, created_epoch DESC)"
    )
    return conn


def create_version(
    db_path: Path,
    page: str,
    name: str,
    description: str,
    content: str,
    created_by: str | None,
    is_auto: bool = False,
) -> int:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO config_versions "
            "(page, name, description, content, created_epoch, created_by, is_auto) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (page, name, description, content, time.time(), created_by, int(is_auto)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_versions(db_path: Path, page: str) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM config_versions WHERE page = ? ORDER BY created_epoch DESC",
            (page,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_version(db_path: Path, page: str, version_id: int) -> dict | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM config_versions WHERE page = ? AND id = ?", (page, version_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_version(db_path: Path, page: str, version_id: int) -> None:
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "DELETE FROM config_versions WHERE page = ? AND id = ?", (page, version_id)
        )
        conn.commit()
    finally:
        conn.close()
