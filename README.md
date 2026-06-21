# 🌙 Nyx

**Asistente de escritorio cyberpunk para Claude** — un overlay nativo de Wayland (GTK4 +
`gtk4-layer-shell`) que convierte a Claude en un asistente "estilo Siri" siempre presente:
una ventanita HUD con glitch que **reacciona**, **chat por atajo** con respuesta en streaming,
**voz** (le hablas y te responde hablando), y **acciones con confirmación**. Para **KDE Plasma 6 / Wayland**.

> El "cerebro" es tu **Claude Code CLI** en modo programático (`claude -p --output-format stream-json`):
> usa tu sesión existente (login Max), **sin API key ni coste extra**.

---

## ✨ Qué hace

- **Avatar (la ventanita de Nyx):** tile HUD translúcido (borde teal + corner-brackets animados +
  scanlines) con el glifo *sparkle* de Claude latiendo, dibujado en **Cairo/CPU** (sin GL) + **glitch**
  (aberración RGB + ráfagas). Estados **idle / listening / thinking / talking**: pequeño y discreto en
  reposo, **crece al interactuar**. Reacciona también a tus sesiones de Claude Code en la terminal.
- **Chat (Meta+C):** barra de entrada con foco → tu pregunta → respuesta de Claude **en streaming**, con
  efecto **máquina de escribir** y **markdown** renderizado en el bocadillo. Continuidad de conversación.
- **Voz (estilo Siri):** **push-to-talk** (Meta+A) → STT local (faster-whisper, español) con **auto-stop**
  por VAD (callas → corta sola) → Claude → **TTS neuronal** (voz **es-ES** vía `edge-tts`, gratis y sin
  key; con Piper/espeak de fallback y **Gemini HD** opcional), sintetizado por **chunks con prefetch**
  para hablar fluido y sin huecos. Salida de voz con **toggle (Meta+M)**: enciéndela/apágala cuando
  quieras; la decisión **persiste** entre reinicios.
- **Acciones con confirmación (híbrido seguro):** Nyx puede *ejecutar* cosas (abrir apps, comandos),
  pero un **gate de permisos** auto-permite lo seguro (lecturas, abrir apps), **deniega** lo peligroso
  (`rm -rf`, `sudo`, BD…) y para el resto abre un **popup de confirmación**.
- **Notificaciones propias:** mensajes/avisos como bocadillo cyberpunk (no las del sistema).

## 🏗️ Arquitectura (resumen)

Un único **daemon** GTK4 (`nyx`) que posee todas las superficies y un subproceso `claude -p` persistente:

```
 atajo / hooks / voz ─ nyx-ctl <op> ─┐  (socket UNIX JSONL: summon|ask|say|listen|tts|confirm…)
                                      v
   daemon nyx ─ backend.py ⇄ claude -p (stream-json)
   avatar (orbe) · bubble · inputbar · confirm · voice (STT/TTS) · ipc
```

