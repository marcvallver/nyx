"""Cliente del socket de Nyx — stdlib pura (sin GTK).

Lo usan `nyx-ctl` y `nyx-bubble-capture` para hablar con el daemon. Protocolo:
una línea JSON por petición, una línea JSON de respuesta, y cierre.
"""

from __future__ import annotations

import json
import os
import socket


def socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "nyx.sock")


def send(obj: dict, timeout: float = 2.0) -> dict | None:
    """Envía `obj` al daemon y devuelve su respuesta (dict), o None si no responde."""
    path = socket_path()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
        s.sendall((json.dumps(obj) + "\n").encode())
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            try:
                buf = s.recv(4096)
            except socket.timeout:
                break
            if not buf:
                break
            chunks.append(buf)
        raw = b"".join(chunks).decode(errors="replace").strip()
        return json.loads(raw) if raw else {"ok": True}
    except (OSError, ValueError):
        return None
    finally:
        s.close()


def daemon_running() -> bool:
    return send({"op": "ping"}) is not None
