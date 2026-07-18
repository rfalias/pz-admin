"""Renders a small static crop of the official Project Zomboid map
(map.projectzomboid.com) centered on a world coordinate, by fetching the
same raw DeepZoom tiles the site's own viewer uses and stitching them
server-side. This deliberately avoids embedding the site's interactive page
(which gates its content behind a cookie-consent dialog that reappears on
every iframe navigation due to browser third-party storage partitioning).

Coordinate transform and tile layout reverse-engineered from the site's own
`coordinates.js`/`map.js`/`globals.js` (the `iso`/default map variant):
  step = sqr
  dx = (x - y) * step / 2
  dy = (x + y) * step / 4
  imageX = (x0 + dx) / scale
  imageY = (y0 + dy) / scale
Tile pyramid is standard DeepZoom: max_level = ceil(log2(max(w, h))), tile
URL is `.../layer0_files/{level}/{col}_{row}.jpg`.
"""
import io
import json
import math
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = "https://map.projectzomboid.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
CACHE_TTL_SECONDS = 6 * 3600

SERVER_VERSION_RE = re.compile(r"version=(\d+)\.(\d+)\.(\d+)")

_cache: dict[str, tuple[float, object]] = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < CACHE_TTL_SECONDS:
        return entry[1]
    return None


def _cache_set(key: str, value):
    _cache[key] = (time.time(), value)


def _fetch_bytes(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _fetch_json(url: str):
    data = _fetch_bytes(url)
    return json.loads(data) if data is not None else None


def _detect_server_pz_version(logs_dir: Path) -> str | None:
    """The PZ build this server actually runs, e.g. "42.19.0" - read from its
    own debug log (`version=X.Y.Z ...`, logged once near the top on every
    boot) rather than assumed, so the map preview always matches the live
    server's build instead of whatever map.projectzomboid.com happens to
    mark as its own site-wide default (which was Build 41, not this
    server's Build 42, when this was first wired up)."""
    cached = _cache_get("server_version")
    if cached is not None:
        return cached or None
    version = None
    try:
        matches = sorted(logs_dir.glob("*_DebugLog-server.txt"))
        if matches:
            with matches[-1].open("r", encoding="utf-8", errors="replace") as f:
                for _ in range(500):
                    line = f.readline()
                    if not line:
                        break
                    m = SERVER_VERSION_RE.search(line)
                    if m:
                        version = m.group(0).split("=", 1)[1]
                        break
    except OSError:
        pass
    _cache_set("server_version", version or "")
    return version


def _target_version(logs_dir: Path) -> str:
    cached = _cache_get("version")
    if cached is not None:
        return cached
    entries = _fetch_json(f"{ROOT}/build_list.json") or []

    server_version = _detect_server_pz_version(logs_dir)
    version = None
    if server_version and entries:
        exact = next((e for e in entries if e.get("directory") == server_version), None)
        if exact:
            version = exact["directory"]
        else:
            major_minor = ".".join(server_version.split(".")[:2])
            major = server_version.split(".")[0]
            prefix_match = next(
                (e for e in entries if str(e.get("directory", "")).startswith(major_minor + ".")), None
            ) or next(
                (e for e in entries if str(e.get("directory", "")).startswith(major + ".")), None
            )
            if prefix_match:
                version = prefix_match["directory"]

    if not version:
        default_entry = next((e for e in entries if e.get("default")), None)
        version = (default_entry or (entries[0] if entries else {})).get("directory", "")

    _cache_set("version", version)
    return version


def _calibration(version: str) -> dict:
    key = f"calib:{version}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    info = _fetch_json(f"{ROOT}/maps/{version}/base/map_info.json") or {}
    scale = 1 << (int(info.get("skip") or 0))
    w = info.get("w", 0)
    h = info.get("h", 0)
    calib = {
        "x0": info.get("x0", 0),
        "y0": info.get("y0", 0),
        "sqr": info.get("sqr", 1),
        "scale": scale,
        "tile_size": info.get("tile_size", 1024),
        "w": w,
        "h": h,
        "max_level": math.ceil(math.log2(max(w, h, 2))),
    }
    _cache_set(key, calib)
    return calib


def _square_to_image_point(x: float, y: float, calib: dict) -> tuple[float, float]:
    step = calib["sqr"]
    dx = (x - y) * step / 2
    dy = (x + y) * step / 4
    image_x = (calib["x0"] + dx) / calib["scale"]
    image_y = (calib["y0"] + dy) / calib["scale"]
    return image_x, image_y


def _stitch_tiles(
    version: str, calib: dict, level: int, left: float, top: float, out_w: int, out_h: int
) -> Image.Image:
    tile_size = calib["tile_size"]
    col_min = math.floor(left / tile_size)
    col_max = math.floor((left + out_w) / tile_size)
    row_min = math.floor(top / tile_size)
    row_max = math.floor((top + out_h) / tile_size)

    canvas_w = (col_max - col_min + 1) * tile_size
    canvas_h = (row_max - row_min + 1) * tile_size
    canvas = Image.new("RGB", (canvas_w, canvas_h), (40, 42, 45))

    for col in range(col_min, col_max + 1):
        for row in range(row_min, row_max + 1):
            tile_bytes = _fetch_bytes(
                f"{ROOT}/maps/{version}/base/layer0_files/{level}/{col}_{row}.jpg"
            )
            if not tile_bytes:
                continue
            tile_img = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
            canvas.paste(tile_img, ((col - col_min) * tile_size, (row - row_min) * tile_size))

    crop_left = round(left - col_min * tile_size)
    crop_top = round(top - row_min * tile_size)
    return canvas.crop((crop_left, crop_top, crop_left + out_w, crop_top + out_h))


def _draw_marker(draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: int, primary: bool) -> None:
    fill = (214, 40, 40) if primary else (240, 170, 60)
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=fill,
        outline=(255, 255, 255),
        width=2,
    )


