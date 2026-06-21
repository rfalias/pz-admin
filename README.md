# pz-admin

A small FastAPI web app for managing a self-hosted Project Zomboid dedicated
server: edit server/sandbox settings, manage mods (with Steam Workshop URL
import), view logs and player stats, run arbitrary RCON commands, and
restart/save the server, all from a browser.

## Setup

1. Copy `users.example.json` to `users.json` and set real login credentials.
2. Edit `docker-compose.yml`:
   - Point the `CONFIG_DIR` volume at your real `project-zomboid-config` directory.
   - Set `RCON_PASSWORD` to your server's RCON password.
   - Set `CONNECT_HOST` to the address players should use to connect.
   - Update the Traefik labels (or remove them) for your own reverse proxy setup.
3. `docker compose up -d --build`

The app expects `PZ_CONTAINER_NAME` (default `projectzomboid`) to be the name
of your running game server container, and mounts `/var/run/docker.sock` so it
can restart it.
