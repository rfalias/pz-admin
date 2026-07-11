"""Caches friendly Workshop titles for installed mods, keyed by workshop ID.

Fetching a title means scraping the Steam Workshop page (see mod_parser), so
results are cached to disk and only re-fetched once they go stale - keeps the
public dashboard from depending on a live Steam request per page view.
"""
import json
import time
from pathlib import Path

import mod_parser

CACHE_TTL_SECONDS = 24 * 60 * 60


def _load_cache(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache))


def refresh_titles(cache_path: Path, workshop_ids: list[str]) -> None:
    """Fetch and cache titles for any workshop ID that's missing or stale.
    Best-effort: a failed fetch keeps whatever title was already cached."""
    cache = _load_cache(cache_path)
    now = time.time()
    changed = False
    for workshop_id in workshop_ids:
        if not workshop_id:
            continue
        entry = cache.get(workshop_id)
        if entry and now - entry.get("fetched_at", 0) < CACHE_TTL_SECONDS:
            continue
        try:
            html = mod_parser.fetch_page(workshop_id)
            title = mod_parser.parse_page(html).get("title")
        except Exception:
            title = None
        if title:
            cache[workshop_id] = {"title": title, "fetched_at": now}
            changed = True
        elif entry is None:
            # Never fetched successfully - avoid retrying it every loop tick.
            cache[workshop_id] = {"title": None, "fetched_at": now}
            changed = True
    if changed:
        _save_cache(cache_path, cache)


def get_titles(cache_path: Path) -> dict[str, str]:
    """Return {workshop_id: title} for every cached ID with a known title."""
    cache = _load_cache(cache_path)
    return {wid: entry["title"] for wid, entry in cache.items() if entry.get("title")}
