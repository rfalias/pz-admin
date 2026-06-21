import asyncio
import os
from contextlib import asynccontextmanager
from itertools import zip_longest
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import db_stats
import death_tracker
import docker_control
import ini_config
import log_tables
import lua_config
import mod_parser
import rcon_client
import rcon_commands
from auth import verify_login

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
APP_DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "/app/data"))
DEATHS_DB_PATH = APP_DATA_DIR / "deaths.db"
DEATH_SCAN_INTERVAL_SECONDS = int(os.environ.get("DEATH_SCAN_INTERVAL_SECONDS", "60"))

DEFAULT_LOG_LINES = 100
MAX_LOG_LINES = 2000

BASE_DIR = Path(__file__).resolve().parent


async def _death_scan_loop():
    """Periodically parse *_user.txt logs for deaths, independent of anyone
    viewing the Stats page - so deaths aren't missed if a log file rotates
    (and its old copy is later cleaned up) between page visits."""
    while True:
        try:
            await asyncio.to_thread(death_tracker.scan_logs, LOGS_DIR, DEATHS_DB_PATH)
        except Exception:
            pass
        await asyncio.sleep(DEATH_SCAN_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_death_scan_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="PZ Admin", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def current_user(request: Request) -> str | None:
    return request.session.get("user")


def pop_flash(request: Request) -> str | None:
    return request.session.pop("flash", None)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if verify_login(username, password):
        request.session["user"] = username
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": "Invalid username or password"}, status_code=401
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/")
def index(request: Request):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/server", status_code=303)


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
            "deaths": death_tracker.get_death_leaderboard(DEATHS_DB_PATH),
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
    return JSONResponse(
        {
            "status": status.get("status"),
            "started_at": status.get("started_at"),
            "players": players,
            "rcon_error": rcon_error,
        }
    )


@app.get("/server", response_class=HTMLResponse)
def server_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    entries = ini_config.parse_ini(SERVER_INI_PATH)
    return templates.TemplateResponse(
        request,
        "server.html",
        {
            "active": "server",
            "user": user,
            "entries": entries,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(SERVER_INI_PATH),
            "mods_warning": ini_config.validate_mods(entries),
        },
    )


@app.post("/server")
async def server_save(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
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
def mods_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    entries = ini_config.parse_ini(SERVER_INI_PATH)
    mod_ids = ini_config.split_list(ini_config.get_value(entries, "Mods"))
    workshop_ids = ini_config.split_list(ini_config.get_value(entries, "WorkshopItems"))
    rows = list(zip_longest(mod_ids, workshop_ids, fillvalue=""))
    return templates.TemplateResponse(
        request,
        "mods.html",
        {
            "active": "mods",
            "user": user,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(SERVER_INI_PATH),
            "rows": rows,
            "mods_warning": ini_config.validate_mods(entries),
        },
    )


@app.post("/mods")
async def mods_save(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
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
    )
    ini_config.write_ini(SERVER_INI_PATH, entries)
    flash = "Mods saved. Restart the server to apply changes."
    mods_warning = ini_config.validate_mods(entries)
    if mods_warning:
        flash += f" Warning: {mods_warning}"
    request.session["flash"] = flash
    return RedirectResponse("/mods", status_code=303)


@app.post("/mods/import")
async def mods_import(request: Request):
    if not current_user(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    url = (body.get("url") or "").strip()
    workshop_id = mod_parser.extract_workshop_id(url)
    if not workshop_id:
        return JSONResponse({"error": "Could not find a workshop ID in that URL"}, status_code=400)
    mods, errors = await asyncio.to_thread(mod_parser.resolve_mod_tree, workshop_id)
    return JSONResponse({"mods": mods, "errors": errors})


@app.get("/sandbox", response_class=HTMLResponse)
def sandbox_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    entries, _ = lua_config.parse_sandbox(SANDBOX_LUA_PATH)
    return templates.TemplateResponse(
        request,
        "sandbox.html",
        {
            "active": "sandbox",
            "user": user,
            "entries": entries,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(SANDBOX_LUA_PATH),
        },
    )


@app.post("/sandbox")
async def sandbox_save(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
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
def logs_page(request: Request, lines: int = DEFAULT_LOG_LINES, categories: list[str] | None = Query(None)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    lines = max(10, min(lines, MAX_LOG_LINES))
    selected = _selected_log_categories(categories)
    entries = log_tables.read_logs(LOGS_DIR, selected, lines)
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "active": "logs",
            "user": user,
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
def logs_raw(request: Request, lines: int = DEFAULT_LOG_LINES, categories: list[str] | None = Query(None)):
    if not current_user(request):
        return JSONResponse([], status_code=401)
    lines = max(10, min(lines, MAX_LOG_LINES))
    selected = _selected_log_categories(categories)
    entries = log_tables.read_logs(LOGS_DIR, selected, lines)
    return JSONResponse(entries)


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    users = db_stats.list_users(PLAYER_DB_PATH)
    characters = db_stats.list_characters(SAVE_DB_PATH)
    death_tracker.scan_logs(LOGS_DIR, DEATHS_DB_PATH)
    death_counts = death_tracker.get_death_counts(DEATHS_DB_PATH)
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "active": "stats",
            "user": user,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "config_path": str(PLAYER_DB_PATH),
            "db_exists": PLAYER_DB_PATH.exists(),
            "users": users,
            "characters": characters,
            "death_counts": death_counts,
        },
    )


@app.get("/stats/players")
def stats_players(request: Request):
    if not current_user(request):
        return JSONResponse({}, status_code=401)
    try:
        players = rcon_client.list_players(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        return JSONResponse({"players": players, "error": None})
    except Exception as exc:
        return JSONResponse({"players": [], "error": str(exc)})


@app.get("/status/raw")
def status_raw(request: Request):
    return JSONResponse(docker_control.get_status())


@app.post("/rcon/save")
def rcon_save(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        response = rcon_client.execute(RCON_HOST, RCON_PORT, RCON_PASSWORD, "save")
        request.session["flash"] = f"Save command sent via RCON: {response or 'OK'}"
    except Exception as exc:
        request.session["flash"] = f"Failed to send save command via RCON: {exc}"
    referer = request.headers.get("referer", "/server")
    return RedirectResponse(referer, status_code=303)


@app.get("/remote", response_class=HTMLResponse)
def remote_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "remote.html",
        {
            "active": "remote",
            "user": user,
            "container": PZ_CONTAINER_NAME,
            "flash": pop_flash(request),
            "commands": rcon_commands.COMMANDS,
        },
    )


@app.post("/remote/run")
async def remote_run(request: Request):
    if not current_user(request):
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


@app.post("/restart")
def restart_server(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    try:
        status = docker_control.restart_pz_container()
        request.session["flash"] = f"Restart signal sent to '{PZ_CONTAINER_NAME}' (status: {status})."
    except Exception as exc:
        request.session["flash"] = f"Failed to restart '{PZ_CONTAINER_NAME}': {exc}"
    referer = request.headers.get("referer", "/server")
    return RedirectResponse(referer, status_code=303)
