"""Daemon de notificaciones de Nyx: implementa `org.freedesktop.Notifications`
(la interfaz estándar que usan dunst/mako/swaync) sobre `Gio.DBusConnection` — sin
dependencias extra, integrado en el bucle GLib del daemon (sin hilos).

Opt-in: solo arranca si `dbus_notifications: true` en `~/.config/nyx/config.json`.
Con `dbus_notifications_takeover: true` reclama el nombre de bus reemplazando al daemon
nativo de KDE (knotificationd); sin takeover cede el nombre si KDE ya lo posee (no se cuelga).

Las funciones de parseo son PURAS (sin `gi`) para poder testearlas en CI; el pegamento
D-Bus importa `gi` de forma perezosa dentro de los métodos. Ver
`dist/org.freedesktop.Notifications.service` y docs/ARCHITECTURE.md para la activación.
"""

from __future__ import annotations

from collections.abc import Callable

BUS_NAME = "org.freedesktop.Notifications"
OBJECT_PATH = "/org/freedesktop/Notifications"
INTERFACE = "org.freedesktop.Notifications"

# Introspección mínima de la interfaz estándar (spec freedesktop 1.2).
INTROSPECTION_XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="Notify">
      <arg type="s" name="app_name" direction="in"/>
      <arg type="u" name="replaces_id" direction="in"/>
      <arg type="s" name="app_icon" direction="in"/>
      <arg type="s" name="summary" direction="in"/>
      <arg type="s" name="body" direction="in"/>
      <arg type="as" name="actions" direction="in"/>
      <arg type="a{sv}" name="hints" direction="in"/>
      <arg type="i" name="expire_timeout" direction="in"/>
      <arg type="u" name="id" direction="out"/>
    </method>
    <method name="CloseNotification">
      <arg type="u" name="id" direction="in"/>
    </method>
    <method name="GetCapabilities">
      <arg type="as" name="capabilities" direction="out"/>
    </method>
    <method name="GetServerInformation">
      <arg type="s" name="name" direction="out"/>
      <arg type="s" name="vendor" direction="out"/>
      <arg type="s" name="version" direction="out"/>
      <arg type="s" name="spec_version" direction="out"/>
    </method>
    <signal name="NotificationClosed">
      <arg type="u" name="id"/>
      <arg type="u" name="reason"/>
    </signal>
    <signal name="ActionInvoked">
      <arg type="u" name="id"/>
      <arg type="s" name="action_key"/>
    </signal>
  </interface>
</node>
"""

CAPABILITIES = ["body", "body-markup", "persistence"]
SERVER_NAME = "Nyx"
SERVER_VENDOR = "marc"
SERVER_VERSION = "1.0"
SPEC_VERSION = "1.2"

CLOSE_REASON_EXPIRED = 1
CLOSE_REASON_DISMISSED = 2
CLOSE_REASON_CLOSED = 3  # CloseNotification()


# --- helpers PUROS (sin gi → testeables en CI) ---
def urgency_from_hints(hints) -> int:
    """Extrae la urgencia (0=baja, 1=normal, 2=crítica) del hint `urgency`. Default 1."""
    try:
        u = hints.get("urgency")
    except AttributeError:
        return 1
    if isinstance(u, bool):  # bool ⊂ int → trátalo aparte por seguridad
        return 1
    if isinstance(u, int) and u in (0, 1, 2):
        return u
    return 1


def parse_notify(
    app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout,
) -> dict:
    """Normaliza los args crudos de `Notify` a un dict estable para la UI de Nyx."""
    hints = hints or {}
    return {
        "app": (app_name or "").strip(),
        "replaces_id": int(replaces_id or 0),
        "icon": (app_icon or "").strip(),
        "summary": (summary or "").strip(),
        "body": (body or "").strip(),
        "actions": list(actions or []),
        "urgency": urgency_from_hints(hints),
        "expire_timeout": int(expire_timeout if expire_timeout is not None else -1),
    }


def capabilities() -> list[str]:
    return list(CAPABILITIES)


def server_information() -> tuple[str, str, str, str]:
    return (SERVER_NAME, SERVER_VENDOR, SERVER_VERSION, SPEC_VERSION)


# --- servidor D-Bus (gi perezoso) ---
class NotificationServer:
    """Servidor `org.freedesktop.Notifications` sobre Gio, en el bucle GLib del daemon.

    `callback(n: dict)` se invoca al llegar una notificación, ya en el hilo principal
    (Gio despacha en el contexto por defecto). `n` = el dict de `parse_notify` (+ `id`).
    """

    def __init__(self, callback: Callable[[dict], None], *, takeover: bool = False) -> None:
        self._callback = callback
        self._takeover = takeover
        self._next_id = 1
        self._owner_id: int | None = None
        self._reg_id: int | None = None
        self._conn = None

    def start(self) -> None:
        from gi.repository import Gio

        if self._takeover:
            flags = Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT | Gio.BusNameOwnerFlags.REPLACE
        else:
            flags = Gio.BusNameOwnerFlags.DO_NOT_QUEUE  # si KDE lo posee, cedemos sin colgar
        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION, BUS_NAME, flags,
            self._on_bus_acquired, None, self._on_name_lost,
        )

    def stop(self) -> None:
        from gi.repository import Gio

        if self._conn is not None and self._reg_id is not None:
            try:
                self._conn.unregister_object(self._reg_id)
            except Exception:
                pass
        if self._owner_id is not None:
            try:
                Gio.bus_unown_name(self._owner_id)
            except Exception:
                pass
        self._owner_id = None
        self._reg_id = None
        self._conn = None

    def _on_bus_acquired(self, conn, _name) -> None:
        from gi.repository import Gio

        try:
            node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
            iface = node.lookup_interface(INTERFACE)
            self._conn = conn
            self._reg_id = conn.register_object(
                OBJECT_PATH, iface, self._on_method_call, None, None,
            )
        except Exception:
            self._conn = None

    def _on_name_lost(self, _conn, _name) -> None:
        # Otro daemon (KDE) ya posee el nombre y no hubo takeover → quedamos inertes.
        self._conn = None

    def _on_method_call(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        from gi.repository import GLib

        try:
            if method == "Notify":
                data = parse_notify(*params.unpack())
                nid = data["replaces_id"] or self._next_id
                if not data["replaces_id"]:
                    self._next_id += 1
                data["id"] = nid
                try:
                    self._callback(data)
                except Exception:
                    pass
                invocation.return_value(GLib.Variant("(u)", (nid,)))
            elif method == "CloseNotification":
                (nid,) = params.unpack()
                self.close(int(nid), CLOSE_REASON_CLOSED)
                invocation.return_value(None)
            elif method == "GetCapabilities":
                invocation.return_value(GLib.Variant("(as)", (capabilities(),)))
            elif method == "GetServerInformation":
                invocation.return_value(GLib.Variant("(ssss)", server_information()))
            else:
                invocation.return_dbus_error(
                    "org.freedesktop.DBus.Error.UnknownMethod", f"método desconocido: {method}",
                )
        except Exception:
            try:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.Failed", "error interno")
            except Exception:
                pass

    def close(self, nid: int, reason: int = CLOSE_REASON_CLOSED) -> None:
        """Emite NotificationClosed (al cerrar/expirar una notificación)."""
        if self._conn is None:
            return
        from gi.repository import GLib

        try:
            self._conn.emit_signal(
                None, OBJECT_PATH, INTERFACE, "NotificationClosed",
                GLib.Variant("(uu)", (int(nid), int(reason))),
            )
        except Exception:
            pass
