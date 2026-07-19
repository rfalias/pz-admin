import asyncio
import json
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from itertools import zip_longest
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import admin_shops
import audit_log
import battlepass_data
import battlepass_logs
import config_versions
import db_stats
import death_tracker
import docker_control
import dynamic_spawnpoints
import event_manager
import ini_config
import items_index
import log_tables
import lua_config
import map_preview
import mod_parser
import mod_titles
import player_locations
import player_shops
import rcon_client
import rcon_commands
from auth_db import (
    LastSuperuserError,
    User,
    UserManager,
    UsernameTakenError,
    auth_backend,
    create_db_and_tables,
    create_user,
    current_user_optional,
    current_user_token_optional,
    delete_user,
    get_database_strategy,
    get_user_by_id,
    get_user_manager,
    list_users,
    migrate_users_json,
    set_user_active,
    set_user_password,
    set_user_superuser,
)

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
SERVER_NAME = os.environ.get("SERVER_NAME", "pzserver")
PZ_CONTAINER_NAME = os.environ.get("PZ_CONTAINER_NAME", "projectzomboid")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "change-me-please")
RCON_HOST = os.environ.get("RCON_HOST", "host.docker.internal")
RCON_PORT = int(os.environ.get("RCON_PORT", "27015"))
RCON_PASSWORD = os.environ.get("RCON_PASSWORD", "")
CONNECT_HOST = os.environ.get("CONNECT_HOST", "")

SERVER_INI_PATH = CONFIG_DIR / "Server" / f"{SERVER_NAME}.ini"
SANDBOX_LUA_PATH = CONFIG_DIR / "Server" / f"{SERVER_NAME}_SandboxVars.lua"
PLAYER_DB_PATH = CONFIG_DIR / "db" / f"{SERVER_NAME}.db"
SAVE_DB_PATH = CONFIG_DIR / "Saves" / "Multiplayer" / SERVER_NAME / "players.db"
LOGS_DIR = CONFIG_DIR / "Logs"
DEATH_LOG_PATH = CONFIG_DIR / "Lua" / "DeathTracker.log"
BATTLEPASS_DATA_PATH = CONFIG_DIR / "Lua" / "BattlePassPlayerData.json"
SPAWNPOINTS_PATH = CONFIG_DIR / "Lua" / f"DynamicSpawnPoints_{SERVER_NAME}_EventSpawns.txt"
PLAYERSHOPS_LOG_PATH = CONFIG_DIR / "Lua" / "PlayerShopsTransactions.log"
PLAYER_LOCATIONS_DIR = CONFIG_DIR / "Lua" / "playerlocations"
ADMIN_SHOP_REGISTRY_PATH = CONFIG_DIR / "Lua" / f"PlayerShops_{SERVER_NAME}_AdminShopRegistry.txt"
EVENT_TRIGGER_ZONES_PATH = CONFIG_DIR / "Lua" / f"EventManager_{SERVER_NAME}_TriggerZones.txt"
EVENT_SPAWN_POINTS_PATH = CONFIG_DIR / "Lua" / f"EventManager_{SERVER_NAME}_SpawnPoints.txt"
APP_DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "/app/data"))
DEATHS_DB_PATH = APP_DATA_DIR / "deaths.db"
LAST_WIPE_PATH = APP_DATA_DIR / "last_wipe.json"
MOD_TITLES_CACHE_PATH = APP_DATA_DIR / "mod_titles.json"
AUDIT_DB_PATH = APP_DATA_DIR / "audit.db"
CONFIG_VERSIONS_DB_PATH = APP_DATA_DIR / "config_versions.db"
DEATH_SCAN_INTERVAL_SECONDS = int(os.environ.get("DEATH_SCAN_INTERVAL_SECONDS", "60"))
MOD_TITLES_REFRESH_INTERVAL_SECONDS = int(os.environ.get("MOD_TITLES_REFRESH_INTERVAL_SECONDS", "3600"))
USERS_FILE = Path(os.environ.get("USERS_FILE", "/app/users.json"))
RUNTIME_CONFIG_PATH = APP_DATA_DIR / "runtime_config.json"

# Features that only produce real data if a specific optional Workshop mod
# is installed -- toggleable in Settings so a server that doesn't run one
# can hide its (otherwise permanently-empty-looking) tab. Default True so
# existing deployments don't lose tabs on upgrade.
FEATURE_BATTLEPASS = True
FEATURE_SHOPS = True
FEATURE_SPAWNPOINTS = True
FEATURE_PLAYER_LOCATIONS = True

# name -> [(mod display name, workshop id), ...], used by the Settings page
# to link each toggle to the mod(s) it needs and show whether that mod is
# currently in this server's own WorkshopItems list.
REQUIRED_MODS = {
    "battlepass": [("BattlePass", 3756808742)],
    "shops": [("PlayerShops", 3749824460)],
    "spawnpoints": [("DynamicSpawnPoints", 3759808711), ("EventManager", 3762284248)],
    "player_locations": [("PlayerLocationReporter", 3767193809)],
}


