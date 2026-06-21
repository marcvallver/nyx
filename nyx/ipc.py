"""Servidor del socket UNIX de Nyx, integrado en el bucle GLib (Gio.SocketService).

El handler recibe (msg, reply): debe llamar a `reply(dict)` para responder — YA (ops
inmediatas) o MÁS TARDE (p.ej. `confirm`, que espera a que Marc decida en el popup;
la conexión se mantiene abierta mientras tanto). reply escribe una línea JSON y cierra.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from gi.repository import Gio, GLib


class SocketServer:
    def __init__(self, path: str, handler: Callable[[dict, Callable[[dict], None]], None]):
        self.path = path
        self.handler = handler
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
        self.service = Gio.SocketService.new()
        addr = Gio.UnixSocketAddress.new(path)
        self.service.add_address(addr, Gio.SocketType.STREAM, Gio.SocketProtocol.DEFAULT, None)
        self.service.connect("incoming", self._on_incoming)
        self.service.start()

    def _on_incoming(self, _service, conn, _src):
        dis = Gio.DataInputStream.new(conn.get_input_stream())
        dis.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line, conn)
        return False

    def _on_line(self, dis, res, conn):
        try:
            data, _len = dis.read_line_finish_utf8(res)
        except GLib.Error:
            data = None

        def reply(obj: dict) -> None:
            try:
                out = conn.get_output_stream()
                out.write_all((json.dumps(obj) + "\n").encode(), None)
                out.flush(None)
            except GLib.Error:
                pass
            try:
                conn.close(None)
            except GLib.Error:
                pass

        if data:
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                reply({"ok": False, "error": "bad json"})
                return
            if isinstance(msg, dict):
                try:
                    self.handler(msg, reply)  # el handler llama a reply (ahora o luego)
                except Exception as e:  # un handler no debe tumbar el servidor
                    reply({"ok": False, "error": repr(e)})
                return
        reply({"ok": False, "error": "bad request"})
