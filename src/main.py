import asyncio
import json
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from itertools import zip_longest
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import battlepass_data
import battlepass_logs
import db_stats
import death_tracker
import docker_control
import ini_config
import log_tables
import lua_config
import mod_parser
import mod_titles
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
APP_DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "/app/data"))
DEATHS_DB_PATH = APP_DATA_DIR / "deaths.db"
LAST_WIPE_PATH = APP_DATA_DIR / "last_wipe.json"
MOD_TITLES_CACHE_PATH = APP_DATA_DIR / "mod_titles.json"
DEATH_SCAN_INTERVAL_SECONDS = int(os.environ.get("DEATH_SCAN_INTERVAL_SECONDS", "60"))
MOD_TITLES_REFRESH_INTERVAL_SECONDS = int(os.environ.get("MOD_TITLES_REFRESH_INTERVAL_SECONDS", "3600"))
USERS_FILE = Path(os.environ.get("USERS_FILE", "/app/users.json"))

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
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid username or password"}, status_code=401
        )
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


def _load_installed_mods(entries: list) -> list[str]:
    """Friendly names of installed mods: cached Workshop title if known,
    else the raw mod ID/workshop ID as a fallback."""
    mod_ids = ini_config.split_list(ini_config.get_value(entries, "Mods"))
    workshop_ids = ini_config.split_list(ini_config.get_value(entries, "WorkshopItems"))
    titles = mod_titles.get_titles(MOD_TITLES_CACHE_PATH)
    names = []
    for mod_id, workshop_id in zip_longest(mod_ids, workshop_ids, fillvalue=""):
        if not mod_id and not workshop_id:
            continue
        names.append(titles.get(workshop_id) or mod_id or f"Workshop ID {workshop_id}")
    return names


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
            "leaderboard": _load_battlepass_leaderboard(),
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
    entries = ini_config.parse_ini(SERVER_INI_PATH)
    ini_config.apply_form(entries, form)
    ini_config.write_ini(SERVER_INI_PATH, entries)
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
    ini_config.apply_form(
        entries,
        {
            "Mods": ";".join(m for m, _ in pairs),
            "WorkshopItems": ";".join(w for _, w in pairs),
        },
        managed_keys={"Mods", "WorkshopItems"},
    )
    ini_config.write_ini(SERVER_INI_PATH, entries)
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
    return JSONResponse({"mods": mods, "errors": errors})


@app.get("/sandbox", response_class=HTMLResponse)
def sandbox_page(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    entries, _ = lua_config.parse_sandbox(SANDBOX_LUA_PATH)
    return templates.TemplateResponse(
        request,
        "sandbox.html",
        {
            "active": "sandbox",
            "user": user.username,
            "entries": entries,
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
    entries, var_name = lua_config.parse_sandbox(SANDBOX_LUA_PATH)
    lua_config.apply_form(entries, form)
    lua_config.write_sandbox(SANDBOX_LUA_PATH, entries, var_name)
    request.session["flash"] = "Sandbox settings saved. Restart the server to apply changes."
    return RedirectResponse("/sandbox", status_code=303)


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
            "leaderboard": _load_battlepass_leaderboard(),
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
    entries, file_names = battlepass_logs.read_battlepass_logs(
        LOGS_DIR, lines, file_name=file, player_filter=player or None
    )
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


@app.get("/status/raw")
def status_raw(request: Request):
    return JSONResponse(combined_server_status())


@app.post("/rcon/save")
def rcon_save(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    try:
        response = rcon_client.execute(RCON_HOST, RCON_PORT, RCON_PASSWORD, "save")
        request.session["flash"] = f"Save command sent via RCON: {response or 'OK'}"
    except Exception as exc:
        request.session["flash"] = f"Failed to send save command via RCON: {exc}"
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


@app.post("/remote/run")
async def remote_run(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    command = (body.get("command") or "").strip()
    if not command:
        return JSONResponse({"error": "No command given"}, status_code=400)
    try:
        response = rcon_client.execute(RCON_HOST, RCON_PORT, RCON_PASSWORD, command)
        return JSONResponse({"response": response, "error": None})
    except Exception as exc:
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

    return JSONResponse({"message": " ".join(steps), "error": None})


@app.post("/restart")
def restart_server(request: Request, user: User | None = Depends(current_user_optional)):
    if not user:
        return RedirectResponse("/dashboard", status_code=303)
    try:
        status = docker_control.restart_pz_container()
        request.session["flash"] = f"Restart signal sent to '{PZ_CONTAINER_NAME}' (status: {status})."
    except Exception as exc:
        request.session["flash"] = f"Failed to restart '{PZ_CONTAINER_NAME}': {exc}"
    referer = request.headers.get("referer", "/server")
    return RedirectResponse(referer, status_code=303)


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
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active": "settings",
            "user": user.username,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "users": await list_users(),
            "current_user_id": str(user.id),
        },
    )


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
        except UsernameTakenError:
            request.session["flash"] = f"Username '{username}' is already taken."
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
        except LastSuperuserError:
            request.session["flash"] = "Can't disable the last active admin."
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
        except LastSuperuserError:
            request.session["flash"] = "Can't remove the last active admin."
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
        except LastSuperuserError:
            request.session["flash"] = "Can't delete the last active admin."
    return RedirectResponse("/settings", status_code=303)
