# dist/ — plantillas de integración (opt-in)

Plantillas que **no se instalan solas** (tocan integración del sistema). Se instalan
con `nyx-ctl install`, que renderiza `@REPO@` con la ruta real del repo y **copia
ficheros reales** (nunca symlinks: ni systemd ni sddm atraviesan `/home/marc` 0700).

## Unit systemd --user (`nyx.service`)

Arranque robusto del daemon: `PartOf=graphical-session.target`, `Restart=on-failure`
(si Nyx muere, systemd la relanza en ~2 s), logs en el journal.

```sh
nyx-ctl install        # copia la unit + enable; retira el autostart .desktop
systemctl --user start nyx
nyx-ctl logs -f        # journalctl --user -u nyx.service -f
nyx-ctl uninstall      # vuelve al modo autostart .desktop
```

`nyx-ctl on/off/restart` detectan la unit y usan systemctl automáticamente.
Verifica el entorno con `nyx-ctl doctor`.

## Notificaciones D-Bus (sustituir al daemon de KDE)

Nyx puede ser el daemon `org.freedesktop.Notifications` (lo que hacen dunst/mako/
swaync), mostrando cada notificación como un bocadillo. Implementado en
`nyx/notifyd.py` sobre `Gio.DBusConnection`. **Desactivado por defecto.**

1. Instala la unit + la activación D-Bus (con `SystemdService=nyx.service`, si llega
   una notificación y Nyx no corre, D-Bus le pide a systemd que la arranque — sin
   doble-arranque):
   ```sh
   nyx-ctl install --notifyd
   ```
2. Activa los flags (v2):
   ```sh
   nyx-ctl config set notifications.enabled true
   nyx-ctl config set notifications.takeover true   # reclamar el nombre aunque KDE lo posea
   ```
3. Desactiva el popup nativo en *System Settings → Notifications*.
   Prueba: `notify-send "título" "cuerpo"`.

**No actives `takeover` sin la unit instalada**: si Nyx cae poseyendo el nombre de
bus, systemd + la activación D-Bus son lo que te devuelve las notificaciones en
segundos. Urgencia `critical` tiñe el bocadillo de rojo y salta el DND. Para volver
a KDE: `nyx-ctl config set notifications.takeover false`, borra la activación
(`nyx-ctl uninstall` la retira) y reactiva las notificaciones de Plasma.

## Atajo del historial (Meta+H)

`bin/nyx-ctl history` alterna el panel lateral. El atajo se crea con
`~/.local/share/applications/net.local.nyx-history.desktop` (ya incluido) + un bind en
*System Settings → Shortcuts* (en Wayland los atajos los gestiona KWin; editar
`kglobalshortcutsrc` a mano NO los registra).
