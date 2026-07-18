"""Looks up PZ item metadata (display name, icon) from `items_index.json`
(a snapshot of every item's `fullType` -> displayName/icon mapping, built
outside this app). Loaded once at import time.

Not checked into the public repo (large, extracted game assets) -- a
checkout without it just gets fallback names and no icons everywhere,
rather than the whole app failing to start."""
import json
import logging
from pathlib import Path

_PATH = Path(__file__).parent / "items_index.json"
logger = logging.getLogger(__name__)

BY_FULLTYPE: dict[str, dict] = {}

if _PATH.exists():
    with _PATH.open() as f:
        for entry in json.load(f):
            full_type = entry.get("fullType")
            if full_type:
                BY_FULLTYPE[full_type] = entry
else:
    logger.warning("%s not found -- item icons/display names will be unavailable", _PATH)


def icon_url(full_type: str) -> str | None:
    entry = BY_FULLTYPE.get(full_type)
    if entry and entry.get("hasIcon") and entry.get("icon"):
        return f"/static/images/{entry['icon']}"
    return None


def display_name(full_type: str, fallback: str) -> str:
    entry = BY_FULLTYPE.get(full_type)
    if entry and entry.get("displayName"):
        return entry["displayName"]
    return fallback


def client_index() -> list[dict]:
    """Trimmed [{fullType, displayName, icon}], for the browser typeahead."""
    return sorted(
        (
            {
                "fullType": full_type,
                "displayName": entry.get("displayName") or entry.get("name") or full_type,
                "icon": entry.get("icon") if entry.get("hasIcon") else None,
            }
            for full_type, entry in BY_FULLTYPE.items()
        ),
        key=lambda e: e["displayName"],
    )
