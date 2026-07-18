"""Append-only audit trail: login attempts, user management, and admin
commands. Mirrors death_tracker.py's style - plain sqlite3, no ORM, called
from async route handlers via asyncio.to_thread."""
import sqlite3
import time
from pathlib import Path

ACTIONS = {
    "login": "Login",
    "login_failed": "Login failed",
    "logout": "Logout",
    "server_save": "Server settings saved",
    "mods_save": "Mods saved",
    "mods_import": "Mod import",
    "sandbox_save": "Sandbox saved",
    "version_create": "Config version saved",
    "version_apply": "Config version applied",
    "version_delete": "Config version deleted",
    "env_settings_save": "Environment settings saved",
    "spawnpoints_save": "Spawn points saved",
    "shops_save": "Shops saved",
    "event_zones_save": "Trigger zones saved",
    "rcon_save": "World save (RCON)",
    "remote_run": "Remote command",
    "access_level_change": "Access level change",
    "teleport": "Teleport",
    "wipe": "Server wipe",
    "restart": "Server restart",
    "user_create": "User created",
    "user_toggle_active": "User enabled/disabled",
    "user_toggle_superuser": "Admin granted/revoked",
    "user_password_reset": "Password reset",
    "user_delete": "User deleted",
}


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "epoch REAL NOT NULL,"
        "actor TEXT,"
        "action TEXT NOT NULL,"
        "detail TEXT,"
        "success INTEGER NOT NULL,"
        "ip TEXT)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_epoch ON audit_events(epoch DESC)")
    return conn


def record_event(
    db_path: Path,
    action: str,
    actor: str | None,
    detail: str | None = None,
    success: bool = True,
    ip: str | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO audit_events (epoch, actor, action, detail, success, ip) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), actor, action, detail, int(success), ip),
        )
        conn.commit()
    finally:
        conn.close()


def last_activity(db_path: Path) -> dict[str, dict]:
    """Per-actor most recent successful login epoch and most recent event of
    any kind (activity, success or not), keyed by username. An actor with no
    rows of a given kind simply has no key for it - e.g. a user who was
    created but never logged in has no "login" entry."""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        login_rows = conn.execute(
            "SELECT actor, MAX(epoch) AS epoch FROM audit_events "
            "WHERE action = 'login' AND success = 1 AND actor IS NOT NULL "
            "GROUP BY actor"
        ).fetchall()
        activity_rows = conn.execute(
            "SELECT actor, MAX(epoch) AS epoch FROM audit_events "
            "WHERE actor IS NOT NULL GROUP BY actor"
        ).fetchall()
        result: dict[str, dict] = {}
        for row in login_rows:
            result.setdefault(row["actor"], {})["last_login_epoch"] = row["epoch"]
        for row in activity_rows:
            result.setdefault(row["actor"], {})["last_activity_epoch"] = row["epoch"]
        return result
    finally:
        conn.close()


def list_events(db_path: Path, limit: int = 200, actions: list[str] | None = None) -> list[dict]:
    """Return most-recent-first audit rows, optionally filtered to a set of
    action types. `actions=None` or empty returns all types."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        if actions:
            placeholders = ",".join("?" for _ in actions)
            rows = conn.execute(
                f"SELECT * FROM audit_events WHERE action IN ({placeholders}) "
                "ORDER BY epoch DESC LIMIT ?",
                (*actions, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_events ORDER BY epoch DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
