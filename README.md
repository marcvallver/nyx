# 🌙 Nyx

**Asistente de escritorio cyberpunk para Claude** — un overlay nativo de Wayland (GTK4 +
layer-shell) que convierte a Claude en un asistente "estilo Siri" siempre presente: un avatar
animado (orbe o mascota) que habla mediante bocadillos, un chat invocable por atajo, y
notificaciones propias con estética cyberpunk. Para **KDE Plasma 6 / Wayland**.

> Estado: **en construcción (v0, Fase 0).** Evoluciona el indicador `claude-thinking` (un overlay
> que ya anima el spinner "sparkle" de Claude Code) hacia un asistente completo.

## Idea

- **Cerebro = tu Claude Code CLI**, en modo programático (`claude -p --output-format stream-json`).
  Usa tu sesión existente (login Max) — **sin API key ni coste extra**. Streaming token a token.
- **Cara configurable:** un **orbe** abstracto cyberpunk (por defecto, sin assets con copyright) o
  una **mascota sprite** (reutilizando la infraestructura del proyecto Bestiario).
- **Híbrido con confirmación:** conversa por defecto y puede *ejecutar acciones* (abrir apps,
  lanzar comandos), pero pide confirmación explícita en las arriesgadas. Guardarraíles primero.
- **Notificaciones propias:** los mensajes del asistente salen como popups layer-shell cyberpunk.
- **Voz (más adelante):** dictado por *push-to-talk* (whisper) y voz neural de salida (piper).

## Arquitectura (resumen)

Un único daemon GTK4 + `gtk4-layer-shell` posee todas las superficies (avatar, bocadillo, barra de
entrada, toasts, popups de confirmación) y un subproceso `claude -p` persistente. La comunicación
entre el atajo global / hooks / gate de permisos y el daemon va por un socket UNIX (JSONL).

```
hotkey ─ nyx-ctl summon ─┐
hooks  ─ nyx-ctl say ────┤ (socket UNIX)
                         v
   daemon nyx  ⇄  claude -p (stream-json)
   avatar · bocadillo · input bar · notis · confirmación
```

Detalle completo en [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Roadmap

- **Fase 0** — Sparkle → bocadillo: muestra la última línea de Claude al terminar un turno.
- **Fase 1** — Summon + chat: atajo → barra de entrada → streaming en el bocadillo (continuidad de sesión).
- **Fase 2** — Avatar (orbe/sprite) con estados + notificaciones propias.
- **Fase 3** — Panel de control desde el plasmoide Bestiario.
- **Fase 4** — Acciones con confirmación + guardarraíles.
- **Fase 5** — Voz (STT whisper + TTS piper).

## Requisitos (objetivo)

- KDE Plasma 6 en Wayland, Python ≥ 3.11.
- Sistema: `gtk4`, `gtk4-layer-shell`, `python-gobject` (PyGObject). La GUI **no** se instala por pip.
- `@anthropic-ai/claude-code` autenticado (CLI `claude` en el PATH).
- *(Fase 5, opcional)* `python-openai-whisper` (STT), `piper-tts` (TTS).

## Desarrollo

```bash
pip install -e ".[dev]"
ruff check .
pytest -q
```

La **lógica pura** (parser de `stream-json`, política de permisos) no depende de GTK y se prueba en
CI. La GUI (Wayland/layer-shell) se valida a mano en un escritorio Plasma real.

## Licencia

[MIT](LICENSE) © 2026 Marc Vallverdú. El repo **no** incluye sprites ni sonidos con copyright; el
avatar por defecto es el orbe. Las mascotas se cargan desde material que aporta cada usuario.
