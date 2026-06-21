"""Política de permisos de Nyx (puro, testeable).

Clasifica cada tool-call en:
  - "allow": seguro, se ejecuta sin molestar (lecturas, abrir apps, git read-only…).
  - "deny" : peligroso, bloqueado SIEMPRE (rm -rf, sudo, dd, curl|sh, secretos, BD…).
  - "gray" : el resto → se pregunta a Marc (popup de confirmación).

Guardarraíl: los comandos destructivos y de **base de datos** se DENIEGAN de raíz
(el dev de gymbros apunta a BD de producción). Ante la duda, "gray" (que decida Marc).
El "permitir siempre" aprende patrones, pero NUNCA puede saltarse la lista de deny.
"""

from __future__ import annotations

import json
import os
import re
import shlex

ALLOW_STORE = os.path.expanduser("~/.config/nyx/allowed.json")

# --- patrones de DENEGACIÓN dura (Bash) ---
_DENY = [
    (r"\brm\b[^|;&]*-[a-zA-Z]*[rf]", "borrado recursivo/forzado"),
    (r"\bfind\b[^|;&]*\s-delete\b", "find -delete (borrado masivo)"),
    (r"\b(sudo|doas|pkexec)\b", "elevación de privilegios"),
    (r"\bdd\b", "dd (sobrescritura de disco)"),
    (r"\bmkfs", "formateo"),
    (r"\b(shutdown|reboot|poweroff|halt|systemctl\s+(poweroff|reboot|halt))\b", "apagado/reinicio"),
    (r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b", "curl|sh (ejecutar de internet)"),
    (r":\s*\(\s*\)\s*\{", "fork bomb"),
    (r">\s*/dev/(sd|nvme|disk|vd)", "escritura a dispositivo de bloque"),
    (r"\bchmod\b[^|;&]*(-R[^|;&]*777|777[^|;&]*/)", "chmod 777 peligroso"),
    (r"\bgit\s+push\b[^|;&]*(--force\b|-f\b)", "git push --force"),
    (r"\b(psql|mysql|mariadb|mongo|mongosh|sqlite3|redis-cli|prisma|drizzle-kit|sequelize)\b",
     "cliente de base de datos (BD de producción)"),
    (r"\b(DROP\s+(TABLE|DATABASE)|TRUNCATE\b|DELETE\s+FROM)", "SQL destructivo"),
    (r">\s*/etc/|>\s*/boot/|>\s*/usr/", "escritura en ruta de sistema"),
]

# rutas/secretos cuya lectura se deniega
_SECRET = re.compile(
    r"(/\.ssh/|/\.gnupg/|/\.aws/|\.env(\.[\w]+)?\b|\bid_rsa\b|\bid_ed25519\b|\.pem\b|"
    r"credentials|\.kube/|\.netrc|\.claude/\.credentials)",
    re.IGNORECASE,
)

# primer token de Bash considerado seguro (solo lectura / abrir apps)
_SAFE_BASH = {
    "ls", "cat", "bat", "pwd", "echo", "printf", "grep", "egrep", "rg", "ag", "fd",
    "find", "which", "type", "head", "tail", "wc", "file", "stat", "du", "df", "date",
    "cal", "whoami", "id", "hostname", "uname", "uptime", "tree", "realpath", "dirname",
    "basename", "readlink", "gtk-launch", "xdg-open", "kreadconfig6", "lsblk", "free",
}
_SAFE_GIT_SUB = {"status", "diff", "log", "branch", "show", "remote", "rev-parse",
                 "describe", "config", "stash"}

# `find` con acciones que ejecutan/escriben (no solo listar) → no es seguro, se pregunta a Marc.
# (-delete ya cae en _DENY; -exec con rm/dd/… lo caza el patrón del comando interno.)
_FIND_ACTION = re.compile(r"\s-(exec|execdir|ok|okdir|fprint|fprintf|fls)\b", re.IGNORECASE)

_READ_TOOLS = {"Read", "Glob", "Grep", "LS", "NotebookRead"}
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

_SENSITIVE_WRITE = re.compile(r"^(/etc/|/boot/|/usr/|/bin/|/sbin/|/dev/)|/\.ssh/|/\.gnupg/")


def _first_token(cmd: str) -> str:
    try:
        parts = shlex.split(cmd)
    except ValueError:
        parts = cmd.split()
    for p in parts:  # saltar asignaciones de entorno (FOO=bar cmd)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", p):
            continue
        return os.path.basename(p)
    return ""


def _has_chain(cmd: str) -> bool:
    return bool(re.search(r"[;&|`]|\$\(|\breval\b|>>|>", cmd))


def classify_bash(cmd: str) -> tuple[str, str]:
    cmd = (cmd or "").strip()
    for pat, reason in _DENY:
        if re.search(pat, cmd, re.IGNORECASE):
            return ("deny", reason)
    if _SECRET.search(cmd):
        return ("deny", "acceso a un secreto")
    first = _first_token(cmd)
    if first == "find" and _FIND_ACTION.search(cmd):
        return ("gray", "find con -exec/-fprint (ejecuta o escribe): confirmar")
    if first == "git" and not _has_chain(cmd):
        try:
            sub = shlex.split(cmd)[1] if len(shlex.split(cmd)) > 1 else ""
        except ValueError:
            sub = ""
        if sub in _SAFE_GIT_SUB:
            return ("allow", f"git {sub} (solo lectura)")
        return ("gray", cmd[:100])
    if first in _SAFE_BASH and not _has_chain(cmd):
        return ("allow", f"comando seguro: {first}")
    return ("gray", cmd[:100])


def _learned() -> set[str]:
    try:
        with open(ALLOW_STORE, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def _key(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        return f"Bash|{_first_token(tool_input.get('command', ''))}"
    return f"{tool_name}|*"


def classify(tool_name: str, tool_input: dict, learned: set[str] | None = None) -> tuple[str, str]:
    tool_input = tool_input or {}
    learned = _learned() if learned is None else learned

    if tool_name == "Bash":
        decision, reason = classify_bash(tool_input.get("command", ""))
        if decision == "deny":
            return (decision, reason)  # deny gana siempre, ni aprendido lo salta
        if _key(tool_name, tool_input) in learned:
            return ("allow", "permitido siempre")
        return (decision, reason)

    if tool_name in _READ_TOOLS:
        target = str(
            tool_input.get("file_path") or tool_input.get("path")
            or tool_input.get("pattern") or ""
        )
        if _SECRET.search(target):
            return ("deny", "lectura de un secreto")
        return ("allow", "solo lectura")

    if tool_name in _WRITE_TOOLS:
        path = str(tool_input.get("file_path", ""))
        if _SENSITIVE_WRITE.search(path) or _SECRET.search(path):
            return ("deny", "escritura en ruta sensible")
        if _key(tool_name, tool_input) in learned:
            return ("allow", "permitido siempre")
        return ("gray", f"modificar {os.path.basename(path) or path}")

    # herramientas desconocidas / MCP / web → preguntar (salvo aprendidas)
    if _key(tool_name, tool_input) in learned:
        return ("allow", "permitido siempre")
    return ("gray", tool_name)


def learn(tool_name: str, tool_input: dict) -> None:
    """Persiste un patrón 'permitir siempre' (no puede saltarse el deny)."""
    store = _learned()
    store.add(_key(tool_name, tool_input or {}))
    os.makedirs(os.path.dirname(ALLOW_STORE), exist_ok=True)
    with open(ALLOW_STORE, "w", encoding="utf-8") as f:
        json.dump(sorted(store), f, ensure_ascii=False, indent=2)
