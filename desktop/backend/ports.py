"""Port resolution for nanobot Desktop.

Three localhost ports are involved:

  * ROUTER  (default 24691) — onboard_server frontend router.  The Pake window
                              (``nanobot.exe``) has ``http://127.0.0.1:24691``
                              baked in at build time, so this port CANNOT drift
                              at runtime — Pake would keep pointing at 24691.
                              24691 is deliberately picked in the IANA registered
                              range, below every OS ephemeral floor (Linux ≥32768,
                              Windows/macOS ≥49152), and is unused by any known
                              app, so it essentially never collides.
  * WEBUI   (default 8765)  — gateway WebSocket / WebUI (the chat interface the
                              browser/Pake ends up on).  Read by the gateway from
                              ``config.channels.websocket.port``.
  * GATEWAY (default 18790) — gateway health endpoint (``nanobot gateway --port``).

WEBUI and GATEWAY auto-drift upward to the next free port when their default is
occupied (another nanobot instance, or some unrelated app).  ROUTER is fixed;
occupancy is detected by the launcher and handled explicitly (single-instance
exit vs. a clear error), because silently drifting it would break the Pake entry.

All checks bind to 127.0.0.1 — the desktop only ever listens on loopback.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass

DEFAULT_ROUTER_PORT = 24691
DEFAULT_WEBUI_PORT = 8765
DEFAULT_GATEWAY_PORT = 18790

# How far upward we'll drift before giving up.  200 is far more than any
# realistic pile-up of conflicting listeners, but bounded so we never spin.
_MAX_DRIFT = 200


@dataclass(frozen=True)
class ResolvedPorts:
    """The three ports the desktop will bind this launch.

    ``router`` is always :data:`DEFAULT_ROUTER_PORT` (Pake constraint); it is
    carried here only so callers have a single object.  ``webui`` and
    ``gateway`` may have drifted upward from their defaults.
    """

    router: int
    webui: int
    gateway: int

    @property
    def webui_drifted(self) -> bool:
        return self.webui != DEFAULT_WEBUI_PORT

    @property
    def gateway_drifted(self) -> bool:
        return self.gateway != DEFAULT_GATEWAY_PORT


def port_in_use(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    """True if a listener is accepting connections on ``(host, port)``.

    Tested by attempting to connect: a completed TCP handshake means some
    server is already bound and listening there.  This is deliberately a
    *connect* test rather than a *bind* test — on Windows ``SO_REUSEADDR``
    lets a second socket bind right over an active listener (unlike Unix), so a
    bind test would hide the conflict and report an occupied port as free.

    It also matches what we actually care about — "will the Pake window / our
    own server reach a foreign service on this port?".  Ports carrying only a
    lingering ``TIME_WAIT`` (no listener) refuse the connection and read as
    free, which is correct: our servers set ``SO_REUSEADDR`` and can rebind
    those.  On loopback a refused connect returns instantly, so scanning a few
    hundred candidates is cheap.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_free_port(
    start: int,
    *,
    used: set[int] | None = None,
    host: str = "127.0.0.1",
    max_drift: int = _MAX_DRIFT,
) -> int:
    """Return the first free port at or above ``start``, skipping ``used``.

    ``used`` lets the caller reserve ports already claimed by the desktop
    itself (e.g. the router port) so two roles never collide.
    """
    taken = used or set()
    port = start
    while port < start + max_drift:
        if port not in taken and not port_in_use(port, host):
            return port
        port += 1
    raise RuntimeError(
        f"no free port near {start} after {max_drift} attempts "
        f"(last tried {port - 1})"
    )


def probe_nanobot_router(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """True if ``(host, port)`` is serving the nanobot onboard router.

    Used to distinguish "another nanobot desktop instance already running" from
    "an unrelated app grabbed the port", when the fixed router port (24691) is
    busy.  We ``GET /api/status`` and look for our JSON shape — the keys
    ``configured`` and ``gateway_up`` — which only our router emits.
    """
    import urllib.request

    try:
        url = f"http://{host}:{port}/api/status"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — any failure means "not our router"
        return False
    return isinstance(data, dict) and "configured" in data and "gateway_up" in data


def resolve_ports(
    *,
    router: int = DEFAULT_ROUTER_PORT,
    webui: int = DEFAULT_WEBUI_PORT,
    gateway: int = DEFAULT_GATEWAY_PORT,
) -> ResolvedPorts:
    """Resolve the two drift-able ports, keeping all three distinct.

    The router port is **not** drifted here — it is fixed (Pake).  The caller is
    responsible for handling router occupancy before invoking this.
    """
    used: set[int] = {router}
    webui_port = find_free_port(webui, used=used)
    used.add(webui_port)
    gateway_port = find_free_port(gateway, used=used)
    return ResolvedPorts(router=router, webui=webui_port, gateway=gateway_port)