- **STT** corre en un **venv** aparte (faster-whisper, modelo caliente) controlado por el daemon vía
  un worker por stdin → el texto entra por el mismo `send_turn` que la barra. **TTS**: pipeline
  **síntesis ‖ reproducción (prefetch)** con backend pluggable — `edge-tts` (por defecto, gratis) /
  Gemini HD / Piper — enrutado al sink configurado vía `pw-play`. El gate de permisos es un hook
  **`PreToolUse`** en un `--settings` dedicado. Detalle completo en [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## 📦 Instalación (KDE Plasma 6 / Arch)

```bash
# Sistema (repos oficiales): GTK4 + layer-shell + PyGObject (suelen estar), audio + ffmpeg
sudo pacman -S --needed gtk4 gtk4-layer-shell python-gobject ffmpeg espeak-ng alsa-utils pipewire

# Voz (venv de usuario, sin tocar el sistema, SIN torch/CUDA): STT local + TTS neuronal gratis
python -m venv ~/.local/share/nyx/venv-voice
~/.local/share/nyx/venv-voice/bin/pip install faster-whisper webrtcvad-wheels numpy edge-tts
#   · TTS por defecto: edge-tts → voces neuronales de MS Edge, GRATIS y sin key (voz es-ES "Ximena")
#   · STT: faster-whisper (español) con auto-stop por VAD

# (Opcional) Piper como fallback de TTS sin red:
#   paru -S piper-tts-bin   +   una voz .onnx (+ .json) en ~/.local/share/nyx/voices/

# Lanzar (autoarranca al login)
nyx-ctl on
```

> El daemon necesita `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so` (lo pone `nyx-ctl`). El backend usa
> tu `claude` (Claude Code) del PATH. **Cero torch, cero CUDA** (~450 MB de venv con el modelo STT).

## ⌨️ Uso

```
nyx-ctl on|off|toggle|status     # daemon
nyx-ctl summon                   # abre el chat (átalo a Meta+C en Atajos de KDE)
nyx-ctl listen                   # push-to-talk: pulsa→habla→corta sola (átalo a Meta+A)
nyx-ctl tts [on|off]             # voz de salida: sin arg ALTERNA; on/off fija (átalo a Meta+M). Persiste
nyx-ctl ask "<texto>"            # turno por CLI (sin barra)
nyx-ctl say "<texto>"            # bocadillo (y voz si tts on)
nyx-ctl history                  # alterna el panel de historial lateral (átalo a Meta+H)
nyx-ctl notify "<app>" "<sum>" "<body>"  # notificación estilizada (bocadillo)
nyx-ctl listen_stop | hide | ping  # cortar escucha · ocultar barra · diagnóstico
```

Atajos sugeridos (System Settings → Atajos → *Orden o script*): **Meta+C** → `nyx-ctl summon`,
**Meta+A** → `nyx-ctl listen`, **Meta+M** → `nyx-ctl tts` (conmuta la voz), **Meta+H** →
`nyx-ctl history`.

**Estados emocionales:** Nyx tiñe orbe y bocadillo de **rojo** (alerta/peligro) o **naranja**
(personaje duro) cuando su respuesta abre con `⟨alert⟩`/`⟨heated⟩` (marcadores que se consumen,
declarados en `persona.md`); un comando bloqueado por el gate dispara el rojo automático. El
bocadillo lleva botón **×** para cerrarlo. **Notificaciones D-Bus** (sustituir al daemon de KDE):
opt-in, ver [`dist/README.md`](dist/README.md).

## 🔧 Configuración

- `~/.config/nyx/config.json` — voz y audio (ver [`config.example.json`](config.example.json)):
  `tts_backend` (`edge`/`gemini`/`piper`), `edge_voice` (p.ej. `es-ES-XimenaNeural` o `es-ES-ElviraNeural`),
  `tts_sink` y `stt_source` (el `node.name` de PipeWire para fijar salida/micro), `tts_enabled`,
  `stt_model`. **Gemini HD es opt-in**: `tts_backend: "gemini"` + la API key en `~/.config/nyx/gemini.key`
  (fuera de git). Lista de voces edge: `edge-tts --list-voices | grep es-`.
- `~/dotfiles/.claude/nyx/` (personal): `settings.json` (perfil de permisos + hook del gate) y
  `persona.md` (personalidad), symlinkeados a `~/.config/nyx/`.
- El **avatar sprite** (alternativa al orbe) y los sonidos son adapters de material que aportas tú;
  **no** se incluyen en el repo (sin copyright). El orbe es el avatar por defecto.

## 🧪 Desarrollo

```bash
pip install -e ".[dev]"
ruff check . && pytest -q
```

La **lógica pura** (parser `stream-json`, política de permisos, markup, troceo de frases del TTS,
extractor de transcript) se prueba en CI **sin GTK ni audio**. La GUI/voz se validan a mano en Plasma.

## 🗺️ Estado

Funcionando: avatar glitch, chat con streaming + tecleo, persona, gate de permisos con confirmación,
notificaciones, y **voz** — TTS neuronal **es-ES gratis** (`edge-tts`, voz Ximena) con pipeline de
**prefetch** (fluido, sin huecos) y fallback Piper/espeak, más STT push-to-talk con auto-stop por VAD.
Opt-in: **TTS HD por Gemini** (cloud), *barge-in* (interrumpir a Nyx hablando), wake-word "Hey Nyx".

## Licencia

[MIT](LICENSE) © 2026 Marc Vallverdú. Sin sprites/sonidos con copyright en el repo; el avatar por
defecto es el orbe. Las mascotas y voces se cargan desde material que aporta cada usuario.
