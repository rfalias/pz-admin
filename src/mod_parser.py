"""
Best-effort parser for Steam Workshop pages, used by the Mods tab's
"import from URL" feature.

There's no official API used here - this scrapes the public workshop page
HTML for a convention many PZ mod authors follow of listing their mod's
Workshop ID and Mod ID(s) at the end of the description, e.g.:

    Workshop ID: 3437629766
    Mod ID: CleanUI

Some workshop items bundle multiple mods (e.g. a base mod plus optional
content packs) and list several "Mod ID:" lines for the same Workshop ID -
all of them are collected. Required items (dependencies) are read from the
page's "Required items" sidebar and followed recursively, since a mod's
dependency can itself have further dependencies.

This is inherently fragile: if Steam changes its page markup, or an author
doesn't follow the Workshop ID/Mod ID convention, parsing degrades
gracefully (empty mod_ids / required list) rather than raising - the import
endpoint surfaces this as a human-readable warning so the mod can still be
added manually.
"""
import re
import urllib.error
import urllib.request

WORKSHOP_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={id}"
USER_AGENT = "Mozilla/5.0 (compatible; pz-admin mod importer)"

TITLE_RE = re.compile(r'<div class="workshopItemTitle">\s*(.*?)\s*</div>', re.DOTALL)
MOD_ID_RE = re.compile(r"Mod ID:\s*([^<\r\n]+)")
REQUIRED_ITEM_RE = re.compile(
    r'href="https://steamcommunity\.com/workshop/filedetails/\?id=(\d+)"[^>]*>\s*'
    r'<div class="requiredItem">\s*(.*?)\s*</div>',
    re.DOTALL,
)


def extract_workshop_id(url_or_id: str) -> str | None:
    s = url_or_id.strip()
    if s.isdigit():
        return s
    m = re.search(r"[?&]id=(\d+)", s)
    return m.group(1) if m else None


def fetch_page(workshop_id: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(
        WORKSHOP_URL.format(id=workshop_id), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_page(html: str) -> dict:
    title_match = TITLE_RE.search(html)
    title = title_match.group(1).strip() if title_match else None
    mod_ids = [m.strip() for m in MOD_ID_RE.findall(html) if m.strip()]
    required = [
        {"workshop_id": wid, "title": t.strip()}
        for wid, t in REQUIRED_ITEM_RE.findall(html)
    ]
    return {"title": title, "mod_ids": mod_ids, "required": required}


def resolve_mod_tree(start_id: str, max_depth: int = 10) -> tuple[list[dict], list[str]]:
    """Fetch a workshop item and recursively resolve its required items.

    Returns (mods, errors): `mods` is a flattened, de-duplicated, root-first
    list of {workshop_id, title, mod_ids, is_dependency}; `errors` is a list
    of human-readable messages for anything that failed or looked
    incomplete (e.g. no Mod ID found).
    """
    visited: set[str] = set()
    mods: list[dict] = []
    errors: list[str] = []

    def visit(workshop_id: str, is_dependency: bool, depth: int) -> None:
        if workshop_id in visited:
            return
        visited.add(workshop_id)
        if depth > max_depth:
            errors.append(f"Stopped following dependencies at depth {max_depth} (workshop ID {workshop_id}).")
            return
        try:
            html = fetch_page(workshop_id)
        except Exception as exc:
            errors.append(f"Could not fetch workshop ID {workshop_id}: {exc}")
            return

        parsed = parse_page(html)
        label = parsed["title"] or f"workshop ID {workshop_id}"
        if not parsed["mod_ids"]:
            errors.append(f'"{label}" doesn\'t list a Mod ID in its description - add it manually.')

        mods.append(
            {
                "workshop_id": workshop_id,
                "title": parsed["title"],
                "mod_ids": parsed["mod_ids"],
                "is_dependency": is_dependency,
            }
        )
        for req in parsed["required"]:
            visit(req["workshop_id"], True, depth + 1)

    visit(start_id, False, 0)
    return mods, errors
