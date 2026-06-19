# Arquitectura de Nyx

## Visión

Un único **daemon** (Python + GTK4 + `gtk4-layer-shell`) que posee todas las superficies de UI y un
subproceso `claude -p` persistente. Evoluciona el patrón ya probado de `claude-thinking` (overlay
layer-shell, click-through, animación del sparkle).

```
 hotkey (Meta+C) ─ nyx-ctl summon ─┐
 hooks/cron ─ nyx-ctl say "..." ───┤ (JSONL por socket UNIX: $XDG_RUNTIME_DIR/nyx.sock)
                                    v
 ┌──────────── daemon nyx (GTK4 layer-shell, bucle GLib) ───────────────┐
 │ ipc        → summon→InputBar · say→Notif · confirm→ConfirmPopup       │
 │ backend    ⇄  claude -p (hijo persistente, Gio.Subprocess)            │
 │   stdin: turnos (--input-format stream-json) · stdout: eventos JSONL  │
 │ Bubble (texto en vivo) · Avatar (orbe|sprite) · NotifMgr · InputBar   │
 └──────────────────────────────────────────────────────────────────────┘
            ▲ (el gate PreToolUse reconecta al socket para confirmar)
```

## Backend — envolver el Claude Code CLI

Modo programático, sin API key (usa el login Max existente):

```
claude -p --output-format stream-json --input-format stream-json \
       --include-partial-messages --verbose \
       --model <modelo> --session-id <UUID> \
       --settings <perfil-dedicado> --append-system-prompt-file <persona>
```

- I/O en el bucle GLib vía `Gio.Subprocess` (sin hilos). El prompt se manda por **stdin** (evita
  problemas de comillas). Continuidad: proceso persistente; `--session-id`/`--resume` como respaldo.
- Eventos `stream-json` (esquema verificado, v2.1.183): `system/init` (→ `session_id`),
  `system/status`, `stream_event` con `content_block_delta` → `text_delta` (streaming), `assistant`
  (mensaje completo; fallback), `rate_limit_event` (cuota Max), `result` (fin + métricas). El parser
  vive en [`nyx/streamparse.py`](../nyx/streamparse.py) (puro, testeado).

## Híbrido con confirmación — hook `PreToolUse`

En modo `-p` headless **no hay** prompt interactivo de permisos. El mecanismo que sí corre y puede
inyectar allow/deny por cada tool-call es un hook **`PreToolUse`** en un `--settings` dedicado:

1. `settings.json` dedicado: `allow` (lecturas, `gtk-launch`, `xdg-open`, git read-only…), `deny`
   duro (`rm -rf`, `sudo`, `dd`, `curl|sh`, rutas sensibles, comandos de BD…), y el hook `PreToolUse`.
2. El gate clasifica con `policy.py`: **safe** → allow · **destructivo** → deny · **gris** →
   round-trip por socket al daemon, que muestra un `ConfirmPopup` (Denegar / Permitir una vez /
   Siempre este patrón) y responde.
3. Emite `{"hookSpecificOutput": {"permissionDecision": "allow"|"deny", ...}}`.

`--settings` se **fusiona** sobre la config global (la auth Max queda intacta; no se toca
`CLAUDE_CONFIG_DIR`). Las operaciones destructivas/BD exigen confirmación tecleada, nunca un clic.

## Superficies (layer-shell)

| Superficie | Capa | Teclado | Click-through |
|---|---|---|---|
| Avatar (orbe/sprite) | OVERLAY | NONE | sí (salvo el propio avatar) |
| Bocadillo | OVERLAY | NONE | sí |
| Barra de entrada | OVERLAY | ON_DEMAND/EXCLUSIVE mientras visible | no |
| Notificaciones | OVERLAY | NONE | sí (salvo botones) |

- **Avatar pluggable** (`AvatarRenderer`, estados idle/thinking/talking/listening/alert):
  `OrbRenderer` con **Cairo (CPU)** — se evita GLArea por el bug de transparencia de NVIDIA #4835 —
  y `SpriteRenderer` que cicla hojas de sprites aportadas por el usuario.
- El sparkle (`· ✢ ✳ ✶ ✻ ✽`, palíndromo de 12 frames a 120 ms) se factoriza a `sparkle.py` como
  única fuente de verdad y es el estado "thinking" del avatar.

## IPC

Socket UNIX `$XDG_RUNTIME_DIR/nyx.sock`, líneas JSON (`summon|say|confirm|set|status`), vigilado con
`Gio.SocketService`. Se conserva `~/.cache/claude-thinking.active` para las sesiones de terminal.
Los verbos se diseñan finos para envolverlos luego en D-Bus `org.marc.Nyx1`.

## Lifecycle

`systemd --user` (unit en `~/.config/systemd/user`, `PartOf=graphical-session.target`,
`Restart=on-failure`, `Environment=LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`). Fallback probado:
`~/.config/autostart/nyx.desktop`. `nyx-ctl` soporta ambos.
