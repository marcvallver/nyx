"""Ejecución de acciones propuestas por los watchers — SIEMPRE tras el clic de
Marc en el popup de confirmación (el daemon nunca actúa a ciegas).

Dos clases de acción:
- TERMINAL: abre kitty con el comando preparado (Ghostty se cuelga spawneada
  desde contexto GTK — precedente de sesion-remota). El daemon NUNCA ejecuta
  sudo: la contraseña que Marc teclea en esa terminal es la segunda confirmación.
- SUBPROCESS: la ejecuta el daemon (async, salida al bocadillo). Solo comandos
  que pasen la doble defensa: allowlist propia + veto de policy.

`allowed_subprocess` es pura (testeable en CI); los imports gi son perezosos.
"""

from __future__ import annotations

import shutil
import subprocess

from . import policy
from .watchers.base import SUBPROCESS, TERMINAL, Action

# allowlist de la casa para kind=subprocess (primer token del comando).
# policy sigue vetando por encima (deny gana siempre).
SUBPROCESS_ALLOW = ("faillock",)


def allowed_subprocess(command: str,
                       classify=policy.classify_bash,
                       allow: tuple[str, ...] = SUBPROCESS_ALLOW) -> bool:
    """Doble defensa: deny de policy = no rotundo; allow de policy o allowlist
    propia = sí; el resto (gray fuera de la allowlist) = no."""
    command = (command or "").strip()
    if not command:
        return False
    verdict, _reason = classify(command)
    if verdict == "deny":
        return False
    if verdict == "allow":
        return True
    return command.split()[0].rsplit("/", 1)[-1] in allow


class ActionRunner:
    def __init__(self, notify):
        """`notify(text, mood)` pinta el resultado en el bocadillo (lo pone la app)."""
        self._notify = notify

    def run(self, action: Action) -> None:
        try:
            if action.kind == TERMINAL:
                self._terminal(action)
            elif action.kind == SUBPROCESS:
                self._subprocess(action)
            else:
                self._notify(f"acción desconocida: {action.kind}", "dim")
        except Exception as e:
            self._notify(f"la acción falló: {e}", "alert")

    def _terminal(self, action: Action) -> None:
        kitty = shutil.which("kitty")
        if not kitty:
            self._notify(f"kitty no está; ejecuta a mano: `{action.command}`", "dim")
            return
        argv = [kitty, "--title", f"nyx · {action.label}", "--detach"]
        if action.cwd:
            argv += ["--directory", action.cwd]
        argv += ["zsh", "-ic",
                 f"{action.command}; echo; read -k1 '?— fin · una tecla para cerrar —'"]
        subprocess.Popen(argv, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _subprocess(self, action: Action) -> None:
        if not allowed_subprocess(action.command):
            self._notify(f"vetado por policy: `{action.command}`", "alert")
            return
        from gi.repository import Gio, GLib  # perezoso: el módulo se importa en CI

        try:
            proc = Gio.Subprocess.new(
                ["zsh", "-c", action.command],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE,
            )
        except GLib.Error as e:
            self._notify(f"no pude lanzar `{action.command}`: {e}", "alert")
            return

        def _done(p, res):
            try:
                _ok, stdout, _ = p.communicate_utf8_finish(res)
                out = (stdout or "").strip()
                if p.get_successful():
                    tail = f"\n{out[-200:]}" if out else ""
                    self._notify(f"hecho: `{action.label}`{tail}", "glad")
                else:
                    self._notify(f"`{action.label}` falló:\n{out[-300:]}", "alert")
            except Exception as e:
                self._notify(f"`{action.label}`: {e}", "alert")

        proc.communicate_utf8_async(None, None, _done)
