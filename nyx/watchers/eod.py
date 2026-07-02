"""W5 · Ritual de cierre: a la hora configurada (19:30), si hoy hubo actividad
de Claude, revisa los repos configurados y avisa de trabajo sin commitear —
"/cierre-sesion pendiente". Un solo timer reprogramado a diario (no un tick).
Si Marc no trabajó hoy (claude-edits.log sin tocar), silencio total.
"""

from __future__ import annotations

import os
import time

from .base import Nudge

EDITS_LOG = os.path.expanduser("~/Documents/sistema/claude-edits.log")


def seconds_until(hhmm: str, now_h: int, now_m: int, now_s: int) -> int:
    """Segundos hasta la próxima hh:mm (hoy o mañana). Pura."""
    try:
        h, m = (int(x) for x in hhmm.split(":", 1))
    except (ValueError, AttributeError):
        h, m = 19, 30
    target = h * 3600 + m * 60
    now = now_h * 3600 + now_m * 60 + now_s
    delta = target - now
    return delta if delta > 0 else delta + 86400


def eod_summary(dirty_repos: list[str], any_activity: bool) -> str | None:
    """Texto del nudge de cierre (None = silencio). Pura."""
    if not any_activity or not dirty_repos:
        return None
    if len(dirty_repos) == 1:
        heads = f"`{dirty_repos[0]}`"
    else:
        heads = ", ".join(f"`{r}`" for r in dirty_repos[:-1]) + f" y `{dirty_repos[-1]}`"
    return f"{heads} con trabajo sin commitear. /cierre-sesion pendiente."


class EodWatcher:
    def __init__(self, params: dict, emit):
        self._emit = emit
        self._hour = str(params.get("hour") or "19:30")
        self._repos = [os.path.expanduser(r) for r in (params.get("repos") or [])]
        self._timer: int | None = None

    def start(self) -> None:
        self._schedule()

    def stop(self) -> None:
        from gi.repository import GLib

        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def status(self) -> dict:
        return {"hour": self._hour, "repos": len(self._repos)}

    def _schedule(self) -> None:
        from gi.repository import GLib

        lt = time.localtime()
        secs = seconds_until(self._hour, lt.tm_hour, lt.tm_min, lt.tm_sec)
        self._timer = GLib.timeout_add_seconds(secs, self._fire)

    def _fire(self) -> bool:
        self._timer = None
        try:
            self._check()
        finally:
            self._schedule()  # la cita de mañana
        return False

    def _activity_today(self) -> bool:
        try:
            mtime = os.path.getmtime(EDITS_LOG)
        except OSError:
            return False
        today = time.localtime()
        m = time.localtime(mtime)
        return (m.tm_year, m.tm_yday) == (today.tm_year, today.tm_yday)

    def _check(self) -> None:
        if not self._activity_today():
            return
        self._pending = [r for r in self._repos if os.path.isdir(r)]
        self._dirty: list[str] = []
        self._next_repo()

    def _next_repo(self) -> None:
        if not self._pending:
            text = eod_summary(self._dirty, any_activity=True)
            if text:
                self._emit(Nudge(
                    key=f"eod:{time.strftime('%Y-%m-%d')}",
                    text=text, mood="dim", cooldown_s=6 * 3600,
                ))
            return
        repo = self._pending.pop(0)
        from gi.repository import Gio, GLib

        try:
            proc = Gio.Subprocess.new(
                ["git", "-C", repo, "status", "--porcelain"],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error:
            self._next_repo()
            return

        def _done(p, res, repo=repo):
            try:
                _ok, stdout, _ = p.communicate_utf8_finish(res)
                if p.get_successful() and (stdout or "").strip():
                    self._dirty.append(os.path.basename(repo))
            except Exception:
                pass
            self._next_repo()

        proc.communicate_utf8_async(None, None, _done)
