# pz-admin

A FastAPI web app for managing a self-hosted Project Zomboid dedicated server:
edit server/sandbox settings, manage mods (with Steam Workshop URL import),
view logs, browse registered players and set their access level or teleport
them in-game, run arbitrary RCON commands, track a Battle Pass leaderboard,
manage admin accounts, and restart/save/wipe the server — all from a browser.

## Screenshots

**Public dashboard** — the default landing page for logged-out visitors:
server status, connect info, players online, and the full Battle Pass
leaderboard.

![Dashboard](screenshots/dashboard.png)

**Players** — registered players with live online status, quick access-level
changes and teleport-to-player, all sent over RCON.

![Players](screenshots/players.png)

**Battle Pass leaderboard** — parsed from the mod's exported player data,
ranked by points earned, with per-player tier/feat/quest progress.

![Battle Pass](screenshots/battlepass.png)

**Remote Control** — a form-driven builder for the full RCON command catalog,
or edit the raw command text directly.

![Remote Control](screenshots/remote.png)

**Settings** — add, disable, promote, reset the password for, or delete admin
accounts. Guards against locking yourself out of the last admin account.

![Settings](screenshots/settings.png)

## Features

- **Server / Sandbox** — edit `Server/<name>.ini` and `SandboxVars.lua`
  settings through generated forms.
- **Mods** — edit the mod/workshop ID list, with Steam Workshop URL import
  and dependency resolution.
- **Logs** — categorized server logs (user/chat/connections/admin/command/
  debug), plus a Battle Pass admin-log sub-tab.
- **Players** — registered (whitelisted) players, live online status via
  RCON, death counts, best-effort character info parsed from the save file,
  inline access-level changes (`setaccesslevel`) and teleport-to-player
  (`teleportplayer`) controls.
- **Battle Pass** — leaderboard built from the mod's `BattlePassPlayerData.json`
  export: points, balance, tier/feat/quest progress, lifetime stats, and
  top skills per player, plus "most points/crafted/deaths" highlights. The
  same leaderboard is shown on the public dashboard.
- **Remote Control** — a declarative catalog of RCON commands rendered as a
  form (with the right input type per argument), or edit the built command
  text directly before running it.
- **Settings** — admin user management: add users, promote/demote admin
  status, disable/enable accounts, reset passwords, delete users. Refuses
  any action that would leave zero active admins.
- **Dashboard** — public, unauthenticated landing page: server status,
  connect address, players online, and the full Battle Pass leaderboard,
  with a Login button through to the admin panel.
- **Server status** — the header badge is RCON-aware: a container the
  Docker daemon reports as "running" still shows **starting up** until RCON
  actually accepts connections, then flips to **server live**.
- **Save / Restart / Wipe** — save the world or restart the container from
  any page; a guarded wipe flow (world data and/or player database) stops
  the server, deletes the selected data, and restarts it.

## Auth

Accounts are stored in a local SQLite database (via
[fastapi-users](https://github.com/fastapi-users/fastapi-users)), with
Argon2-hashed passwords and revocable, database-backed sessions (a cookie
holding an opaque token, not a signed blob — logging out actually deletes
the token server-side).

### First run

There's no signup flow. To bootstrap the first admin account:

1. Copy `users.example.json` to `users.json` and set a real username/password.
2. On first boot, if the auth database is empty, that file is imported once
   (passwords get hashed on the way in) and never read again.
3. Once you can log in, manage all accounts from the **Settings** tab —
   `users.json` is no longer needed and can be deleted.

## Setup

1. Copy `users.example.json` to `users.json` and set real login credentials
   (see **Auth** above).
2. Edit `docker-compose.yml`:
   - Point the `CONFIG_DIR` volume at your real `project-zomboid-config` directory.
   - Set `SESSION_SECRET` to a real random string.
   - Set `RCON_PASSWORD` to your server's RCON password.
   - Set `CONNECT_HOST` to the address players should use to connect.
   - Update the Traefik labels (or remove them) for your own reverse proxy setup.
3. `docker compose up -d --build`

The app expects `PZ_CONTAINER_NAME` (default `projectzomboid`) to be the name
of your running game server container, and mounts `/var/run/docker.sock` so it
can restart it.
