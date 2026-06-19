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