def render_preview(x: float, y: float, logs_dir: Path, out_w: int = 560, out_h: int = 420, level_offset: int = 2) -> bytes:
    version = _target_version(logs_dir)
    calib = _calibration(version)
    level = max(0, calib["max_level"] - level_offset)
    downsample = 2 ** (calib["max_level"] - level)

    image_x, image_y = _square_to_image_point(x, y, calib)
    px_x = image_x / downsample
    px_y = image_y / downsample

    left = px_x - out_w / 2
    top = px_y - out_h / 2
    crop = _stitch_tiles(version, calib, level, left, top, out_w, out_h)

    draw = ImageDraw.Draw(crop)
    _draw_marker(draw, out_w // 2, out_h // 2, radius=7, primary=True)

    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def get_map_config(logs_dir: Path) -> dict:
    """Static config a client-side tiled map viewer (Leaflet w/ CRS.Simple)
    needs to render PZ's own map tiles directly: tile URL template, tile
    size, and the zoom/pixel bounds of the tile pyramid."""
    version = _target_version(logs_dir)
    calib = _calibration(version)
    return {
        "tileUrlTemplate": f"{ROOT}/maps/{version}/base/layer0_files/{{z}}/{{x}}_{{y}}.jpg",
        "tileSize": calib["tile_size"],
        "maxZoom": calib["max_level"],
        "width": calib["w"],
        "height": calib["h"],
    }


def world_points_to_image(points: list[tuple[float, float]], logs_dir: Path) -> list[tuple[float, float]]:
    """Converts world (x, y) coordinates to the same base-resolution pixel
    space as get_map_config's tile pyramid (i.e. coordinates a client can
    pass straight into Leaflet's map.unproject(point, maxZoom))."""
    version = _target_version(logs_dir)
    calib = _calibration(version)
    return [_square_to_image_point(x, y, calib) for x, y in points]
