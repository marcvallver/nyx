# Session log — Nyx

Una entrada por sesión de trabajo (append-only, ~5 líneas). El detalle de arquitectura
va a `docs/ARCHITECTURE.md`; aquí solo el rastro de qué se movió y qué viene después.

## 2026-06-21 — Toggle de voz + atajo Meta+M
**Foco de hoy:** que Nyx hable o calle cuando Marc decida (toggle de voz).
**Avanzado:** `nyx-ctl tts` sin arg ALTERNA (op IPC → `TtsSpeaker.toggle`), on/off fija; persiste en `~/.config/nyx/config.json` (escritura atómica); al activar, bocadillo + "Voz activada" audible. Atajo **Meta+M**. 4 tests de toggle/persistencia (51 verdes) + README. → nyx `475fcb3`, dotfiles `f990c3d`.
**Bloqueos:** ninguno. Resuelto en sesión: en Wayland los atajos los gestiona **KWin**; editar `kglobalshortcutsrc` a mano NO los registra → crear por System Settings (GUI).
**Decisiones:** Meta+M para conmutar la voz (Meta+V lo ocupa Klipper).
**Siguiente sesión:** test STT en vivo con micrófono (AirPods/Sony) — pendiente desde el 19/06.
