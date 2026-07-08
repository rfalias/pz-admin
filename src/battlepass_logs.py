import os
import re
from pathlib import Path

_LINE_RE = re.compile(
    r'^\[(?P<ts>[\d:.\- ]+)\]\s+(?P<tag>[A-Z_]+):\s+(?P<fields>.*)\.$'
)
_KEY_RE = re.compile(r'\b([a-zA-Z_]+)=')

TAG_GROUPS: dict[str, set[str]] = {
    "player":        {"REDEEM", "REDEEM_ALL", "CLAIM_TIER_ITEM", "TIER_COMPLETE"},
    "reward":        {"FEAT_REWARD", "LOOT_QUEST_REWARD", "CRAFT_QUEST_REWARD", "SKILL_REWARD", "FIRST_CRAFT"},
    "carryover":     {"CARRYOVER_IMPORT", "CARRYOVER_IMPORT_DONE"},
    "admin_eco":     {"GRANT", "WIPE"},
    "admin_content": {
        "ADD_TIER", "REMOVE_TIER", "ADD_TIER_ITEM", "REMOVE_TIER_ITEM",
        "ADD_QUEST", "REMOVE_QUEST", "ADD_CRAFT_QUEST", "REMOVE_CRAFT_QUEST",
        "ADD_FEAT", "REMOVE_FEAT", "SET_SEASON_PLAN_INFO",
    },
    "season": {"END_SEASON"},
}

_TAG_TO_GROUP: dict[str, str] = {
    tag: group for group, tags in TAG_GROUPS.items() for tag in tags
}


def _parse_fields(fields_str: str) -> dict[str, str]:
    """Parse 'k1=v1 k2=v2 ...' where values may contain spaces.
    Finds each key= position and slices the value up to the next key=."""
    matches = list(_KEY_RE.finditer(fields_str))
    result: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(fields_str)
        result[key] = fields_str[start:end].strip()
    return result


def _tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists() or n <= 0:
        return []
    chunk = 8192
    data = b""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        remaining = f.tell()
        while remaining > 0 and data.count(b"\n") <= n:
            step = min(chunk, remaining)
            remaining -= step
            f.seek(remaining)
            data = f.read(step) + data
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    return [ln.decode("utf-8", errors="replace") for ln in lines[-n:]]


def find_battlepass_files(logs_dir: Path) -> list[Path]:
    """All BattlePassAdmin files across top-level and dated subdirectories, newest first."""
    found: set[Path] = set()
    found.update(logs_dir.glob("*_BattlePassAdmin.txt"))
    for subdir in logs_dir.glob("logs_*"):
        if subdir.is_dir():
            found.update(subdir.glob("*_BattlePassAdmin.txt"))
    return sorted(found, key=lambda p: p.name, reverse=True)


def parse_line(line: str) -> dict | None:
    m = _LINE_RE.match(line.strip())
    if not m:
        return None
    tag = m.group("tag")
    all_fields = _parse_fields(m.group("fields"))
    return {
        "timestamp": m.group("ts").strip(),
        "tag": tag,
        "group": _TAG_TO_GROUP.get(tag, "unknown"),
        "player": all_fields.get("player"),
        "fields": {k: v for k, v in all_fields.items() if k != "player"},
    }


def read_battlepass_logs(
    logs_dir: Path,
    n: int,
    file_name: str | None = None,
    player_filter: str | None = None,
) -> tuple[list[dict], list[str]]:
    """Return (entries, available_file_names). entries are newest-first."""
    all_files = find_battlepass_files(logs_dir)
    file_names = [f.name for f in all_files]

    if not all_files:
        return [], file_names

    target = next((f for f in all_files if f.name == file_name), all_files[0])

    entries: list[dict] = []
    for raw in _tail_lines(target, n):
        parsed = parse_line(raw)
        if parsed is None:
            continue
        if player_filter and (parsed.get("player") or "").lower() != player_filter.lower():
            continue
        entries.append(parsed)

    entries.reverse()  # newest first
    return entries, file_names
