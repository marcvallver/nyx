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

## Configuración (v2) — `nyx/config.py`

Única fuente de verdad: `~/.config/nyx/config.json` con **schema v2 anidado**
(`backend.model`, `ui.*` posiciones/TTL, `voice.*`, `notifications.*`, `terminal_echo`,
`mood`, `watchers.*`). Migración automática del formato plano (con `.bak`), rutas
punteadas, `validate()` que nunca lanza, escritura atómica. `nyx-ctl config
list|get|set` + op `reload` (aplica en vivo lo aplicable y devuelve
`applied`/`restart_needed`; sin file-monitor: entraría en bucle con las escrituras
atómicas del propio daemon). El panel de control usa la MISMA ruta (config.update +
reload).

## IPC

Socket UNIX `$XDG_RUNTIME_DIR/nyx.sock`, líneas JSON
(`summon|say|confirm|status|tts|listen|history|notify|hide|ask|quit|reload|mood|
config…|session_new|session_done|watchers|panel`), vigilado con `Gio.SocketService`.
Se conserva `~/.cache/claude-thinking.active` para las sesiones de terminal.
Los verbos se diseñan finos para envolverlos luego en D-Bus `org.marc.Nyx1`. `say`
acepta `mood`; `notify` lleva `app|summary|body|urgency` y opcionalmente
`icon|actions` (lista plana key,label como la spec).

## Sesión core (persistente)

El `--resume` del backend se persiste en `~/.local/state/nyx/session.json`: la
conversación de Marc con Nyx **sobrevive a reinicios del daemon**. Si la sesión
guardada ya no es recuperable, el turno se reintenta UNA vez desde cero sin perder
el mensaje. El hilo se registra en `~/.local/state/nyx/chat.jsonl`
([`nyx/chatlog.py`](../nyx/chatlog.py), puro; rotación a 1000) y el panel de
historial lo recarga al arrancar. `nyx-ctl session show|new|open` (open = kitty con
`claude --resume`; chatear ahí bifurca — la gestión real es vía Nyx). El hook
`Stop` global (`nyx-bubble-capture`) ya NO manda texto de otras sesiones: emite
`session_done` → eco compacto "⌁ sesión <repo>" sin voz (config `terminal_echo`),
filtrando los turnos del propio backend por session_id.

## Estados emocionales · historial · notificaciones

