"""Servidor del socket UNIX de Nyx, integrado en el bucle GLib (Gio.SocketService).

Una línea JSON por petición → el handler devuelve un dict → se responde con una
línea JSON y se cierra la conexión. Verbos: ping, status, say, quit (y futuros).
"""

from __future__ import annotations

import json
import os
from typing import Callable

from gi.repository import Gio, GLib


class SocketServer:
    def __init__(self, path: str, handler: Callable[[dict], dict]):
        self.path = path
        self.handler = handler
        # Limpia un socket huérfano (instancia previa caída). La unicidad real la
        # garantiza el application_id de Gtk.Application, así que aquí ya somos el primario.
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
        self.service = Gio.SocketService.new()
        addr = Gio.UnixSocketAddress.new(path)
        self.service.add_address(
            addr, Gio.SocketType.STREAM, Gio.SocketProtocol.DEFAULT, None
        )
        self.service.connect("incoming", self._on_incoming)
        self.service.start()

    def _on_incoming(self, _service, conn, _src):
        dis = Gio.DataInputStream.new(conn.get_input_stream())
        dis.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line, conn)
        return False

    def _on_line(self, dis, res, conn):
        reply = {"ok": False, "error": "bad request"}
        try:
            data, _len = dis.read_line_finish_utf8(res)
        except GLib.Error:
            data = None
        if data:
            try:
                msg = json.loads(data)
                if isinstance(msg, dict):
                    reply = self.handler(msg) or {"ok": True}
            except json.JSONDecodeError:
                pass
            except Exception as e:  # un handler no debe tumbar el servidor
                reply = {"ok": False, "error": repr(e)}
        try:
            out = conn.get_output_stream()
            out.write_all((json.dumps(reply) + "\n").encode(), None)
            out.flush(None)
        except GLib.Error:
            pass
        try:
            conn.close(None)
        except GLib.Error:
            pass
