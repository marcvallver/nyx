# Session log — Nyx

Una entrada por sesión de trabajo (append-only, ~5 líneas). El detalle de arquitectura
va a `docs/ARCHITECTURE.md`; aquí solo el rastro de qué se movió y qué viene después.

## 2026-07-02 — Nyx v2: config + sesión core + notifs v2 + proactiva + panel (+ NyxMidnight en dotfiles)
**Foco de hoy:** plan maestro "asistente de 10" aprobado por Marc — gestionable, con notificaciones de verdad, proactiva y guapa.
**Avanzado:** config unificada v2 (`nyx/config.py`, migración auto + `nyx-ctl config` + op `reload`); moods `⟨glad⟩`/`⟨dim⟩` (Sanzo Wada #189/#41) + persona expresiva + mood persistente completo; **sesión core persistente** (`--resume` sobrevive reinicios, hilo en `chat.jsonl`, `nyx-ctl session`, eco de terminal compacto sin voz); unit systemd `Restart=on-failure` (kill -9 → resucita en 2s); notifs v2 (cola pura con rate-limit/DND/reglas, historial JSONL, botones de acción + iconos, `NotificationClosed` real); **capa proactiva** (`nyx/watchers/`: NudgeGate + sessions/repos/usb/system/eod — detectó los PR #550/#544 de Marc S en su primer pulso); centro de control (`nyx/control.py`, drawer derecho). 155 tests verdes. En dotfiles: scheme **NyxMidnight** aplicado (+accent teal), `themes/nyx/colors.toml`, `chk_nyx_palette` en drift, hooks de sesión.
**Bloqueos:** spectacle/portal se colgó a mitad de sesión (rc=0 sin fichero, ni con `-f`) → capturas de moods/panel pendientes de verificación visual por Marc. `dist/` estaba en `.gitignore` (plantillas nunca versionadas) → corregido.
**Decisiones:** JSON se queda (no TOML); espejo real de notifs imposible por spec (un dueño del bus name) → takeover opt-in y SOLO con unit instalada; glad/dim por doctrina Wada (partir de combos donde vive el teal); el daemon jamás ejecuta sudo (kitty + contraseña = 2ª confirmación); eco de terminal sin texto (decisión de Marc); panel al final para enseñarlo todo.
**Siguiente sesión:** atar Meta+N (panel) en System Settings; decidir activación del takeover de notifs; track visual restante (wallpaper midnight, splash QML "Nyx boot sequence", SDDM overlay con snapshot, borde neón Klassy); test STT en vivo con micrófono (heredado del 19/06).

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
