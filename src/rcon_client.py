import socket
import struct

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2


class RconError(Exception):
    pass


def _pack(packet_id: int, pkt_type: int, body: str) -> bytes:
    payload = struct.pack("<ii", packet_id, pkt_type) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RconError("Connection closed by RCON server")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_packet(sock: socket.socket) -> tuple[int, int, bytes]:
    size = struct.unpack("<i", _recv_exact(sock, 4))[0]
    payload = _recv_exact(sock, size)
    packet_id, pkt_type = struct.unpack("<ii", payload[:8])
    body = payload[8:-2]
    return packet_id, pkt_type, body


def execute(host: str, port: int, password: str, command: str, timeout: float = 5.0) -> str:
    """Open a connection, authenticate, run one command, and return its text response."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(_pack(1, SERVERDATA_AUTH, password))
        packet_id, pkt_type, _ = _read_packet(sock)
        if pkt_type != SERVERDATA_AUTH_RESPONSE:
            # Some servers send an empty SERVERDATA_RESPONSE_VALUE before the real auth response.
            packet_id, pkt_type, _ = _read_packet(sock)
        if packet_id == -1:
            raise RconError("RCON authentication failed (wrong password?)")

        sock.sendall(_pack(2, SERVERDATA_EXECCOMMAND, command))
        sock.settimeout(min(timeout, 1.5))
        parts = []
        try:
            while True:
                _, _, body = _read_packet(sock)
                parts.append(body)
        except socket.timeout:
            pass
        return b"".join(parts).decode("utf-8", errors="replace").rstrip("\x00")


def list_players(host: str, port: int, password: str) -> list[str]:
    """Return the list of currently connected player usernames."""
    text = execute(host, port, password, "players")
    names = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("-"):
            names.append(line[1:].strip())
    return names
