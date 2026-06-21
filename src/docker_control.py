import os

import docker

PZ_CONTAINER_NAME = os.environ.get("PZ_CONTAINER_NAME", "projectzomboid")


def restart_pz_container() -> str:
    client = docker.from_env()
    container = client.containers.get(PZ_CONTAINER_NAME)
    container.restart(timeout=30)
    container.reload()
    return container.status


def get_status() -> dict:
    """Return status info for the PZ container: status, health (if any), and started-at time."""
    try:
        client = docker.from_env()
        container = client.containers.get(PZ_CONTAINER_NAME)
        state = container.attrs.get("State", {})
        health = state.get("Health", {}).get("Status")
        return {
            "status": container.status,
            "health": health,
            "started_at": state.get("StartedAt"),
            "error": None,
        }
    except docker.errors.NotFound:
        return {"status": "not_found", "health": None, "started_at": None, "error": "Container not found"}
    except Exception as exc:
        return {"status": "unknown", "health": None, "started_at": None, "error": str(exc)}
