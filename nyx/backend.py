"""Backend de Nyx: lanza el Claude Code CLI por turno y streamea la respuesta.

Fase 1 (rápida): resuelve la ruta ESTABLE del binario `claude` una vez (el shim de
fnm es efímero) y lo lanza DIRECTO — sin `zsh -ic` (ahorra ~1s de arranque + ruido
de p10k). Fallback a `zsh -ic 'exec claude "$@"'` si no se resuelve el binario.
Un `claude -p` por turno con `--resume <session_id>` para continuidad. Modelo sonnet.
Parser puro de `nyx/streamparse.py`. stderr silenciado.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable

from gi.repository import Gio, GLib

from . import streamparse

MODEL = "sonnet"  # rápido/barato para chat; Opus para tareas pesadas

# Perfil dedicado de Nyx (personal, fuera del repo): persona + permisos restringidos.
# Marc los versiona en ~/dotfiles/.claude/nyx/ y los symlinka aquí.
NYX_CONFIG = os.path.expanduser("~/.config/nyx")
_SETTINGS = os.path.join(NYX_CONFIG, "settings.json")
_PERSONA = os.path.join(NYX_CONFIG, "persona.md")


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _resolve_claude() -> str | None:
    """Ruta estable del binario `claude` (resuelve el shim efímero de fnm)."""
    p = shutil.which("claude")
    if not p:
        try:
            out = subprocess.run(
                ["zsh", "-ic", "command -v claude"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = [x.strip() for x in out.stdout.splitlines() if x.strip()]
            p = lines[-1] if lines else None
        except Exception:
            p = None
    if p:
        real = os.path.realpath(p)  # fnm_multishells (efímero) -> node-version (estable)
        if os.path.exists(real):
            return real
    return None


class ClaudeBackend:
    def __init__(self, on_signal: Callable[[object], None]):
        self.on_signal = on_signal  # callback(signal), en el bucle GLib
        self.session_id: str | None = None
        self.busy = False
        self._parser = streamparse.StreamParser()
        self._claude_bin = _resolve_claude()  # una vez; None -> fallback zsh

    def _argv(self, prompt: str) -> list[str]:
        if not (self._claude_bin and os.path.exists(self._claude_bin)):
            self._claude_bin = _resolve_claude()  # re-resolver (p.ej. tras upgrade de node)
        head = (
            [self._claude_bin]
            if self._claude_bin
            else ["zsh", "-ic", 'exec claude "$@"', "nyx"]
        )
        argv = head + [
            "-p", prompt,
            "--output-format", "stream-json",
            "--include-partial-messages", "--verbose",
            "--model", MODEL,
        ]
        if os.path.exists(_SETTINGS):
            argv += ["--settings", _SETTINGS]   # perfil aislado: permisos restringidos
        persona = _read(_PERSONA)
        if persona:
            argv += ["--append-system-prompt", persona]  # personalidad de Nyx
        if self.session_id:
            argv += ["--resume", self.session_id]
        return argv

    def ask(self, prompt: str) -> bool:
        prompt = (prompt or "").strip()
        if self.busy or not prompt:
            return False
        self.busy = True
        self._parser = streamparse.StreamParser()
        try:
            # SubprocessLauncher para quitar TERM_PROGRAM: así el hook global de
            # sonido (condicionado a TERM_PROGRAM=ghostty) NO suena en los turnos de Nyx.
            launcher = Gio.SubprocessLauncher.new(
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
            )
            launcher.unsetenv("TERM_PROGRAM")
            proc = launcher.spawnv(self._argv(prompt))
        except GLib.Error as e:
            self.busy = False
            self.on_signal(
                streamparse.Result(
                    subtype="error", text=f"no pude lanzar claude: {e}", is_error=True
                )
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
