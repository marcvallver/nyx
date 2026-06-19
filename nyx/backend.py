"""Backend de Nyx: lanza el Claude Code CLI por turno y streamea la respuesta.

Fase 1: un `claude -p` por turno con `--resume <session_id>` para continuidad
(sencillo y robusto; el coste de arranque se cubre con el sparkle "thinking").
Usa el parser puro de `nyx/streamparse.py`. Modelo rápido (sonnet) para el chat.

Nota: invoca vía `zsh -ic 'exec claude "$@"'` para resolver el shim de fnm; el
prompt va como argv literal (sin shell-quoting). stderr silenciado (ruido p10k).
Optimización futura: resolver la ruta del binario `claude` una vez y lanzarlo directo.
"""

from __future__ import annotations

from typing import Callable

from gi.repository import Gio, GLib

from . import streamparse

MODEL = "sonnet"  # rápido/barato para chat; Opus para tareas pesadas


class ClaudeBackend:
    def __init__(self, on_signal: Callable[[object], None]):
        self.on_signal = on_signal  # callback(signal), en el bucle GLib
        self.session_id: str | None = None
        self.busy = False
        self._parser = streamparse.StreamParser()

    def ask(self, prompt: str) -> bool:
        prompt = (prompt or "").strip()
        if self.busy or not prompt:
            return False
        self.busy = True
        self._parser = streamparse.StreamParser()
        argv = [
            "zsh", "-ic", 'exec claude "$@"', "nyx",
            "-p", prompt,
            "--output-format", "stream-json",
            "--include-partial-messages", "--verbose",
            "--model", MODEL,
        ]
        if self.session_id:
            argv += ["--resume", self.session_id]
        try:
            proc = Gio.Subprocess.new(
                argv,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error as e:
            self.busy = False
            self.on_signal(
                streamparse.Result(subtype="error", text=f"no pude lanzar claude: {e}", is_error=True)
            )
            return False
        stdout = Gio.DataInputStream.new(proc.get_stdout_pipe())
        stdout.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)
        return True

    def _on_line(self, stream, res):
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:  # EOF → turno terminado
            self.busy = False
            return
        for sig in self._parser.feed_line(line):
            if isinstance(sig, streamparse.Init) and sig.session_id:
                self.session_id = sig.session_id
            self.on_signal(sig)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)
