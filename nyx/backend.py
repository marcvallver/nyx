"""Backend de Nyx: lanza el Claude Code CLI por turno y streamea la respuesta.

Fase 1 (rápida): resuelve la ruta ESTABLE del binario `claude` una vez (el shim de
fnm es efímero) y lo lanza DIRECTO — sin `zsh -ic` (ahorra ~1s de arranque + ruido
de p10k). Fallback a `zsh -ic 'exec claude "$@"'` si no se resuelve el binario.
Un `claude -p` por turno con `--resume <session_id>` para continuidad. La sesión
CORE se persiste en ~/.local/state/nyx/session.json: la conversación de Marc con
Nyx sobrevive a reinicios del daemon. Si la sesión guardada ya no es recuperable
(p.ej. ~/.claude limpiado), el turno se reintenta UNA vez desde cero sin perder
el mensaje. Parser puro de `nyx/streamparse.py`. stderr silenciado.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable

from gi.repository import Gio, GLib

from . import streamparse

DEFAULT_MODEL = "sonnet"  # rápido/barato para chat; Opus para tareas pesadas

# Perfil dedicado de Nyx (personal, fuera del repo): persona + permisos restringidos.
# Marc los versiona en ~/dotfiles/.claude/nyx/ y los symlinka aquí.
NYX_CONFIG = os.path.expanduser("~/.config/nyx")
_SETTINGS = os.path.join(NYX_CONFIG, "settings.json")
_PERSONA = os.path.join(NYX_CONFIG, "persona.md")
# estado de la sesión core (sobrevive reinicios del daemon)
SESSION_STATE = os.path.expanduser("~/.local/state/nyx/session.json")

# Las sesiones de claude son POR DIRECTORIO de proyecto: el subproceso debe correr
# SIEMPRE desde el repo, o `--resume` no encuentra la sesión core (bajo systemd el
# cwd del daemon era ~ y todos los turnos morían en error_during_execution).
REPO_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _load_session() -> str | None:
    try:
        with open(SESSION_STATE, encoding="utf-8") as f:
            sid = json.load(f).get("session_id")
        return sid if isinstance(sid, str) and sid else None
    except (OSError, ValueError):
        return None


def _save_session(sid: str) -> None:
    try:
        os.makedirs(os.path.dirname(SESSION_STATE), exist_ok=True)
        tmp = SESSION_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"session_id": sid}, f)
        os.replace(tmp, SESSION_STATE)
    except OSError:
        pass  # best-effort: sin persistencia la sesión sigue viva en memoria


def _clear_session() -> None:
    try:
        os.remove(SESSION_STATE)
    except OSError:
        pass


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
    def __init__(self, on_signal: Callable[[object], None], model: str | None = None):
        self.on_signal = on_signal  # callback(signal), en el bucle GLib
        self.model = model or DEFAULT_MODEL  # config backend.model; aplica al siguiente turno
        self.session_id: str | None = _load_session()  # sesión core: sobrevive reinicios
        self.busy = False
        self._parser = streamparse.StreamParser()
        self._claude_bin = _resolve_claude()  # una vez; None -> fallback zsh
        self._prompt = ""  # turno en curso (para reintentar si el resume falla)
        self._used_resume = False
        self._retried = False
        self._got_result = False
        self._got_init = False

    def reset_session(self) -> None:
        """Empieza una sesión core nueva (op session_new): olvida el hilo anterior."""
        self.session_id = None
        _clear_session()

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
            "--model", self.model,
        ]
        if os.path.exists(_SETTINGS):
            argv += ["--settings", _SETTINGS]   # perfil aislado: permisos restringidos
        persona = _read(_PERSONA)
        if persona:
            argv += ["--append-system-prompt", persona]  # personalidad de Nyx
        self._used_resume = bool(self.session_id)
        if self.session_id:
            argv += ["--resume", self.session_id]
        return argv

    def ask(self, prompt: str) -> bool:
        prompt = (prompt or "").strip()
        if self.busy or not prompt:
            return False
        self.busy = True
        self._prompt = prompt
        self._retried = False
        return self._spawn(prompt)

    def _spawn(self, prompt: str) -> bool:
        self._parser = streamparse.StreamParser()
        self._got_result = False
        self._got_init = False
        try:
            # SubprocessLauncher para quitar TERM_PROGRAM: así el hook global de
            # sonido (condicionado a TERM_PROGRAM=ghostty) NO suena en los turnos de Nyx.
            launcher = Gio.SubprocessLauncher.new(
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
            )
            launcher.unsetenv("TERM_PROGRAM")
            launcher.set_cwd(REPO_DIR)  # sesiones por directorio: siempre desde el repo
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
            # `claude -p --resume <id>` con una sesión irrecuperable muere sin emitir
            # `result`: reintenta el MISMO turno una vez desde cero (sesión nueva),
            # sin perder el mensaje de Marc.
            if not self._got_result and self._used_resume and not self._retried:
                self._retried = True
                self.session_id = None
                _clear_session()
                if self._spawn(self._prompt):
                    return  # turno relanzado; este stream muere aquí
            self.busy = False
            return
        for sig in self._parser.feed_line(line):
            if isinstance(sig, streamparse.Init) and sig.session_id:
                self._got_init = True
                if sig.session_id != self.session_id:
                    _save_session(sig.session_id)
                self.session_id = sig.session_id
            elif isinstance(sig, streamparse.Result):
                self._got_result = True
                # "No conversation found with session ID": el error llega ANTES de
                # arrancar (sin init). Reintenta el MISMO turno de cero UNA vez,
                # sin enseñar este error a Marc ni perder su mensaje.
                if (sig.is_error and self._used_resume
                        and not self._got_init and not self._retried):
                    self._retried = True
                    self.session_id = None
                    _clear_session()
                    if self._spawn(self._prompt):
                        return  # el stream viejo muere aquí; sigue el del retry
            self.on_signal(sig)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)
