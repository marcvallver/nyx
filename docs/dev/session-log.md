# Session log — Nyx

Una entrada por sesión de trabajo (append-only, ~5 líneas). El detalle de arquitectura
va a `docs/ARCHITECTURE.md`; aquí solo el rastro de qué se movió y qué viene después.

## 2026-06-21 — Toggle de voz + atajo Meta+M
**Foco de hoy:** que Nyx hable o calle cuando Marc decida (toggle de voz).
**Avanzado:** `nyx-ctl tts` sin arg ALTERNA (op IPC → `TtsSpeaker.toggle`), on/off fija; persiste en `~/.config/nyx/config.json` (escritura atómica); al activar, bocadillo + "Voz activada" audible. Atajo **Meta+M**. 4 tests de toggle/persistencia (51 verdes) + README. → nyx `475fcb3`, dotfiles `f990c3d`.
**Bloqueos:** ninguno. Resuelto en sesión: en Wayland los atajos los gestiona **KWin**; editar `kglobalshortcutsrc` a mano NO los registra → crear por System Settings (GUI).
**Decisiones:** Meta+M para conmutar la voz (Meta+V lo ocupa Klipper).
**Siguiente sesión:** test STT en vivo con micrófono (AirPods/Sony) — pendiente desde el 19/06.

## 2026-06-21 — Estados emocionales (mood) + historial + notificaciones + fonética
**Foco de hoy:** personalidad propia con estados emocionales que tiñen TODA la UI, + historial, + notificaciones, + voz que pronuncia el inglés.
**Avanzado:** marcadores `⟨alert⟩`/`⟨heated⟩` consumidos en `streamparse` (`MoodSignal`, tolera split entre deltas); **mood UNIFICADO** en orbe/sparkle/bocadillo/barra/×/fondo con los colores de la terminal Ghostty (alert `#c5003c`, heated ámbar `#ff9e00`, reposo teal + aberración cian); botón **×** de cierre; **historial** lateral (`history.py`, `nyx-ctl history`); **notificaciones** D-Bus `org.freedesktop.Notifications` sobre Gio (`notifyd.py`, opt-in); **fonética** inglesa del TTS (`phonetics.py`, respelling es-ES, solo voz); auto-`⟨alert⟩` en `nyx-permission-gate` ante un deny. 72 tests verdes (21 nuevos: mood + notifyd + fonética), `ruff` pineado. Revisión adversarial (workflow) → 3 bugs corregidos.
**Bloqueos:** ninguno en código. Operativo: una 2ª instancia de Claude + el backend del propio daemon (Auto mode, con `Write|*`/`Edit|*` aprendidos) se auto-editaban el repo en paralelo → detenidos. Reiniciar/capturar la GUI desde un shell sin display exige tomar prestado el entorno gráfico de `/proc`.
**Decisiones:** colores de mood = paleta de la terminal Ghostty (cyberpunk-2077); regla "el mood unifica toda la UI salvo que dañe legibilidad/función"; notificaciones D-Bus opt-in (no toma KDE por defecto); `ruff` pineado (23 errores pre-existentes → limpieza aparte).
**Siguiente sesión:** valorar limpiar los 23 ruff pre-existentes; test STT en vivo con micrófono (heredado del 19/06).
