import re
from pathlib import Path

_ASSIGN_RE = re.compile(r"^(\w+)\s*=\s*(.*)$")
_HEADER_RE = re.compile(r"^(\w+)\s*=\s*\{$")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _infer_value(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    if raw.endswith(","):
        raw = raw[:-1].strip()
    if raw.lower() in ("true", "false"):
        return raw.lower(), "bool"
    if _NUMBER_RE.match(raw):
        return raw, "number"
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1], "string"
    return raw, "raw"


def _parse_block(lines: list[str], i: int) -> tuple[list[dict], int]:
    items: list[dict] = []
    pending_comments: list[str] = []
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "":
            i += 1
            continue
        if stripped in ("}", "},"):
            return items, i + 1
        if stripped.startswith("--"):
            pending_comments.append(stripped[2:].strip())
            i += 1
            continue
        match = _ASSIGN_RE.match(stripped)
        if not match:
            i += 1
            continue
        key, rest = match.groups()
        rest = rest.strip()
        if rest == "{":
            children, i = _parse_block(lines, i + 1)
            items.append(
                {
                    "key": key,
                    "type": "table",
                    "children": children,
                    "comment": " ".join(pending_comments),
                }
            )
        elif rest in ("{}", "{},"):
            items.append(
                {
                    "key": key,
                    "type": "table",
                    "children": [],
                    "comment": " ".join(pending_comments),
                }
            )
            i += 1
        else:
            value, vtype = _infer_value(rest)
            items.append(
                {
                    "key": key,
                    "type": vtype,
                    "value": value,
                    "comment": " ".join(pending_comments),
                }
            )
            i += 1
        pending_comments = []
    return items, i


def parse_sandbox(path: Path) -> tuple[list[dict], str]:
    """Parse a PZ '<server>_SandboxVars.lua' file into a nested list of entries."""
    var_name = "SandboxVars"
    if not path.exists():
        return [], var_name

    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        match = _HEADER_RE.match(line.strip())
        if match:
            var_name = match.group(1)
            items, _ = _parse_block(lines, i + 1)
            return items, var_name
    return [], var_name


def _format_value(item: dict) -> str:
    if item["type"] == "string":
        return f'"{item["value"]}"'
    return item["value"]


def _render_block(items: list[dict], indent: int) -> list[str]:
    pad = "    " * indent
    out = []
    for item in items:
        if item.get("comment"):
            out.append(f"{pad}-- {item['comment']}")
        if item["type"] == "table":
            out.append(f"{pad}{item['key']} = {{")
            out.extend(_render_block(item["children"], indent + 1))
            out.append(f"{pad}}},")
        else:
            out.append(f"{pad}{item['key']} = {_format_value(item)},")
    return out


def render_sandbox(items: list[dict], var_name: str = "SandboxVars") -> str:
    lines = [f"{var_name} = {{"]
    lines.extend(_render_block(items, 1))
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_sandbox(path: Path, items: list[dict], var_name: str = "SandboxVars") -> None:
    path.write_text(render_sandbox(items, var_name))


def apply_form(items: list[dict], form: dict, prefix: str = "") -> None:
    for item in items:
        path = f"{prefix}{item['key']}"
        if item["type"] == "table":
            apply_form(item["children"], form, prefix=f"{path}.")
        elif item["type"] == "bool":
            item["value"] = "true" if path in form else "false"
        elif path in form:
            item["value"] = form[path]