- **Estados emocionales (mood).** Cuatro marcadores que Nyx abre en su respuesta:
  `⟨alert⟩` (rojo `#c5003c`, peligro), `⟨heated⟩` (ámbar `#ff9e00`, carácter duro),
  `⟨glad⟩` (Lemon Yellow `#f8ed43`, Sanzo Wada #189 — algo salió bien) y `⟨dim⟩`
  (Dark Citrine `#8b835b`, Wada #41 — bajón sin drama). `theme.MOODS` es la lista
  canónica. `streamparse.py` los detecta y **consume** (tolera marcador partido)
  emitiendo `MoodSignal`; el mood tiñe TODAS las superficies (regla de la casa).
  Además hay **mood persistente** (op `mood` / panel; clave `mood` del config):
  tiñe el reposo y sobrevive reinicios; la decisión de estado del orbe es pura
  ([`nyx/moodstate.py`](../nyx/moodstate.py)). El gate dispara `mood=alert` ante
  un deny. La persona declara los marcadores en `~/.config/nyx/persona.md`.
- **Historial.** `history.py` — panel layer-shell lateral (izquierda,
  `exclusive_zone`): turnos (recargados de `chat.jsonl` al arrancar) +
  notificaciones compactas (las silenciadas también, marcadas). Toggle Meta+H.
- **Notificaciones v2.** `notifyd.py` implementa `org.freedesktop.Notifications`
  (capabilities `actions|body|persistence`) — opt-in `notifications.enabled` +
  `takeover`. Pipeline único (op `notify` y D-Bus):
  [`nyx/notifqueue.py`](../nyx/notifqueue.py) puro — classify (crítica salta DND
  y silencios por app), FIFO con prioridad crítica, replaces_id real, rate-limit
  60 s con colapso "+N de app" — → bocadillo de una en una, con icono y hasta 3
  botones (`ActionInvoked`; la región de input es la unión de widgets interactivos,
  fallback = todo click-through). `NotificationClosed` se emite al ocultarse
  (expired/dismissed). Historial persistente `~/.local/state/nyx/notifications.jsonl`
  (`nyx-ctl notifs`, `dnd`). Ver `dist/README.md`; **no activar takeover sin la
  unit systemd instalada**.

## Proactividad — watchers (`nyx/watchers/`)

Contrato: **la máquina vigila y propone, decide el humano**; un nudge se dispara
UNA vez por estado nuevo (clave = huella del estado) y si Marc lo ignora, Nyx se
calla. Todo opt-in por config (`watchers.<nombre>.enabled`).

- `base.py` (puro): `Nudge`, `Action`, `NudgeGate` (cooldown + quiet-hours que
  cruzan medianoche — los alert pasan; estado en `~/.cache/nyx/nudges.json`).
- `WatcherManager`: registro dict + import perezoso; try/except en todo (ningún
  watcher tumba el daemon); estado por op `watchers`.
- Acciones ([`nyx/actions.py`](../nyx/actions.py)): SIEMPRE tras el popup
  (`ConfirmPopup.show_proposal`, sin "siempre"). `terminal` abre kitty con el
  comando preparado — **el daemon JAMÁS ejecuta sudo**, la contraseña es la 2ª
  confirmación; `subprocess` solo con allowlist + veto de policy.
- Primera hornada: `sessions` (colisiones de sesiones Claude en el mismo root git,
  vía hooks → `bin/nyx-session-mark` + FileMonitor; worktrees no colisionan),
  `repos` (pulso gh adaptativo 5/30 min de los PRs de fulgor: nuevo de Marc S /
  verde-efectivo → propuesta de merge / rojo nuevo; backoff y silencio ante error),
  `usb_backup` (UDisks2 → propuesta `bin/nyx-offsite` + recordatorio de N días),
  `system` (kernel sin módulos tras upgrade; faillock ≥ umbral → reset propuesto),
  `eod` (19:30: repos sucios → "/cierre-sesion pendiente").

## Centro de control — `nyx/control.py`

Drawer layer-shell anclado a la derecha (espejo del historial), HudFrame, teñido
por el mood persistente. Estado (modelo/sesión/coste), interruptores en vivo,
mood, modelo, watchers y acciones. Op `panel` / `nyx-ctl panel` (Meta+N sugerido).

## Lifecycle

`systemd --user` (unit en `~/.config/systemd/user`, `PartOf=graphical-session.target`,
`Restart=on-failure`, `Environment=LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`). Fallback probado:
`~/.config/autostart/nyx.desktop`. `nyx-ctl` soporta ambos.

## Voz (STT / TTS) — `nyx/voice.py`, `nyx/stt_worker.py`

- **STT (escuchar, push-to-talk):** `nyx/stt_worker.py` corre en un **venv aparte**
  (`~/.local/share/nyx/venv-voice`) porque el daemon usa el python del sistema (sin faster-whisper).
  El worker carga **faster-whisper** una vez (caliente) y, por stdin (`start`/`stop`), graba el micro
  con `pw-record` (raw 16 kHz mono) y **corta solo** ~800 ms después de que callas vía **webrtcvad**
  (auto-stop), o por `stop`/tope. Transcribe en español e imprime `TEXT:<…>`. `SttListener` (lado
  daemon) lo controla por stdin y, al recibir texto, lo reinyecta por `app.send_turn` (mismo flujo que
  la barra → orbe `thinking`). Op socket `listen` (toggle) + atajo KDE. **Lean: webrtcvad + numpy, sin
  torch ni CUDA** (silero-vad arrastraba torch+CUDA → descartado).
- **TTS (hablar) — pipeline síntesis ‖ reproducción (prefetch):** `TtsSpeaker` corre **dos hilos**:
  un *productor* sintetiza el siguiente trozo **mientras** suena el actual, y un *consumidor* reproduce
  el PCM ya listo en orden → **sin huecos entre frases**. En `_on_signal`, el streaming de Claude se
  agrupa en **chunks grandes** (`group_chunks`, pura/testeada): una respuesta breve sale **entera en
  una sola síntesis** (prosodia natural, menos llamadas); las largas se cortan por párrafo o ~280 chars.
  Cada clip lleva un colchón de silencio (`_pad`) para que `pw-play` no corte la última sílaba. Markdown
  se limpia para el habla (`_strip_md`). Un contador de generación (`stop()` lo incrementa) descarta el
  trabajo en vuelo al cortar (toggle/turno nuevo/barge-in). Toggle de salida vía op `tts`.
- **Backends TTS pluggables (`tts_backend` en config), con fallback en cascada** edge → Piper → espeak:
  - **`edge` (por defecto):** [`edge-tts`](https://github.com/rany2/edge-tts) — voces neuronales de
    Microsoft Edge, **gratis, sin key ni cuota**; voz es-ES `Ximena`/`Elvira`. Da mp3 → se decodifica a
    PCM s16le 24 kHz con **ffmpeg** (corre en el venv, vía subprocess; el daemon no importa edge_tts).
  - **`gemini` (opt-in, HD):** REST a `generateContent` (modalidad AUDIO, voz `Kore`), con urllib y la
    API key en `~/.config/nyx/gemini.key` (**fuera de git**). Cae a local sin red/cuota.
  - **`piper` / espeak:** local sin red (red de seguridad).
- **Enrutado de audio por config:** `tts_sink` y `stt_source` (el `node.name` de PipeWire) fijan
  salida/micro de Nyx **sin tocar el default del sistema** (`pw-play --target` / `pw-record --target`).
  El **STT se queda siempre local** por privacidad; la nube solo se usa, opt-in, para la *boca*.
