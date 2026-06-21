import json
import os
from pathlib import Path

USERS_FILE = Path(os.environ.get("USERS_FILE", "/app/users.json"))


def load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    with USERS_FILE.open() as f:
        data = json.load(f)
    return {u["username"]: u["password"] for u in data.get("users", [])}


def verify_login(username: str, password: str) -> bool:
    users = load_users()
    return username in users and users[username] == password
