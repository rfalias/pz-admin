"""Reads/writes the PlayerShops mod's admin shop registry (pipe-delimited
text, one shop per line):
`id|type|x|y|z|locationId|reserved|name|owner|item=price,item=price,...`
"""
import re
from pathlib import Path

import items_index

TYPES = {
    "buy": "Pawn",
    "vendor": "Vendor",
}

MAP_ZOOM = 14

_SANITIZE_RE = re.compile(r"[|\r\n]")


def _sanitize(value: str) -> str:
    return _SANITIZE_RE.sub(" ", str(value or ""))


def _parse_items(raw: str) -> list[dict]:
    items = []
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        item, _, price = part.partition("=")
        item = item.strip()
        label = item[len("Base.") :] if item.startswith("Base.") else item
        items.append(
            {
                "item": item,
                "label": label,
                "price": price.strip(),
                "display_name": items_index.display_name(item, label),
                "icon_url": items_index.icon_url(item),
            }
        )
    items.sort(key=lambda it: it["display_name"].lower())
    return items


def read_shops(path: Path) -> list[dict]:
    """All registered shops, in file order."""
    if not path.exists():
        return []
    shops = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split("|")
        if len(fields) < 9:
            continue
        shop_id, shop_type, x, y, z, location_id, reserved, name, owner = fields[:9]
        items_raw = fields[9] if len(fields) > 9 else ""
        shops.append(
            {
                "id": shop_id,
                "type": shop_type,
                "x": x,
                "y": y,
                "z": z,
                "location_id": location_id,
                "reserved": reserved,
                "name": name,
                "owner": owner,
                "stock": _parse_items(items_raw),
                "map_url": f"https://map.projectzomboid.com/?{x}x{y}x{MAP_ZOOM}",
            }
        )
    return shops


def write_shops(path: Path, shops: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for s in shops:
        stock = ",".join(
            f"{item['item']}={int(item['price'])}"
            for item in s.get("stock", [])
            if item.get("item")
        )
        fields = [
            str(int(s["id"])),
            _sanitize(s["type"]),
            str(int(s["x"])),
            str(int(s["y"])),
            str(int(s["z"])),
            _sanitize(s["location_id"]),
            _sanitize(s.get("reserved") or "0"),
            _sanitize(s["name"]),
            _sanitize(s.get("owner") or ""),
            stock,
        ]
        lines.append("|".join(fields))
    text = "\n".join(lines)
    path.write_text(text + "\n" if lines else "")
