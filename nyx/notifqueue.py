"""Cola y clasificación de notificaciones de sistema — PURA (sin gi, tiempo
inyectado), testeable en CI. `app.py` solo pega los timers GLib.

Reglas: la urgencia crítica (>=2) salta el DND y los silencios por app; el
rate-limit colapsa el exceso en un resumen sintético "+N de <app>" para que
una ráfaga (spam de una app ruidosa) no convierta el bocadillo en metralleta.
Las silenciadas se registran igual en el historial (esa es la gracia).
"""

from __future__ import annotations

import json
import os

SHOW = "show"
SILENCE = "silence"

NOTIF_LOG = os.path.expanduser("~/.local/state/nyx/notifications.jsonl")


def classify(n: dict, rules: dict | None = None, dnd: bool = False) -> str:
    """SHOW o SILENCE. Crítica (urgency>=2) siempre SHOW; luego DND; luego
    reglas por app ({"Spotify": "silence"})."""
    if int(n.get("urgency", 1)) >= 2:
        return SHOW
    if dnd:
        return SILENCE
    if (rules or {}).get(n.get("app", "")) == "silence":
        return SILENCE
    return SHOW


class NotifQueue:
    """FIFO con prioridad para críticas, replaces_id real y rate-limit por
    ventana de 60 s. El tiempo entra por parámetro (now, en segundos)."""

    def __init__(self, max_per_minute: int = 6, max_queue: int = 20):
        self.max_per_minute = max(1, int(max_per_minute))
        self.max_queue = max(1, int(max_queue))
        self._pending: list[dict] = []
        self._shown_ts: list[float] = []  # instantes de los shows en la ventana
        self._collapsed: dict[str, int] = {}  # app -> nº colapsadas por rate-limit

    def push(self, n: dict, now: float) -> str:
        """Encola. Devuelve "replaced" (sustituyó a una pendiente con su mismo id),
        "collapsed" (rate-limit: va al resumen sintético) o "queued"."""
        nid = int(n.get("id") or 0)
        if nid:
            for i, p in enumerate(self._pending):
                if int(p.get("id") or 0) == nid:
                    self._pending[i] = n  # replaces_id real: actualiza, no duplica
                    return "replaced"
        self._prune(now)
        critical = int(n.get("urgency", 1)) >= 2
        if not critical and len(self._shown_ts) >= self.max_per_minute:
            app = n.get("app") or "sistema"
            self._collapsed[app] = self._collapsed.get(app, 0) + 1
            return "collapsed"
        if len(self._pending) >= self.max_queue:
            self._drop_one()
        if critical:
            self._pending.insert(0, n)  # las críticas se cuelan
        else:
            self._pending.append(n)
        return "queued"

    def next(self, now: float) -> dict | None:
        """Siguiente notificación a mostrar (cuenta como show), el resumen
        sintético de las colapsadas, o None si no hay nada."""
        self._prune(now)
        if self._pending:
            self._shown_ts.append(now)
            return self._pending.pop(0)
        if self._collapsed:
            parts = [f"+{c} de {app}" for app, c in self._collapsed.items()]
            self._collapsed = {}
            self._shown_ts.append(now)
            return {"id": 0, "app": "", "summary": "notificaciones agrupadas",
                    "body": " · ".join(parts), "urgency": 0, "synthetic": True}
        return None

    def pending_count(self) -> int:
        return len(self._pending) + sum(self._collapsed.values())

    def _prune(self, now: float) -> None:
        self._shown_ts = [t for t in self._shown_ts if now - t < 60.0]

    def _drop_one(self) -> None:
        """Cola llena: descarta la más antigua de menor urgencia (nunca una crítica
        si hay alternativa)."""
        idx = min(range(len(self._pending)),
                  key=lambda i: (int(self._pending[i].get("urgency", 1)), i))
        self._pending.pop(idx)


# --- historial persistente (JSONL, best-effort) ---
def log_notification(n: dict, shown: bool, ts: float | None = None,
                     path: str | None = None) -> None:
    p = path or NOTIF_LOG
    rec = {"app": n.get("app", ""), "summary": n.get("summary", ""),
           "body": n.get("body", ""), "urgency": int(n.get("urgency", 1)),
           "shown": bool(shown), "ts": ts}
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_recent(n: int = 20, path: str | None = None) -> list[dict]:
    p = path or NOTIF_LOG
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-n:]:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and (rec.get("summary") or rec.get("app")):
            out.append(rec)
    return out
