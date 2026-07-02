"""W2 · Pulso de PRs del repo principal (fulgor): con el CI caído por billing,
Marc verifica y mergea a mano — Nyx vigila las transiciones y avisa:
- PR nuevo de otro autor (Marc S) → nudge informativo (cascada intra-día).
- PR propio que pasa a verde-efectivo (ignorando checks rotos conocidos, p.ej.
  gitleaks) → nudge + acción propuesta: `gh pr merge --admin` en terminal.
- Check no ignorado que pasa a FAILURE → alert.

Único watcher inevitablemente periódico: tick adaptativo (5 min con sesión de
Claude activa, 30 min si no), 1 llamada `gh pr list` por tick (≤12/h vs 5000/h
de rate-limit). Error de red/gh → backoff x2 y SILENCIO (nunca nudge de error).
La lógica de decisión (diff_prs) es pura y se testea con fixtures del JSON real.
"""

from __future__ import annotations

import json
import os

from .base import Action, Nudge

SNAPSHOT = os.path.expanduser("~/.cache/nyx/prwatch.json")
ACTIVITY_FILE = os.path.expanduser("~/.cache/claude-thinking.active")
_GH_FIELDS = "number,title,author,statusCheckRollup,reviewDecision"


def _checks(pr: dict) -> list[tuple[str, str]]:
    """statusCheckRollup → [(nombre, estado)] normalizando CheckRun (status/
    conclusion) y StatusContext (context/state)."""
    out: list[tuple[str, str]] = []
    for c in pr.get("statusCheckRollup") or []:
        name = c.get("name") or c.get("context") or "?"
        if c.get("status") and c.get("status") != "COMPLETED":
            state = "PENDING"
        else:
            state = (c.get("conclusion") or c.get("state") or "PENDING").upper()
        out.append((name, state))
    return out


def snapshot_pr(pr: dict, ignore_checks: list[str]) -> dict:
    """Huella estable de un PR para comparar entre ticks. Pura."""
    checks = [(n, s) for n, s in _checks(pr) if n not in ignore_checks]
    failing = sorted(n for n, s in checks if s in ("FAILURE", "ERROR"))
    pending = any(s == "PENDING" for _n, s in checks)
    ok = ("SUCCESS", "SKIPPED", "NEUTRAL")
    green = not pending and not failing and all(s in ok for _n, s in checks)
    return {
        "title": pr.get("title") or "",
        "author": ((pr.get("author") or {}).get("login") or "").strip(),
        "failing": failing,
        "green": green,
        "pending": pending,
    }


def diff_prs(prev: dict[str, dict], curr: dict[str, dict], own_login: str,
             repo_path: str, merge_flags: str) -> list[Nudge]:
    """Transiciones entre dos snapshots {num: snapshot_pr()}. Pura.
    Solo cambios de estado: lo estable no re-nudgea (además del NudgeGate)."""
    nudges: list[Nudge] = []
    for num, cur in curr.items():
        old = prev.get(num)
        author = cur["author"]
        if old is None and author and author != own_login:
            nudges.append(Nudge(
                key=f"pr:new:{num}",
                text=f"`{author}` ha abierto PR #{num}: {cur['title']}",
            ))
        if author == own_login:
            if cur["green"] and not (old or {}).get("green"):
                nudges.append(Nudge(
                    key=f"pr:green:{num}",
                    text=f"PR #{num} en verde-efectivo: {cur['title']}. ¿Merge?",
                    mood="glad",
                    action=Action(
                        label=f"merge PR #{num}",
                        kind="terminal",
                        command=f"gh pr merge {num} {merge_flags}".strip(),
                        cwd=repo_path,
                    ),
                ))
            new_failing = set(cur["failing"]) - set((old or {}).get("failing") or [])
            if old is not None and new_failing:
                nudges.append(Nudge(
                    key=f"pr:red:{num}:{','.join(sorted(new_failing))}",
                    text=(f"PR #{num} en rojo: falla "
                          f"{', '.join(sorted(new_failing))}."),
                    mood="alert",
                ))
    return nudges


class ReposWatcher:
    def __init__(self, params: dict, emit):
        self._emit = emit
        self._repo = params.get("repo") or ""
        self._path = os.path.expanduser(params.get("path") or "")
        self._own = params.get("own_login") or "marcvallver"
        self._ignore = list(params.get("ignore_checks") or [])
        self._merge_flags = params.get("merge_flags") or "--admin --squash"
        self._active_s = int(params.get("interval_active_s", 300))
        self._idle_s = int(params.get("interval_idle_s", 1800))
        self._backoff = 1
        self._timer: int | None = None
        self._calls = 0
        self._last_error = ""

    # --- ciclo ---
    def start(self) -> None:
        if not self._repo:
            raise ValueError("watchers.repos.repo vacío")
        self._schedule(15)  # primer pulso poco después de arrancar

    def stop(self) -> None:
        from gi.repository import GLib

        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def status(self) -> dict:
        out = {"repo": self._repo, "gh_calls": self._calls}
        if self._last_error:
            out["last_error"] = self._last_error
        return out

    def _interval(self) -> int:
        base = self._active_s if os.path.exists(ACTIVITY_FILE) else self._idle_s
        return min(3600, base * self._backoff)

    def _schedule(self, seconds: int) -> None:
        from gi.repository import GLib

        if self._timer is not None:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add_seconds(seconds, self._tick)

    def _tick(self) -> bool:
        self._timer = None
        self._fetch()
        return False  # la siguiente cita la pone _done (intervalo adaptativo)

    def _fetch(self) -> None:
        from gi.repository import Gio, GLib

        self._calls += 1
        try:
            proc = Gio.Subprocess.new(
                ["gh", "pr", "list", "--repo", self._repo,
                 "--json", _GH_FIELDS, "--limit", "30"],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error as e:
            self._failed(str(e))
            return
        proc.communicate_utf8_async(None, None, self._done)

    def _done(self, proc, res) -> None:
        try:
            _ok, stdout, _ = proc.communicate_utf8_finish(res)
        except Exception as e:
            self._failed(str(e))
            return
        if not proc.get_successful():
            self._failed("gh salió con error")
            return
        try:
            prs = json.loads(stdout or "[]")
            curr = {str(pr["number"]): snapshot_pr(pr, self._ignore) for pr in prs}
        except (ValueError, KeyError, TypeError) as e:
            self._failed(f"json: {e}")
            return
        self._backoff = 1
        self._last_error = ""
        prev = self._load_snapshot()
        for nudge in diff_prs(prev, curr, self._own, self._path, self._merge_flags):
            self._emit(nudge)
        self._save_snapshot(curr)
        self._schedule(self._interval())

    def _failed(self, err: str) -> None:
        # silencio hacia Marc: solo backoff y constancia en status()
        self._last_error = err[:120]
        self._backoff = min(8, self._backoff * 2)
        self._schedule(self._interval())

    # --- snapshot en disco ---
    def _load_snapshot(self) -> dict:
        try:
            with open(SNAPSHOT, encoding="utf-8") as f:
                raw = json.load(f)
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_snapshot(self, snap: dict) -> None:
        try:
            os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
            tmp = SNAPSHOT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False)
            os.replace(tmp, SNAPSHOT)
        except OSError:
            pass