def _load_runtime_config_overrides() -> dict:
    if not RUNTIME_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(RUNTIME_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _recompute_server_paths() -> None:
    global SERVER_INI_PATH, SANDBOX_LUA_PATH, PLAYER_DB_PATH, SAVE_DB_PATH, SPAWNPOINTS_PATH
    SERVER_INI_PATH = CONFIG_DIR / "Server" / f"{SERVER_NAME}.ini"
    SANDBOX_LUA_PATH = CONFIG_DIR / "Server" / f"{SERVER_NAME}_SandboxVars.lua"
    PLAYER_DB_PATH = CONFIG_DIR / "db" / f"{SERVER_NAME}.db"
    SAVE_DB_PATH = CONFIG_DIR / "Saves" / "Multiplayer" / SERVER_NAME / "players.db"
    SPAWNPOINTS_PATH = CONFIG_DIR / "Lua" / f"DynamicSpawnPoints_{SERVER_NAME}_EventSpawns.txt"


def _apply_runtime_config(values: dict) -> None:
    """Apply an environment-settings override dict onto the live globals
    (and keep docker_control.py's independent copy in sync). Safe to call at
    startup (from persisted overrides) or from the Settings page (from a
    submitted form) - only keys present in `values` are touched, and a blank
    RCON_PASSWORD means "keep the current one"."""
    global PZ_CONTAINER_NAME, SERVER_NAME, RCON_HOST, RCON_PORT, RCON_PASSWORD
    global CONNECT_HOST, DEATH_SCAN_INTERVAL_SECONDS, MOD_TITLES_REFRESH_INTERVAL_SECONDS
    global FEATURE_BATTLEPASS, FEATURE_SHOPS, FEATURE_SPAWNPOINTS, FEATURE_PLAYER_LOCATIONS

    if values.get("PZ_CONTAINER_NAME"):
        PZ_CONTAINER_NAME = values["PZ_CONTAINER_NAME"]
        docker_control.PZ_CONTAINER_NAME = PZ_CONTAINER_NAME
    if values.get("SERVER_NAME"):
        SERVER_NAME = values["SERVER_NAME"]
        _recompute_server_paths()
    if values.get("RCON_HOST"):
        RCON_HOST = values["RCON_HOST"]
    if "RCON_PORT" in values and values["RCON_PORT"] != "":
        RCON_PORT = int(values["RCON_PORT"])
    if values.get("RCON_PASSWORD"):
        RCON_PASSWORD = values["RCON_PASSWORD"]
    if "CONNECT_HOST" in values:
        CONNECT_HOST = values["CONNECT_HOST"]
    if "DEATH_SCAN_INTERVAL_SECONDS" in values and values["DEATH_SCAN_INTERVAL_SECONDS"] != "":
        DEATH_SCAN_INTERVAL_SECONDS = int(values["DEATH_SCAN_INTERVAL_SECONDS"])
    if (
        "MOD_TITLES_REFRESH_INTERVAL_SECONDS" in values
        and values["MOD_TITLES_REFRESH_INTERVAL_SECONDS"] != ""
    ):
        MOD_TITLES_REFRESH_INTERVAL_SECONDS = int(values["MOD_TITLES_REFRESH_INTERVAL_SECONDS"])

    # Booleans: unlike the string fields above, False is a legitimate value
    # to apply, so this must check *presence* in values, not truthiness.
    if "FEATURE_BATTLEPASS" in values:
        FEATURE_BATTLEPASS = bool(values["FEATURE_BATTLEPASS"])
    if "FEATURE_SHOPS" in values:
        FEATURE_SHOPS = bool(values["FEATURE_SHOPS"])
    if "FEATURE_SPAWNPOINTS" in values:
        FEATURE_SPAWNPOINTS = bool(values["FEATURE_SPAWNPOINTS"])
    if "FEATURE_PLAYER_LOCATIONS" in values:
        FEATURE_PLAYER_LOCATIONS = bool(values["FEATURE_PLAYER_LOCATIONS"])


def _feature_enabled(name: str) -> bool:
    return {
        "battlepass": FEATURE_BATTLEPASS,
        "shops": FEATURE_SHOPS,
        "spawnpoints": FEATURE_SPAWNPOINTS,
        "player_locations": FEATURE_PLAYER_LOCATIONS,
    }.get(name, True)


_apply_runtime_config(_load_runtime_config_overrides())

DEFAULT_LOG_LINES = 100
MAX_LOG_LINES = 2000

BASE_DIR = Path(__file__).resolve().parent


async def _death_scan_loop():
    """Periodically parse *_user.txt logs for deaths, independent of anyone
    viewing the Stats page - so deaths aren't missed if a log file rotates
    (and its old copy is later cleaned up) between page visits."""
    while True:
        try:
            await asyncio.to_thread(death_tracker.scan_logs, DEATH_LOG_PATH, DEATHS_DB_PATH)
        except Exception:
            pass
        await asyncio.sleep(DEATH_SCAN_INTERVAL_SECONDS)


async def _mod_titles_loop():
    """Periodically refresh cached Workshop titles for the currently
    configured mods, so the dashboard never has to fetch Steam on a page
    view (it's the public, unauthenticated landing page)."""
    while True:
        try:
            entries = ini_config.parse_ini(SERVER_INI_PATH)
            workshop_ids = ini_config.split_list(ini_config.get_value(entries, "WorkshopItems"))
            await asyncio.to_thread(mod_titles.refresh_titles, MOD_TITLES_CACHE_PATH, workshop_ids)
        except Exception:
            pass
        await asyncio.sleep(MOD_TITLES_REFRESH_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    await migrate_users_json(USERS_FILE)
    death_task = asyncio.create_task(_death_scan_loop())
    mod_titles_task = asyncio.create_task(_mod_titles_loop())
    try:
        yield
    finally:
        death_task.cancel()
        mod_titles_task.cancel()


app = FastAPI(title="PZ Admin", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
# Cache-busts static assets (css/js) on every deploy, since browsers otherwise
# keep serving a stale cached copy after `docker compose up -d --build`.
templates.env.globals["static_version"] = str(int(time.time()))
templates.env.globals["feature_enabled"] = _feature_enabled


def combined_server_status() -> dict:
    """Docker's "running" only means the process started - the PZ world can take
    a while longer to load before RCON actually accepts connections. Downgrade
    to "starting" until RCON responds, so the badge reflects the true state."""
    status = docker_control.get_status()
    if status.get("status") == "running":
        try:
            rcon_client.execute(RCON_HOST, RCON_PORT, RCON_PASSWORD, "players", timeout=2.0)
        except Exception as exc:
            status["status"] = "starting"
            status["error"] = str(exc)
    return status


def pop_flash(request: Request) -> str | None:
    return request.session.pop("flash", None)


def _client_ip(request: Request) -> str | None:
    """Real client IP, resolved through Cloudflare -> Traefik -> this app.

    Cloudflare sits in front of Traefik and stamps the true visitor IP onto
    CF-Connecting-IP; Traefik never touches that header. Traefik's own
    X-Forwarded-For isn't trustworthy here - since Traefik isn't configured
    to trust Cloudflare's IP ranges, it overwrites X-Forwarded-For with the
    immediate TCP peer, which is Cloudflare's edge address, not the visitor
    (confirmed in audit_events: entries were recording 172.70.x.x, a
    Cloudflare range, instead of a real client IP). X-Forwarded-For is kept
    as a fallback for traffic that reaches Traefik directly (e.g. the LAN
    ranges in the pzadmin-whitelist middleware), and request.client.host as
    a last resort for local/direct access with no proxy in front at all.
    """
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


async def _audit(
    request: Request,
    action: str,
    actor: str | None,
    detail: str | None = None,
    success: bool = True,
) -> None:
    """Best-effort audit write - a logging failure must never break the
    action it's recording."""
    try:
        await asyncio.to_thread(
            audit_log.record_event, AUDIT_DB_PATH, action, actor, detail, success, _client_ip(request)
        )
    except Exception:
        pass


def _format_diff_detail(diffs: list[str], max_items: int = 15, max_len: int = 2000) -> str:
    """Join per-field 'key: old -> new' diffs into one audit detail string,
    capped so a change touching many fields doesn't blow up the audit log."""
    if not diffs:
        return "no changes"
    shown = diffs[:max_items]
    detail = "; ".join(shown)
    if len(diffs) > max_items:
        detail += f"; (+{len(diffs) - max_items} more)"
    if len(detail) > max_len:
        detail = detail[: max_len - 3] + "..."
    return detail


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, user: User | None = Depends(current_user_optional)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login_submit(
    request: Request,
    credentials: OAuth2PasswordRequestForm = Depends(),
    user_manager: UserManager = Depends(get_user_manager),
    strategy=Depends(get_database_strategy),
):
    user = await user_manager.authenticate(credentials)
    if user is None or not user.is_active:
        await _audit(request, "login_failed", credentials.username, success=False)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid username or password"}, status_code=401
        )
    await _audit(request, "login", user.username)
    login_response = await auth_backend.login(strategy, user)
    redirect = RedirectResponse("/", status_code=303)
    redirect.headers["set-cookie"] = login_response.headers["set-cookie"]
    return redirect


@app.get("/logout")
async def logout(
    request: Request,
    user_token: tuple = Depends(current_user_token_optional),
    strategy=Depends(get_database_strategy),
):
    request.session.clear()
    user, token = user_token
    if user:
        await _audit(request, "logout", user.username)
        logout_response = await auth_backend.logout(strategy, user, token)
        redirect = RedirectResponse("/dashboard", status_code=303)
        redirect.headers["set-cookie"] = logout_response.headers["set-cookie"]
        return redirect
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/")
def index(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/server", status_code=303)


def _load_battlepass_leaderboard() -> dict | None:
    raw_data = battlepass_data.load_battlepass_data(BATTLEPASS_DATA_PATH)
    return battlepass_data.build_leaderboard(raw_data) if raw_data else None


def _kill_leaderboard(limit: int = 25) -> list[dict]:
    """Top zombie killers by kill_tally.txt, ranked descending. Players with
    no recorded kills yet are omitted rather than cluttering the board with
    zeroes."""
    tallies = player_locations.all_kill_tallies(PLAYER_LOCATIONS_DIR)
    ranked = sorted(
        (t for t in tallies.values() if t.get("kills", 0) > 0),
        key=lambda t: -t.get("kills", 0),
    )[:limit]
    return [
        {
            "rank": i + 1,
            "username": t.get("username", ""),
            "kills": t.get("kills", 0),
            "lastUpdated": t.get("lastUpdated"),
        }
        for i, t in enumerate(ranked)
    ]


def _load_installed_mods(entries: list) -> list[dict]:
    """Friendly names of installed mods, linked to their Workshop page when
    a workshop ID is known. Falls back to the raw mod ID as the name when
    there's no cached title (or no workshop ID at all)."""
    mod_ids = ini_config.split_list(ini_config.get_value(entries, "Mods"))
    workshop_ids = ini_config.split_list(ini_config.get_value(entries, "WorkshopItems"))
    titles = mod_titles.get_titles(MOD_TITLES_CACHE_PATH)
    mods = []
    for mod_id, workshop_id in zip_longest(mod_ids, workshop_ids, fillvalue=""):
        if not mod_id and not workshop_id:
            continue
        name = titles.get(workshop_id) or mod_id or f"Workshop ID {workshop_id}"
        url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}" if workshop_id else None
        mods.append({"name": name, "url": url})
    return mods


def _required_mods_status() -> dict[str, list[dict]]:
    """For each feature in REQUIRED_MODS: its mod name(s), Workshop link(s),
    and whether that mod id is currently in *this* server's own
    WorkshopItems list -- same signal _load_installed_mods already trusts
    for the dashboard's mod tags."""
    entries = ini_config.parse_ini(SERVER_INI_PATH)
    workshop_ids = set(ini_config.split_list(ini_config.get_value(entries, "WorkshopItems")))
    return {
        feature: [
            {
                "name": mod_name,
                "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}",
                "installed": str(workshop_id) in workshop_ids,
            }
            for mod_name, workshop_id in mods
        ]
        for feature, mods in REQUIRED_MODS.items()
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    entries = ini_config.parse_ini(SERVER_INI_PATH)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "server_name": ini_config.get_value(entries, "PublicName") or SERVER_NAME,
            "description": ini_config.get_value(entries, "PublicDescription"),
            "connect_host": CONNECT_HOST,
            "connect_port": ini_config.get_value(entries, "DefaultPort", "16261"),
            "leaderboard": _load_battlepass_leaderboard() if FEATURE_BATTLEPASS else None,
            "kill_leaderboard": _kill_leaderboard() if FEATURE_PLAYER_LOCATIONS else [],
            "mods": _load_installed_mods(entries),
        },
    )


@app.get("/dashboard/raw")
def dashboard_raw(request: Request):
    status = docker_control.get_status()
    try:
        players = rcon_client.list_players(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        rcon_error = None
    except Exception as exc:
        players = []
        rcon_error = str(exc)

    effective_status = status.get("status")
    if effective_status == "running" and rcon_error:
        effective_status = "starting"

    return JSONResponse(
        {
            "status": effective_status,
            "started_at": status.get("started_at"),
            "players": players,
            "rcon_error": rcon_error,
        }
    )


VERSION_PAGES = {"server": "Server Settings", "mods": "Mods", "sandbox": "Sandbox Settings"}


def _capture_version_content(page: str) -> str:
    if page == "server":
        return SERVER_INI_PATH.read_text()
    if page == "sandbox":
        return SANDBOX_LUA_PATH.read_text()
    entries = ini_config.parse_ini(SERVER_INI_PATH)
    return json.dumps(
        {
            "Mods": ini_config.get_value(entries, "Mods"),
            "WorkshopItems": ini_config.get_value(entries, "WorkshopItems"),
        }
    )


def _apply_version_content(page: str, content: str) -> None:
    if page == "server":
        SERVER_INI_PATH.write_text(content)
    elif page == "sandbox":
        SANDBOX_LUA_PATH.write_text(content)
    else:
        # Mods only owns the Mods/WorkshopItems keys of the shared server
        # ini - apply through managed_keys, same as mods_save, so restoring
        # an old Mods version can never touch unrelated Server settings.
        data = json.loads(content)
        entries = ini_config.parse_ini(SERVER_INI_PATH)
        ini_config.apply_form(entries, data, managed_keys={"Mods", "WorkshopItems"})
        ini_config.write_ini(SERVER_INI_PATH, entries)


def _parse_version_entries(page: str):
    if page == "sandbox":
        entries, _ = lua_config.parse_sandbox(SANDBOX_LUA_PATH)
        return entries
    return ini_config.parse_ini(SERVER_INI_PATH)


def _diff_mods(old_entries: list[dict], new_entries: list[dict]) -> list[str]:
    old_pairs = list(
        zip_longest(
            ini_config.split_list(ini_config.get_value(old_entries, "Mods")),
            ini_config.split_list(ini_config.get_value(old_entries, "WorkshopItems")),
            fillvalue="",
        )
    )
    new_pairs = list(
        zip_longest(
            ini_config.split_list(ini_config.get_value(new_entries, "Mods")),
            ini_config.split_list(ini_config.get_value(new_entries, "WorkshopItems")),
            fillvalue="",
        )
    )
    added = [p for p in new_pairs if p not in old_pairs]
    removed = [p for p in old_pairs if p not in new_pairs]
    return [f"+{m} ({w})" if w else f"+{m}" for m, w in added] + [
        f"-{m} ({w})" if w else f"-{m}" for m, w in removed
    ]


@app.get("/server", response_class=HTMLResponse)
def server_page(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    entries = ini_config.parse_ini(SERVER_INI_PATH)
    return templates.TemplateResponse(
        request,
        "server.html",
        {
            "active": "server",
            "user": user.username,
            "entries": entries,
            "categories": ini_config.categorize(entries),
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(SERVER_INI_PATH),
            "server_name": SERVER_NAME,
            "mods_warning": ini_config.validate_mods(entries),
            "last_wipe": _read_last_wipe(),
        },
    )


@app.post("/server")
async def server_save(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    form = dict(await request.form())
    old_entries = ini_config.parse_ini(SERVER_INI_PATH)
    entries = ini_config.parse_ini(SERVER_INI_PATH)
    ini_config.apply_form(entries, form)
    ini_config.write_ini(SERVER_INI_PATH, entries)
    diffs = ini_config.diff_entries(old_entries, entries)
    await _audit(request, "server_save", user.username, detail=_format_diff_detail(diffs))
    flash = "Server settings saved. Restart the server to apply changes."
    mods_warning = ini_config.validate_mods(entries)
    if mods_warning:
        flash += f" Warning: {mods_warning}"
    request.session["flash"] = flash
    return RedirectResponse("/server", status_code=303)


@app.get("/mods", response_class=HTMLResponse)
def mods_page(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    entries = ini_config.parse_ini(SERVER_INI_PATH)
    mod_ids = ini_config.split_list(ini_config.get_value(entries, "Mods"))
    workshop_ids = ini_config.split_list(ini_config.get_value(entries, "WorkshopItems"))
    rows = list(zip_longest(mod_ids, workshop_ids, fillvalue=""))
    return templates.TemplateResponse(
        request,
        "mods.html",
        {
            "active": "mods",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(SERVER_INI_PATH),
            "rows": rows,
            "mods_warning": ini_config.validate_mods(entries),
        },
    )


@app.post("/mods")
async def mods_save(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    form = await request.form()
    mod_ids = form.getlist("mod_id")
    workshop_ids = form.getlist("workshop_id")
    # Pair by row position (not independently) so a mod with a still-blank
    # workshop id (or vice versa) doesn't get shifted out of alignment.
    pairs = [
        (m.strip(), w.strip())
        for m, w in zip_longest(mod_ids, workshop_ids, fillvalue="")
        if m.strip() or w.strip()
    ]
    entries = ini_config.parse_ini(SERVER_INI_PATH)
    old_mod_ids = ini_config.split_list(ini_config.get_value(entries, "Mods"))
    old_workshop_ids = ini_config.split_list(ini_config.get_value(entries, "WorkshopItems"))
    old_pairs = list(zip_longest(old_mod_ids, old_workshop_ids, fillvalue=""))
    ini_config.apply_form(
        entries,
        {
            "Mods": ";".join(m for m, _ in pairs),
            "WorkshopItems": ";".join(w for _, w in pairs),
        },
        managed_keys={"Mods", "WorkshopItems"},
    )
    ini_config.write_ini(SERVER_INI_PATH, entries)
    added = [p for p in pairs if p not in old_pairs]
    removed = [p for p in old_pairs if p not in pairs]
    diffs = [f"+{m} ({w})" if w else f"+{m}" for m, w in added]
    diffs += [f"-{m} ({w})" if w else f"-{m}" for m, w in removed]
    await _audit(request, "mods_save", user.username, detail=_format_diff_detail(diffs))
    flash = "Mods saved. Restart the server to apply changes."
    mods_warning = ini_config.validate_mods(entries)
    if mods_warning:
        flash += f" Warning: {mods_warning}"
    request.session["flash"] = flash
    return RedirectResponse("/mods", status_code=303)


@app.post("/mods/import")
async def mods_import(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    url = (body.get("url") or "").strip()
    workshop_id = mod_parser.extract_workshop_id(url)
    if not workshop_id:
        return JSONResponse({"error": "Could not find a workshop ID in that URL"}, status_code=400)
    mods, errors = await asyncio.to_thread(mod_parser.resolve_mod_tree, workshop_id)
    await _audit(request, "mods_import", user.username, detail=url, success=not errors)
    return JSONResponse({"mods": mods, "errors": errors})


@app.get("/sandbox", response_class=HTMLResponse)
def sandbox_page(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    entries, _ = lua_config.parse_sandbox(SANDBOX_LUA_PATH)
    leaves = [e for e in entries if e["type"] != "table"]
    tables = [e for e in entries if e["type"] == "table"]
    return templates.TemplateResponse(
        request,
        "sandbox.html",
        {
            "active": "sandbox",
            "user": user.username,
            "entries": entries,
            "leaf_categories": lua_config.categorize_leaves(leaves),
            "tables": tables,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(SANDBOX_LUA_PATH),
        },
    )


@app.post("/sandbox")
async def sandbox_save(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    form = dict(await request.form())
    old_entries, _ = lua_config.parse_sandbox(SANDBOX_LUA_PATH)
    entries, var_name = lua_config.parse_sandbox(SANDBOX_LUA_PATH)
    lua_config.apply_form(entries, form)
    lua_config.write_sandbox(SANDBOX_LUA_PATH, entries, var_name)
    diffs = lua_config.diff_items(old_entries, entries)
    await _audit(request, "sandbox_save", user.username, detail=_format_diff_detail(diffs))
    request.session["flash"] = "Sandbox settings saved. Restart the server to apply changes."
    return RedirectResponse("/sandbox", status_code=303)


@app.get("/{page}/versions", response_class=HTMLResponse)
async def versions_page(page: str, request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    if page not in VERSION_PAGES:
        raise HTTPException(404)
    versions = await asyncio.to_thread(config_versions.list_versions, CONFIG_VERSIONS_DB_PATH, page)
    return templates.TemplateResponse(
        request,
        "versions.html",
        {
            "active": page,
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "page": page,
            "page_label": VERSION_PAGES[page],
            "back_url": f"/{page}",
            "versions": versions,
        },
    )


@app.post("/{page}/versions/create")
async def versions_create(
    page: str,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    if page not in VERSION_PAGES:
        raise HTTPException(404)
    name = name.strip()
    if not name:
        request.session["flash"] = "Version name is required."
    else:
        content = _capture_version_content(page)
        await asyncio.to_thread(
            config_versions.create_version,
            CONFIG_VERSIONS_DB_PATH, page, name, description.strip(), content, user.username,
        )
        await _audit(request, "version_create", user.username, detail=f"{page}: {name}")
        request.session["flash"] = f"Saved version '{name}'."
    return RedirectResponse(f"/{page}/versions", status_code=303)


@app.post("/{page}/versions/{version_id}/apply")
async def versions_apply(
    page: str,
    version_id: int,
    request: Request,
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    if page not in VERSION_PAGES:
        raise HTTPException(404)
    version = await asyncio.to_thread(
        config_versions.get_version, CONFIG_VERSIONS_DB_PATH, page, version_id
    )
    if version is None:
        request.session["flash"] = "Version not found."
        return RedirectResponse(f"/{page}/versions", status_code=303)
    await asyncio.to_thread(
        config_versions.create_version,
        CONFIG_VERSIONS_DB_PATH,
        page,
        f"Auto-backup before applying '{version['name']}'",
        "",
        _capture_version_content(page),
        user.username,
        True,
    )
    old_entries = _parse_version_entries(page)
    _apply_version_content(page, version["content"])
    new_entries = _parse_version_entries(page)
    if page == "mods":
        diffs = _diff_mods(old_entries, new_entries)
    elif page == "sandbox":
        diffs = lua_config.diff_items(old_entries, new_entries)
    else:
        diffs = ini_config.diff_entries(old_entries, new_entries)
    await _audit(
        request,
        "version_apply",
        user.username,
        detail=f"{page}: {version['name']} | {_format_diff_detail(diffs)}",
    )
    request.session["flash"] = f"Applied version '{version['name']}'. Restart the server to apply changes."
    return RedirectResponse(f"/{page}", status_code=303)


@app.post("/{page}/versions/{version_id}/delete")
async def versions_delete(
    page: str,
    version_id: int,
    request: Request,
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    if page not in VERSION_PAGES:
        raise HTTPException(404)
    version = await asyncio.to_thread(
        config_versions.get_version, CONFIG_VERSIONS_DB_PATH, page, version_id
    )
    if version is None:
        request.session["flash"] = "Version not found."
    else:
        await asyncio.to_thread(config_versions.delete_version, CONFIG_VERSIONS_DB_PATH, page, version_id)
        await _audit(request, "version_delete", user.username, detail=f"{page}: {version['name']}")
        request.session["flash"] = f"Deleted version '{version['name']}'."
    return RedirectResponse(f"/{page}/versions", status_code=303)


@app.get("/spawnpoints", response_class=HTMLResponse)
def spawnpoints_page(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    if FEATURE_SPAWNPOINTS:
        entries = dynamic_spawnpoints.parse_file(SPAWNPOINTS_PATH)
        zones = event_manager.zones_with_points(
            event_manager.read_zones(EVENT_TRIGGER_ZONES_PATH),
            event_manager.read_spawn_points(EVENT_SPAWN_POINTS_PATH),
        )
    else:
        entries, zones = [], []
    return templates.TemplateResponse(
        request,
        "spawnpoints.html",
        {
            "active": "spawnpoints",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(SPAWNPOINTS_PATH),
            "entries": entries,
            "zones_config_path": str(EVENT_TRIGGER_ZONES_PATH),
            "zones": zones,
            "zone_limits": {
                "min_radius": event_manager.MIN_ZONE_RADIUS,
                "max_radius": event_manager.MAX_ZONE_RADIUS,
                "min_cooldown_sec": event_manager.MIN_ZONE_COOLDOWN_SEC,
                "max_spawn_points_per_zone": event_manager.MAX_SPAWN_POINTS_PER_ZONE,
                "max_zombies_per_spawn_point": event_manager.MAX_ZOMBIES_PER_SPAWN_POINT,
            },
        },
    )


@app.post("/spawnpoints")
async def spawnpoints_save(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    form = await request.form()
    ids = form.getlist("id")
    names = form.getlist("name")
    xs = form.getlist("x")
    ys = form.getlist("y")
    zs = form.getlist("z")
    created_bys = form.getlist("created_by")
    enableds = form.getlist("enabled")

    new_id = dynamic_spawnpoints.next_id(dynamic_spawnpoints.parse_file(SPAWNPOINTS_PATH))
    entries = []
    skipped = 0
    for id_str, name, x_str, y_str, z_str, created_by, enabled_str in zip_longest(
        ids, names, xs, ys, zs, created_bys, enableds, fillvalue=""
    ):
        name = name.strip()
        if not name:
            continue
        try:
            x, y = int(x_str), int(y_str)
        except ValueError:
            skipped += 1
            continue
        try:
            z = int(z_str)
        except ValueError:
            z = 0
        if id_str.strip().lstrip("-").isdigit():
            row_id = int(id_str)
        else:
            row_id = new_id
            new_id += 1
        entries.append(
            {
                "id": row_id,
                "name": name,
                "x": x,
                "y": y,
                "z": z,
                "created_by": created_by.strip() or user.username,
                "enabled": enabled_str != "0",
            }
        )

    dynamic_spawnpoints.write_file(SPAWNPOINTS_PATH, entries)
    await _audit(request, "spawnpoints_save", user.username, detail=f"{len(entries)} spawn points")
    flash = f"Saved {len(entries)} spawn points."
    if skipped:
        flash += f" Skipped {skipped} row(s) with invalid X/Y coordinates."
    request.session["flash"] = flash
    return RedirectResponse("/spawnpoints", status_code=303)


@app.post("/spawnpoints/zones")
async def event_zones_save(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    form = await request.form()
    ids = form.getlist("zone_id")
    names = form.getlist("zone_name")
    xs = form.getlist("zone_x")
    ys = form.getlist("zone_y")
    zs = form.getlist("zone_z")
    radii = form.getlist("zone_radius")
    cooldowns = form.getlist("zone_cooldown_sec")
    outfits = form.getlist("zone_outfit_name")
    female_chances = form.getlist("zone_female_chance")
    sprinter_chances = form.getlist("zone_sprinter_chance")
    points_jsons = form.getlist("zone_spawn_points_json")

    existing_zones = event_manager.read_zones(EVENT_TRIGGER_ZONES_PATH)
    existing_points = event_manager.read_spawn_points(EVENT_SPAWN_POINTS_PATH)
    new_zone_id = event_manager.next_id(existing_zones)
    new_point_id = event_manager.next_id(existing_points)

    zones = []
    all_points = []
    skipped_zones = 0
    skipped_points = 0
    for id_str, name, x_str, y_str, z_str, radius_str, cooldown_str, outfit, female_str, sprinter_str, points_json in zip_longest(
        ids, names, xs, ys, zs, radii, cooldowns, outfits, female_chances, sprinter_chances, points_jsons, fillvalue=""
    ):
        name = name.strip()
        if not name:
            continue
        try:
            x, y, z = int(x_str), int(y_str), int(z_str)
        except ValueError:
            skipped_zones += 1
            continue
        try:
            radius = int(radius_str)
        except ValueError:
            radius = event_manager.MIN_ZONE_RADIUS
        radius = max(event_manager.MIN_ZONE_RADIUS, min(event_manager.MAX_ZONE_RADIUS, radius))
        try:
            cooldown_sec = max(event_manager.MIN_ZONE_COOLDOWN_SEC, int(cooldown_str))
        except ValueError:
            cooldown_sec = event_manager.MIN_ZONE_COOLDOWN_SEC
        try:
            female_chance = max(0, min(100, int(female_str)))
        except ValueError:
            female_chance = 0
        try:
            sprinter_chance = max(0, min(100, int(sprinter_str)))
        except ValueError:
            sprinter_chance = 0

        if id_str.strip().lstrip("-").isdigit():
            zone_id = int(id_str)
        else:
            zone_id = new_zone_id
            new_zone_id += 1

        zones.append(
            {
                "id": zone_id,
                "name": name,
                "x": x,
                "y": y,
                "z": z,
                "radius": radius,
                "cooldown_sec": cooldown_sec,
                "outfit_name": outfit.strip(),
                "female_chance": female_chance,
                "sprinter_chance": sprinter_chance,
                "created_by": user.username,
            }
        )

        try:
            raw_points = json.loads(points_json) if points_json else []
        except (json.JSONDecodeError, TypeError):
            raw_points = []
        if not isinstance(raw_points, list):
            raw_points = []
        for raw in raw_points[: event_manager.MAX_SPAWN_POINTS_PER_ZONE]:
            try:
                px, py, pz = int(raw.get("x")), int(raw.get("y")), int(raw.get("z"))
                zombie_count = int(raw.get("zombie_count"))
                jitter_radius = int(raw.get("jitter_radius"))
            except (TypeError, ValueError):
                skipped_points += 1
                continue
            if zombie_count <= 0 or jitter_radius < 0:
                skipped_points += 1
                continue
            zombie_count = min(zombie_count, event_manager.MAX_ZOMBIES_PER_SPAWN_POINT)

            id_val = raw.get("id")
            if isinstance(id_val, (int, str)) and str(id_val).strip().isdigit():
                point_id = int(id_val)
            else:
                point_id = new_point_id
                new_point_id += 1

            all_points.append(
                {
                    "id": point_id,
                    "zone_id": zone_id,
                    "x": px,
                    "y": py,
                    "z": pz,
                    "zombie_count": zombie_count,
                    "jitter_radius": jitter_radius,
                    "created_by": user.username,
                }
            )
        if len(raw_points) > event_manager.MAX_SPAWN_POINTS_PER_ZONE:
            skipped_points += len(raw_points) - event_manager.MAX_SPAWN_POINTS_PER_ZONE

    event_manager.write_zones(EVENT_TRIGGER_ZONES_PATH, zones)
    event_manager.write_spawn_points(EVENT_SPAWN_POINTS_PATH, all_points)
    await _audit(
        request, "event_zones_save", user.username,
        detail=f"{len(zones)} trigger zones, {len(all_points)} spawn points",
    )
    flash = f"Saved {len(zones)} trigger zones and {len(all_points)} spawn points."
    if skipped_zones:
        flash += f" Skipped {skipped_zones} zone(s) with invalid coordinates."
    if skipped_points:
        flash += f" Skipped {skipped_points} spawn point(s) (invalid or over the per-zone limit)."
    request.session["flash"] = flash
    return RedirectResponse("/spawnpoints", status_code=303)


def _selected_shop_types(types: list[str] | None) -> list[str]:
    return [t for t in (types or []) if t in player_shops.TYPES]


@app.get("/playershops", response_class=HTMLResponse)
def playershops_page(
    request: Request,
    lines: int = DEFAULT_LOG_LINES,
    types: list[str] | None = Query(None),
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    lines = max(10, min(lines, MAX_LOG_LINES))
    selected = _selected_shop_types(types)
    entries = player_shops.read_transactions(PLAYERSHOPS_LOG_PATH, lines, selected) if FEATURE_SHOPS else []
    return templates.TemplateResponse(
        request,
        "playershops.html",
        {
            "active": "playershops",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(PLAYERSHOPS_LOG_PATH),
            "lines": lines,
            "all_types": player_shops.TYPES,
            "selected_types": selected,
            "entries": entries,
        },
    )


@app.get("/playershops/raw")
def playershops_raw(
    request: Request,
    lines: int = DEFAULT_LOG_LINES,
    types: list[str] | None = Query(None),
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return JSONResponse([], status_code=401)
    lines = max(10, min(lines, MAX_LOG_LINES))
    selected = _selected_shop_types(types)
    entries = player_shops.read_transactions(PLAYERSHOPS_LOG_PATH, lines, selected)
    return JSONResponse(entries)


@app.get("/shops", response_class=HTMLResponse)
def shops_page(
    request: Request,
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    shops = admin_shops.read_shops(ADMIN_SHOP_REGISTRY_PATH) if FEATURE_SHOPS else []
    return templates.TemplateResponse(
        request,
        "shops.html",
        {
            "active": "shops",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(ADMIN_SHOP_REGISTRY_PATH),
            "all_types": admin_shops.TYPES,
            "shops": shops,
        },
    )


@app.get("/shops/items-index.json")
def shops_items_index(user: User | None = Depends(current_user_optional)):
    if not user:
        return Response(status_code=401)
    return JSONResponse(
        items_index.client_index(),
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.post("/shops")
async def shops_save(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    form = await request.form()
    ids = form.getlist("id")
    types = form.getlist("type")
    xs = form.getlist("x")
    ys = form.getlist("y")
    zs = form.getlist("z")
    location_ids = form.getlist("location_id")
    reserveds = form.getlist("reserved")
    names = form.getlist("name")
    owners = form.getlist("owner")
    stock_jsons = form.getlist("stock_json")

    shops = []
    skipped = 0
    for id_str, type_, x_str, y_str, z_str, location_id, reserved, name, owner, stock_json in zip_longest(
        ids, types, xs, ys, zs, location_ids, reserveds, names, owners, stock_jsons, fillvalue=""
    ):
        try:
            row_id, x, y, z = int(id_str), int(x_str), int(y_str), int(z_str)
        except ValueError:
            skipped += 1
            continue
        try:
            raw_stock = json.loads(stock_json) if stock_json else []
        except (json.JSONDecodeError, TypeError):
            raw_stock = []
        stock = []
        for entry in raw_stock if isinstance(raw_stock, list) else []:
            item = str(entry.get("item") or "").strip()
            if not item:
                continue
            try:
                price = int(entry.get("price"))
            except (TypeError, ValueError):
                continue
            if price < 0:
                continue
            stock.append({"item": item, "price": price})
        shops.append(
            {
                "id": row_id,
                "type": type_,
                "x": x,
                "y": y,
                "z": z,
                "location_id": location_id,
                "reserved": reserved,
                "name": name,
                "owner": owner,
                "stock": stock,
            }
        )

    admin_shops.write_shops(ADMIN_SHOP_REGISTRY_PATH, shops)
    await _audit(request, "shops_save", user.username, detail=f"{len(shops)} shops")
    flash = f"Saved {len(shops)} shops."
    if skipped:
        flash += f" Skipped {skipped} row(s) with invalid data."
    request.session["flash"] = flash
    return RedirectResponse("/shops", status_code=303)


@app.get("/shops/map-preview")
async def shops_map_preview(
    x: float,
    y: float,
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return Response(status_code=401)
    data = await asyncio.to_thread(map_preview.render_preview, x, y, LOGS_DIR)
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=60"},
    )


def _selected_log_categories(categories: list[str] | None) -> list[str]:
    selected = [c for c in (categories or []) if c in log_tables.CATEGORIES]
    return selected or log_tables.DEFAULT_CATEGORIES


@app.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request,
    lines: int = DEFAULT_LOG_LINES,
    categories: list[str] | None = Query(None),
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    lines = max(10, min(lines, MAX_LOG_LINES))
    selected = _selected_log_categories(categories)
    entries = log_tables.read_logs(LOGS_DIR, selected, lines)
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "active": "logs",
            "subtab": "server",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(LOGS_DIR),
            "lines": lines,
            "all_categories": log_tables.CATEGORIES,
            "selected_categories": selected,
            "entries": entries,
        },
    )


@app.get("/logs/raw")
def logs_raw(
    request: Request,
    lines: int = DEFAULT_LOG_LINES,
    categories: list[str] | None = Query(None),
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return JSONResponse([], status_code=401)
    lines = max(10, min(lines, MAX_LOG_LINES))
    selected = _selected_log_categories(categories)
    entries = log_tables.read_logs(LOGS_DIR, selected, lines)
    return JSONResponse(entries)


@app.get("/battlepass", response_class=HTMLResponse)
def battlepass_page(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "battlepass.html",
        {
            "active": "battlepass",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "data_path": str(BATTLEPASS_DATA_PATH),
            "leaderboard": _load_battlepass_leaderboard() if FEATURE_BATTLEPASS else None,
            "kill_leaderboard": _kill_leaderboard() if FEATURE_PLAYER_LOCATIONS else [],
        },
    )


@app.get("/battlepass/player/{username}", response_class=HTMLResponse)
def battlepass_player_page(
    request: Request, username: str, user: User | None = Depends(current_user_optional)
):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    if not FEATURE_BATTLEPASS:
        request.session["flash"] = "Battle Pass is disabled in Settings."
        return RedirectResponse("/battlepass", status_code=303)
    raw_data = battlepass_data.load_battlepass_data(BATTLEPASS_DATA_PATH)
    detail = battlepass_data.build_player_detail(raw_data, username) if raw_data else None
    if detail is None:
        request.session["flash"] = f"No battle pass data found for '{username}'."
        return RedirectResponse("/battlepass", status_code=303)
    return templates.TemplateResponse(
        request,
        "battlepass_player.html",
        {
            "active": "battlepass",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "player": detail,
        },
    )


@app.get("/logs/battlepass", response_class=HTMLResponse)
def battlepass_logs_page(
    request: Request,
    lines: int = 200,
    file: str | None = None,
    player: str | None = None,
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    lines = max(10, min(lines, 2000))
    if FEATURE_BATTLEPASS:
        entries, file_names = battlepass_logs.read_battlepass_logs(
            LOGS_DIR, lines, file_name=file, player_filter=player or None
        )
    else:
        entries, file_names = [], []
    return templates.TemplateResponse(
        request,
        "logs_battlepass.html",
        {
            "active": "logs",
            "subtab": "battlepass",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "lines": lines,
            "entries": entries,
            "file_names": file_names,
            "selected_file": file or (file_names[0] if file_names else ""),
            "player_filter": player or "",
        },
    )


@app.get("/logs/battlepass/raw")
def battlepass_logs_raw(
    request: Request,
    lines: int = 200,
    file: str | None = None,
    player: str | None = None,
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return JSONResponse([], status_code=401)
    lines = max(10, min(lines, 2000))
    entries, _ = battlepass_logs.read_battlepass_logs(
        LOGS_DIR, lines, file_name=file, player_filter=player or None
    )
    return JSONResponse(entries)


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    users = db_stats.list_users(PLAYER_DB_PATH)
    characters = db_stats.list_characters(SAVE_DB_PATH)
    death_tracker.scan_logs(DEATH_LOG_PATH, DEATHS_DB_PATH)
    death_counts = death_tracker.get_death_counts(DEATHS_DB_PATH)
    if FEATURE_PLAYER_LOCATIONS:
        locations = {
            u["username"].lower(): player_locations.latest_location(u["username"], PLAYER_LOCATIONS_DIR)
            for u in users
        }
        kill_tallies = player_locations.all_kill_tallies(PLAYER_LOCATIONS_DIR)
    else:
        locations, kill_tallies = {}, {}
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "active": "stats",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(PLAYER_DB_PATH),
            "db_exists": PLAYER_DB_PATH.exists(),
            "users": users,
            "characters": characters,
            "death_counts": death_counts,
            "kill_tallies": kill_tallies,
            "locations": locations,
            "access_levels": rcon_commands.ACCESS_LEVELS,
        },
    )


@app.get("/stats/players")
def stats_players(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return JSONResponse({}, status_code=401)
    try:
        players = rcon_client.list_players(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        return JSONResponse({"players": players, "error": None})
    except Exception as exc:
        return JSONResponse({"players": [], "error": str(exc)})


@app.get("/player/{username}", response_class=HTMLResponse)
def player_detail_page(
    request: Request,
    username: str,
    start: float | None = None,
    end: float | None = None,
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)

    characters = db_stats.list_characters(SAVE_DB_PATH)
    character = characters.get(username.lower())

    death_tracker.scan_logs(DEATH_LOG_PATH, DEATHS_DB_PATH)
    deaths = death_tracker.get_deaths_for_user(DEATHS_DB_PATH, username)

    battlepass = None
    if FEATURE_BATTLEPASS:
        raw_bp = battlepass_data.load_battlepass_data(BATTLEPASS_DATA_PATH)
        battlepass = battlepass_data.build_player_detail(raw_bp, username) if raw_bp else None

    all_locations, filtered_locations, recent_locations = [], [], []
    kill_tally = None
    map_config = None
    trail_points_json = "[]"
    MAX_TRAIL_POINTS = 2000
    if FEATURE_PLAYER_LOCATIONS:
        all_locations = player_locations.read_location_history(username, PLAYER_LOCATIONS_DIR)
        filtered_locations = player_locations.filter_by_timeframe(all_locations, start, end)
        recent_locations = list(reversed(filtered_locations[-50:]))
        for loc in recent_locations:
            if loc.get("action") == "picked_up" and loc.get("item"):
                loc["icon_url"] = items_index.icon_url(loc["item"])
                loc["display_name"] = items_index.display_name(loc["item"], loc["item"])

        kill_tally = player_locations.read_kill_tally(username, PLAYER_LOCATIONS_DIR)

        trail_source = filtered_locations[-MAX_TRAIL_POINTS:]
        if trail_source:
            try:
                image_points = map_preview.world_points_to_image(
                    [(e["x"], e["y"]) for e in trail_source], LOGS_DIR
                )
                trail_points = []
                for (px, py), e in zip(image_points, trail_source):
                    point = {"px": px, "py": py, "t": e["lastUpdated"], "action": e.get("action", "tick")}
                    if point["action"] == "picked_up" and e.get("item"):
                        point["item"] = e["item"]
                        point["itemName"] = items_index.display_name(e["item"], e["item"])
                        point["icon"] = items_index.icon_url(e["item"])
                    elif point["action"] == "killed_zombie" and e.get("totalKills") is not None:
                        point["totalKills"] = e["totalKills"]
                    trail_points.append(point)
                trail_points_json = json.dumps(trail_points)
                map_config = map_preview.get_map_config(LOGS_DIR)
            except Exception:
                map_config = None

    return templates.TemplateResponse(
        request,
        "player_detail.html",
        {
            "active": "stats",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "username": username,
            "character": character,
            "deaths": deaths,
            "battlepass": battlepass,
            "locations": recent_locations,
            "kill_tally": kill_tally,
            "filtered_location_count": len(filtered_locations),
            "total_location_count": len(all_locations),
            "start": start,
            "end": end,
            "map_config": map_config,
            "map_config_json": json.dumps(map_config) if map_config else "null",
            "trail_points_json": trail_points_json,
            "trail_points_truncated": len(filtered_locations) > MAX_TRAIL_POINTS,
            "max_trail_points": MAX_TRAIL_POINTS,
        },
    )


@app.post("/player/{username}/clear-location")
async def player_clear_location(
    request: Request,
    username: str,
    start: float | None = Form(None),
    end: float | None = Form(None),
    user: User | None = Depends(current_user_optional),
):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    removed = await asyncio.to_thread(
        player_locations.clear_location_history, username, PLAYER_LOCATIONS_DIR, start, end
    )
    scope = "all" if start is None and end is None else "selected range"
    await _audit(
        request,
        "player_location_clear",
        user.username,
        detail=f"{username}: removed {removed} entries ({scope})",
    )
    request.session["flash"] = f"Cleared {removed} location entries for '{username}'."
    return RedirectResponse(f"/player/{username}", status_code=303)


@app.get("/status/raw")
def status_raw(request: Request):
    return JSONResponse(combined_server_status())


@app.post("/rcon/save")
async def rcon_save(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    try:
        response = rcon_client.execute(RCON_HOST, RCON_PORT, RCON_PASSWORD, "save")
        request.session["flash"] = f"Save command sent via RCON: {response or 'OK'}"
        await _audit(request, "rcon_save", user.username)
    except Exception as exc:
        request.session["flash"] = f"Failed to send save command via RCON: {exc}"
        await _audit(request, "rcon_save", user.username, detail=str(exc), success=False)
    referer = request.headers.get("referer", "/server")
    return RedirectResponse(referer, status_code=303)


@app.get("/remote", response_class=HTMLResponse)
def remote_page(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "remote.html",
        {
            "active": "remote",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "commands": rcon_commands.COMMANDS,
        },
    )


def _classify_remote_command(command: str) -> str:
    """Best-effort semantic label for a raw RCON command string, since
    /remote/run is used generically for the console, access-level changes
    (Players page), and teleports (Players page)."""
    first_word = command.strip().split(" ", 1)[0].lower()
    if first_word == "setaccesslevel":
        return "access_level_change"
    if first_word == "teleportplayer":
        return "teleport"
    return "remote_run"


@app.post("/remote/run")
async def remote_run(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    command = (body.get("command") or "").strip()
    if not command:
        return JSONResponse({"error": "No command given"}, status_code=400)
    action = _classify_remote_command(command)
    try:
        response = rcon_client.execute(RCON_HOST, RCON_PORT, RCON_PASSWORD, command)
        await _audit(request, action, user.username, detail=command)
        return JSONResponse({"response": response, "error": None})
    except Exception as exc:
        await _audit(request, action, user.username, detail=command, success=False)
        return JSONResponse({"response": None, "error": str(exc)})


def _read_last_wipe() -> dict | None:
    if not LAST_WIPE_PATH.exists():
        return None
    try:
        return json.loads(LAST_WIPE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_last_wipe(wipe_world: bool, wipe_players: bool) -> None:
    LAST_WIPE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_WIPE_PATH.write_text(
        json.dumps({"epoch": time.time(), "wipe_world": wipe_world, "wipe_players": wipe_players})
    )


@app.post("/wipe")
async def wipe_server(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    wipe_world = bool(body.get("wipe_world", True))
    wipe_players = bool(body.get("wipe_players", False))

    steps: list[str] = []

    try:
        await asyncio.to_thread(docker_control.stop_container)
        steps.append("Server stopped.")
    except Exception as exc:
        await _audit(
            request, "wipe", user.username,
            detail=f"world={wipe_world} players={wipe_players}: failed to stop server: {exc}",
            success=False,
        )
        return JSONResponse({"error": f"Failed to stop server: {exc}"})

    if wipe_world:
        save_dir = CONFIG_DIR / "Saves" / "Multiplayer" / SERVER_NAME
        try:
            if save_dir.exists():
                shutil.rmtree(save_dir)
            steps.append("World data deleted.")
        except Exception as exc:
            steps.append(f"Warning: could not delete world data: {exc}")
        try:
            if DEATHS_DB_PATH.exists():
                DEATHS_DB_PATH.unlink()
            steps.append("Death records cleared.")
        except Exception as exc:
            steps.append(f"Warning: could not clear death records: {exc}")

    if wipe_players:
        try:
            if PLAYER_DB_PATH.exists():
                PLAYER_DB_PATH.unlink()
            steps.append("Player database deleted.")
        except Exception as exc:
            steps.append(f"Warning: could not delete player database: {exc}")

    _write_last_wipe(wipe_world, wipe_players)

    try:
        await asyncio.to_thread(docker_control.start_container)
        steps.append("Server started.")
    except Exception as exc:
        steps.append(f"Warning: could not start server: {exc}")

    await _audit(
        request, "wipe", user.username,
        detail=f"world={wipe_world} players={wipe_players}: {' '.join(steps)}",
    )
    return JSONResponse({"message": " ".join(steps), "error": None})


@app.post("/restart")
async def restart_server(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return JSONResponse({"message": None, "error": "Not logged in."}, status_code=401)
    try:
        status = await asyncio.to_thread(docker_control.restart_pz_container)
        await _audit(request, "restart", user.username)
        return JSONResponse(
            {"message": f"Restart signal sent to '{PZ_CONTAINER_NAME}' (status: {status}).", "error": None}
        )
    except Exception as exc:
        await _audit(request, "restart", user.username, detail=str(exc), success=False)
        return JSONResponse({"message": None, "error": str(exc)})


def _require_admin(request: Request, user: User | None) -> RedirectResponse | None:
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    if not user.is_superuser:
        request.session["flash"] = "You don't have permission to manage users."
        return RedirectResponse("/", status_code=303)
    return None


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: User | None = Depends(current_user_optional)):
    denied = _require_admin(request, user)
    if denied:
        return denied
    activity = await asyncio.to_thread(audit_log.last_activity, AUDIT_DB_PATH)
    users = [
        {
            "id": u.id,
            "username": u.username,
            "is_superuser": u.is_superuser,
            "is_active": u.is_active,
            "last_login_epoch": activity.get(u.username, {}).get("last_login_epoch"),
            "last_activity_epoch": activity.get(u.username, {}).get("last_activity_epoch"),
        }
        for u in await list_users()
    ]
    env_settings = {
        "PZ_CONTAINER_NAME": PZ_CONTAINER_NAME,
        "SERVER_NAME": SERVER_NAME,
        "RCON_HOST": RCON_HOST,
        "RCON_PORT": RCON_PORT,
        "CONNECT_HOST": CONNECT_HOST,
        "DEATH_SCAN_INTERVAL_SECONDS": DEATH_SCAN_INTERVAL_SECONDS,
        "MOD_TITLES_REFRESH_INTERVAL_SECONDS": MOD_TITLES_REFRESH_INTERVAL_SECONDS,
    }
    paths = {
        "CONFIG_DIR": str(CONFIG_DIR),
        "APP_DATA_DIR": str(APP_DATA_DIR),
        "SERVER_INI_PATH": str(SERVER_INI_PATH),
        "SANDBOX_LUA_PATH": str(SANDBOX_LUA_PATH),
        "PLAYER_DB_PATH": str(PLAYER_DB_PATH),
        "SAVE_DB_PATH": str(SAVE_DB_PATH),
        "LOGS_DIR": str(LOGS_DIR),
        "DEATH_LOG_PATH": str(DEATH_LOG_PATH),
        "BATTLEPASS_DATA_PATH": str(BATTLEPASS_DATA_PATH),
        "SPAWNPOINTS_PATH": str(SPAWNPOINTS_PATH),
        "PLAYERSHOPS_LOG_PATH": str(PLAYERSHOPS_LOG_PATH),
        "ADMIN_SHOP_REGISTRY_PATH": str(ADMIN_SHOP_REGISTRY_PATH),
        "EVENT_TRIGGER_ZONES_PATH": str(EVENT_TRIGGER_ZONES_PATH),
        "EVENT_SPAWN_POINTS_PATH": str(EVENT_SPAWN_POINTS_PATH),
    }
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active": "settings",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "users": users,
            "current_user_id": str(user.id),
            "env_settings": env_settings,
            "paths": paths,
            "features": {
                "battlepass": FEATURE_BATTLEPASS,
                "shops": FEATURE_SHOPS,
                "spawnpoints": FEATURE_SPAWNPOINTS,
                "player_locations": FEATURE_PLAYER_LOCATIONS,
            },
            "required_mods": _required_mods_status(),
        },
    )


@app.post("/settings/features")
async def settings_save_features(
    request: Request,
    feature_battlepass: bool = Form(False),
    feature_shops: bool = Form(False),
    feature_spawnpoints: bool = Form(False),
    feature_player_locations: bool = Form(False),
    user: User | None = Depends(current_user_optional),
):
    denied = _require_admin(request, user)
    if denied:
        return denied

    values = {
        "FEATURE_BATTLEPASS": feature_battlepass,
        "FEATURE_SHOPS": feature_shops,
        "FEATURE_SPAWNPOINTS": feature_spawnpoints,
        "FEATURE_PLAYER_LOCATIONS": feature_player_locations,
    }
    old = {
        "FEATURE_BATTLEPASS": FEATURE_BATTLEPASS,
        "FEATURE_SHOPS": FEATURE_SHOPS,
        "FEATURE_SPAWNPOINTS": FEATURE_SPAWNPOINTS,
        "FEATURE_PLAYER_LOCATIONS": FEATURE_PLAYER_LOCATIONS,
    }

    _apply_runtime_config(values)

    stored = _load_runtime_config_overrides()
    stored.update(values)
    RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG_PATH.write_text(json.dumps(stored))

    diffs = [f"{k}: {old[k]!r} -> {values[k]!r}" for k in old if old[k] != values[k]]
    await _audit(request, "feature_flags_save", user.username, detail=_format_diff_detail(diffs))
    request.session["flash"] = "Feature settings saved."
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/environment")
async def settings_save_environment(
    request: Request,
    pz_container_name: str = Form(...),
    server_name: str = Form(...),
    rcon_host: str = Form(...),
    rcon_port: str = Form(...),
    rcon_password: str = Form(""),
    connect_host: str = Form(""),
    death_scan_interval_seconds: str = Form(...),
    mod_titles_refresh_interval_seconds: str = Form(...),
    user: User | None = Depends(current_user_optional),
):
    denied = _require_admin(request, user)
    if denied:
        return denied

    values = {
        "PZ_CONTAINER_NAME": pz_container_name.strip(),
        "SERVER_NAME": server_name.strip(),
        "RCON_HOST": rcon_host.strip(),
        "RCON_PORT": rcon_port.strip(),
        "RCON_PASSWORD": rcon_password,
        "CONNECT_HOST": connect_host.strip(),
        "DEATH_SCAN_INTERVAL_SECONDS": death_scan_interval_seconds.strip(),
        "MOD_TITLES_REFRESH_INTERVAL_SECONDS": mod_titles_refresh_interval_seconds.strip(),
    }

    if not values["PZ_CONTAINER_NAME"] or not values["SERVER_NAME"] or not values["RCON_HOST"]:
        request.session["flash"] = "Container name, server name, and RCON host are required."
        return RedirectResponse("/settings", status_code=303)
    try:
        int(values["RCON_PORT"])
        int(values["DEATH_SCAN_INTERVAL_SECONDS"])
        int(values["MOD_TITLES_REFRESH_INTERVAL_SECONDS"])
    except ValueError:
        request.session["flash"] = "RCON port and interval fields must be whole numbers."
        return RedirectResponse("/settings", status_code=303)

    old = {
        "PZ_CONTAINER_NAME": PZ_CONTAINER_NAME,
        "SERVER_NAME": SERVER_NAME,
        "RCON_HOST": RCON_HOST,
        "RCON_PORT": RCON_PORT,
        "CONNECT_HOST": CONNECT_HOST,
        "DEATH_SCAN_INTERVAL_SECONDS": DEATH_SCAN_INTERVAL_SECONDS,
        "MOD_TITLES_REFRESH_INTERVAL_SECONDS": MOD_TITLES_REFRESH_INTERVAL_SECONDS,
    }

    _apply_runtime_config(values)

    stored = _load_runtime_config_overrides()
    stored.update({k: v for k, v in values.items() if k != "RCON_PASSWORD"})
    if values["RCON_PASSWORD"]:
        stored["RCON_PASSWORD"] = values["RCON_PASSWORD"]
    RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG_PATH.write_text(json.dumps(stored))

    new = {
        "PZ_CONTAINER_NAME": PZ_CONTAINER_NAME,
        "SERVER_NAME": SERVER_NAME,
        "RCON_HOST": RCON_HOST,
        "RCON_PORT": RCON_PORT,
        "CONNECT_HOST": CONNECT_HOST,
        "DEATH_SCAN_INTERVAL_SECONDS": DEATH_SCAN_INTERVAL_SECONDS,
        "MOD_TITLES_REFRESH_INTERVAL_SECONDS": MOD_TITLES_REFRESH_INTERVAL_SECONDS,
    }
    diffs = [f"{k}: {old[k]!r} -> {new[k]!r}" for k in old if old[k] != new[k]]
    if values["RCON_PASSWORD"]:
        diffs.append("RCON_PASSWORD: (changed)")
    await _audit(request, "env_settings_save", user.username, detail=_format_diff_detail(diffs))
    request.session["flash"] = "Environment settings saved."
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/users")
async def settings_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    is_superuser: str | None = Form(None),
    user: User | None = Depends(current_user_optional),
):
    denied = _require_admin(request, user)
    if denied:
        return denied
    username = username.strip()
    if not username or not password:
        request.session["flash"] = "Username and password are required."
    else:
        try:
            await create_user(username, password, is_superuser=bool(is_superuser))
            request.session["flash"] = f"Created user '{username}'."
            await _audit(request, "user_create", user.username, detail=username)
        except UsernameTakenError:
            request.session["flash"] = f"Username '{username}' is already taken."
            await _audit(request, "user_create", user.username, detail=username, success=False)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/users/{user_id}/toggle-active")
async def settings_toggle_active(
    request: Request,
    user_id: uuid.UUID,
    user: User | None = Depends(current_user_optional),
):
    denied = _require_admin(request, user)
    if denied:
        return denied
    target = await get_user_by_id(user_id)
    if target is None:
        request.session["flash"] = "User not found."
    elif target.id == user.id:
        request.session["flash"] = "You can't disable your own account."
    else:
        try:
            await set_user_active(user_id, not target.is_active)
            verb = "Enabled" if not target.is_active else "Disabled"
            request.session["flash"] = f"{verb} '{target.username}'."
            await _audit(request, "user_toggle_active", user.username, detail=target.username)
        except LastSuperuserError:
            request.session["flash"] = "Can't disable the last active admin."
            await _audit(request, "user_toggle_active", user.username, detail=target.username, success=False)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/users/{user_id}/toggle-superuser")
async def settings_toggle_superuser(
    request: Request,
    user_id: uuid.UUID,
    user: User | None = Depends(current_user_optional),
):
    denied = _require_admin(request, user)
    if denied:
        return denied
    target = await get_user_by_id(user_id)
    if target is None:
        request.session["flash"] = "User not found."
    elif target.id == user.id:
        request.session["flash"] = "You can't change your own admin status."
    else:
        try:
            await set_user_superuser(user_id, not target.is_superuser)
            verb = "Granted" if not target.is_superuser else "Revoked"
            request.session["flash"] = f"{verb} admin for '{target.username}'."
            await _audit(request, "user_toggle_superuser", user.username, detail=target.username)
        except LastSuperuserError:
            request.session["flash"] = "Can't remove the last active admin."
            await _audit(request, "user_toggle_superuser", user.username, detail=target.username, success=False)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/users/{user_id}/password")
async def settings_reset_password(
    request: Request,
    user_id: uuid.UUID,
    password: str = Form(...),
    user: User | None = Depends(current_user_optional),
):
    denied = _require_admin(request, user)
    if denied:
        return denied
    target = await get_user_by_id(user_id)
    if target is None:
        request.session["flash"] = "User not found."
    elif not password:
        request.session["flash"] = "Password can't be blank."
    else:
        await set_user_password(user_id, password)
        request.session["flash"] = f"Password updated for '{target.username}'."
        await _audit(request, "user_password_reset", user.username, detail=target.username)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/users/{user_id}/delete")
async def settings_delete_user(
    request: Request,
    user_id: uuid.UUID,
    user: User | None = Depends(current_user_optional),
):
    denied = _require_admin(request, user)
    if denied:
        return denied
    target = await get_user_by_id(user_id)
    if target is None:
        request.session["flash"] = "User not found."
    elif target.id == user.id:
        request.session["flash"] = "You can't delete your own account."
    else:
        try:
            await delete_user(user_id)
            request.session["flash"] = f"Deleted user '{target.username}'."
            await _audit(request, "user_delete", user.username, detail=target.username)
        except LastSuperuserError:
            request.session["flash"] = "Can't delete the last active admin."
            await _audit(request, "user_delete", user.username, detail=target.username, success=False)
    return RedirectResponse("/settings", status_code=303)


def _selected_audit_actions(actions: list[str] | None) -> list[str]:
    return [a for a in (actions or []) if a in audit_log.ACTIONS]


@app.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    limit: int = 200,
    actions: list[str] | None = Query(None),
    user: User | None = Depends(current_user_optional),
):
    denied = _require_admin(request, user)
    if denied:
        return denied
    limit = max(10, min(limit, 2000))
    selected = _selected_audit_actions(actions)
    entries = await asyncio.to_thread(audit_log.list_events, AUDIT_DB_PATH, limit, selected)
    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "active": "audit",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "limit": limit,
            "all_actions": audit_log.ACTIONS,
            "selected_actions": selected,
            "entries": entries,
        },
    )


@app.get("/audit/raw")
async def audit_raw(
    request: Request,
    limit: int = 200,
    actions: list[str] | None = Query(None),
    user: User | None = Depends(current_user_optional),
):
    denied = _require_admin(request, user)
    if denied:
        return JSONResponse([], status_code=403)
    limit = max(10, min(limit, 2000))
    selected = _selected_audit_actions(actions)
    entries = await asyncio.to_thread(audit_log.list_events, AUDIT_DB_PATH, limit, selected)
    return JSONResponse(entries)
