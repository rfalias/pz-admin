from pathlib import Path


def _move_after(entries: list[dict], anchor_key: str, move_key: str) -> None:
    """Reposition the move_key entry directly after anchor_key, if both are present."""
    move_idx = next((i for i, e in enumerate(entries) if e["key"] == move_key), None)
    anchor_present = any(e["key"] == anchor_key for e in entries)
    if move_idx is None or not anchor_present:
        return
    item = entries.pop(move_idx)
    anchor_idx = next(i for i, e in enumerate(entries) if e["key"] == anchor_key)
    entries.insert(anchor_idx + 1, item)


def parse_ini(path: Path) -> list[dict]:
    """Parse a PZ server .ini file (key=value, '#' comments) into an ordered list of entries."""
    entries = []
    if not path.exists():
        return entries

    pending_comments: list[str] = []
    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        if stripped == "":
            pending_comments = []
            continue
        if stripped.startswith("#"):
            pending_comments.append(stripped.lstrip("#").strip())
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            key = key.strip()
            is_bool = value.strip().lower() in ("true", "false")
            entries.append(
                {
                    "key": key,
                    "value": value,
                    "comment": " ".join(pending_comments),
                    "is_bool": is_bool,
                }
            )
            pending_comments = []

    # Mods and WorkshopItems are defined far apart in the stock ini but must be
    # kept in sync with each other, so surface them side by side.
    _move_after(entries, "Mods", "WorkshopItems")
    return entries


def get_value(entries: list[dict], key: str, default: str = "") -> str:
    entry = next((e for e in entries if e["key"] == key), None)
    return entry["value"] if entry else default


def _split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(";") if v.strip()]


def validate_mods(entries: list[dict]) -> str | None:
    """Warn when a Mods entry doesn't have a matching WorkshopItems id."""
    mods = next((e for e in entries if e["key"] == "Mods"), None)
    workshop = next((e for e in entries if e["key"] == "WorkshopItems"), None)
    if mods is None or workshop is None:
        return None

    mod_ids = _split_list(mods["value"])
    workshop_ids = _split_list(workshop["value"])
    missing = len(mod_ids) - len(workshop_ids)
    if missing > 0:
        return (
            f"Mods has {len(mod_ids)} entr{'y' if len(mod_ids) == 1 else 'ies'} but "
            f"WorkshopItems only has {len(workshop_ids)} — add the missing Workshop ID"
            f"{'' if missing == 1 else 's'} so every mod can be downloaded."
        )
    return None


def write_ini(path: Path, entries: list[dict]) -> None:
    lines = []
    for entry in entries:
        if entry["comment"]:
            lines.append(f"# {entry['comment']}")
        lines.append(f"{entry['key']}={entry['value']}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip("\n") + "\n")


def apply_form(entries: list[dict], form: dict) -> None:
    for entry in entries:
        key = entry["key"]
        if entry["is_bool"]:
            entry["value"] = "true" if key in form else "false"
        elif key in form:
            entry["value"] = form[key]
