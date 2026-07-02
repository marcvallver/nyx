"""W4 · Nudges de sistema:
- Kernel actualizado pendiente de reinicio: tras un upgrade, el directorio de
  módulos del kernel CORRIENDO desaparece → los módulos no cargables hasta
  reiniciar. Señal: FileMonitor sobre /usr/lib/modules + chequeo al arrancar.
- faillock: contraseñas mal tecleadas (RDP/askpass) bloquean el login de marc.
  Señal: FileMonitor sobre /run/faillock; al cambiar se lee `faillock --user X`
  y con >= umbral se propone el reset (funciona SIN sudo: el fichero es 660 marc).
"""

from __future__ import annotations

import getpass
import os

from .base import Action, Nudge

MODULES_DIR = "/usr/lib/modules"
FAILLOCK_DIR = "/run/faillock"


def kernel_pending(running_release: str, module_dirs: list[str]) -> bool:
    """¿El kernel corriendo ya no tiene módulos instalados? Pura."""
    return bool(running_release) and running_release not in module_dirs


def count_failures(output: str) -> int:
    """Nº de intentos fallidos VÁLIDOS en la salida de `faillock --user X`
    (líneas de registro que acaban en columna V). Pura."""
    count = 0
    for line in (output or "").splitlines():
        parts = line.split()
        if parts and parts[-1] == "V" and len(parts) >= 3:
            count += 1
    return count


class SystemWatcher:
    def __init__(self, params: dict, emit):
        self._emit = emit
        self._threshold = int(params.get("faillock_threshold", 3))
        self._user = params.get("user") or getpass.getuser()
        self._monitors: list = []

    def start(self) -> None:
        from gi.repository import Gio

        for path, cb in ((MODULES_DIR, self._check_kernel),
                         (FAILLOCK_DIR, self._check_faillock)):
            if not os.path.isdir(path):
                continue
            gfile = Gio.File.new_for_path(path)
            mon = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            mon.connect("changed", lambda *_a, _cb=cb: _cb())
            self._monitors.append(mon)
        self._check_kernel()  # estado presente al arrancar

    def stop(self) -> None:
        for mon in self._monitors:
            try:
                mon.cancel()
            except Exception:
                pass
        self._monitors = []

    def status(self) -> dict:
        return {"kernel": os.uname().release}

    def _check_kernel(self) -> None:
        try:
            dirs = os.listdir(MODULES_DIR)
        except OSError:
            return
        running = os.uname().release
        if kernel_pending(running, dirs):
            self._emit(Nudge(
                key=f"kernel:{running}",
                text=("Kernel actualizado: el que corre ya no tiene módulos. "
                      "Reinicia cuando cierres, operativo."),
                mood="dim",
                cooldown_s=12 * 3600,
            ))

    def _check_faillock(self) -> None:
        from gi.repository import Gio, GLib

        try:
            proc = Gio.Subprocess.new(
                ["faillock", "--user", self._user],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error:
            return

        def _done(p, res):
            try:
                _ok, stdout, _ = p.communicate_utf8_finish(res)
            except Exception:
                return
            fails = count_failures(stdout or "")
            if fails >= self._threshold:
                self._emit(Nudge(
                    key=f"faillock:{self._user}:{fails}",
                    text=(f"{fails} fallos de login. ¿Reseteo el faillock antes "
                          "de que el RDP te cierre la puerta?"),
                    mood="alert",
                    action=Action(label="reset faillock", kind="subprocess",
                                  command=f"faillock --user {self._user} --reset"),
                    cooldown_s=600,
                ))

        proc.communicate_utf8_async(None, None, _done)
