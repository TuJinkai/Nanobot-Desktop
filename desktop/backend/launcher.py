"""nanobot Desktop — backend lifecycle manager (zero-console).

Run via ``pythonw.exe`` so NO console window ever appears.

Flow:
  0. Resolve ports (ports.py): the router port 24691 is Pake-baked and
     immutable — if it is taken, distinguish our own instance (→ exit) from a
     foreign app (→ error) instead of drifting. The WebUI (8765) and gateway
     (18790) ports drift upward to the next free port when occupied.
  1. Start the frontend router on 24691 (binds instantly → Pake never sees
     "connection refused"; it shows a friendly loading animation instead).
  2. Open the single Pake window at the router.
  3. Start the gateway silently.  The router's loader polls until it is up,
     then redirects to the WebUI (or to the web onboarding on first run).
  4. Wait for the Pake window to close, then stop everything and exit.

All output goes to ~/.nanobot/desktop-launcher.log (pythonw has no console).
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

# CRITICAL: the embeddable python312._pth does NOT add this script's directory
# to sys.path, so the relative `import onboard_server` below would fail.  Add it
# explicitly before any local import.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Port defaults & drift logic live in ports.py (imported lazily in main()).
# The router port is Pake-baked and immutable; webui/gateway drift when busy.


# ---------------------------------------------------------------------------
# Logging (to a file, since pythonw has no console)
# ---------------------------------------------------------------------------


def _setup_logging() -> logging.Logger:
    log_dir = os.path.join(os.path.expanduser("~"), ".nanobot")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "desktop-launcher.log")
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("nanobot-desktop")


log = _setup_logging()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _install_dir() -> Path:
    return Path(_HERE).parent


def _python_dir() -> Path:
    return _install_dir() / "python"


def _pythonw_exe() -> str:
    """Interpreter for spawning children.

    Windows: prefer pythonw.exe (no console). macOS/Linux: python3 (GUI apps
    launched from a .app bundle don't attach a terminal anyway).
    """
    d = _python_dir()
    for name in ("pythonw.exe", "python.exe", "python3", "python"):
        p = d / name
        if p.exists():
            return str(p)
    return sys.executable


def _pake_exe() -> str:
    return str(_install_dir() / "nanobot.exe")


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    sp = _python_dir() / "Lib" / "site-packages"
    env["PYTHONPATH"] = str(sp) if sp.exists() else ""
    return env


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


class Gateway:
    def __init__(self, health_port: int) -> None:
        self._health_port = health_port
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.stop()
        cmd = [
            _pythonw_exe(), "-m", "nanobot", "gateway",
            "--foreground", "--port", str(self._health_port),
        ]
        kwargs: dict[str, Any] = {"env": _clean_env(), "stdin": subprocess.DEVNULL,
                                  "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            kwargs["creationflags"] = flags
        else:
            kwargs["start_new_session"] = True
        log.info("starting gateway: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, **kwargs)

    def stop(self, timeout: float = 15.0) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            log.info("gateway stopped")
        except Exception as exc:  # noqa: BLE001
            log.warning("gateway stop error: %s", exc)

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Pake window
# ---------------------------------------------------------------------------


def launch_pake(url: str) -> subprocess.Popen | None:
    exe = _pake_exe()
    if not Path(exe).exists():
        log.warning("pake exe missing, opening browser instead")
        import webbrowser
        webbrowser.open(url)
        return None
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True
    log.info("launching pake → %s", url)
    return subprocess.Popen([exe], **kwargs)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _ensure_webui_port_in_config(webui_port: int) -> None:
    """Patch ``channels.websocket.port`` in the saved config to ``webui_port``.

    The gateway reads its WebUI port *only* from config (there is no CLI flag
    for it), so when 8765 was occupied and we drifted to another port we must
    write that port back into config before starting the gateway — otherwise it
    would try to bind the old, still-occupied port and fail.

    No-op when no config exists yet (first run: onboarding writes it instead,
    via onboard_server which has already been pinned to the same port).  All
    errors are logged and swallowed: a failure here must not abort the launch.
    """
    try:
        from nanobot.config.loader import get_config_path, load_config, save_config
    except Exception as exc:  # noqa: BLE001
        log.warning("config loader unavailable, cannot patch websocket port: %s", exc)
        return
    path = get_config_path()
    if not path.exists():
        return
    try:
        cfg = load_config(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not load config to patch websocket port: %s", exc)
        return
    ws = getattr(cfg.channels, "websocket", None)
    ws = dict(ws) if isinstance(ws, dict) else {}
    if ws.get("port") == webui_port:
        return  # already matches; nothing to write
    ws["port"] = webui_port
    ws.setdefault("enabled", True)
    try:
        cfg.channels.websocket = ws
        save_config(cfg, path)
        log.info("patched channels.websocket.port → %d", webui_port)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not save patched websocket port: %s", exc)


def main() -> int:
    import ports as ports_mod
    from onboard_server import (
        OnboardRouter,
        ROUTER_PORT,
        configure_webui_port,
        config_is_configured,
    )

    log.info("=== launcher start (python=%s) ===", sys.executable)

    # 0. Resolve ports.  The router port is Pake-baked (immutable): if it is
    #    already taken we must NOT silently drift it — the Pake window would
    #    still navigate to the baked port and see connection-refused.  Tell our
    #    own instance (→ exit cleanly, single-instance) apart from a foreign app
    #    (→ clear error).  24691 is picked to make this almost never happen.
    if ports_mod.port_in_use(ROUTER_PORT):
        if ports_mod.probe_nanobot_router(ROUTER_PORT):
            log.info(
                "another nanobot desktop is already serving on :%d — "
                "not starting a second instance", ROUTER_PORT,
            )
            return 0
        log.error(
            "router port %d is occupied by a non-nanobot process. The Pake "
            "window is baked to this port and cannot drift. Free port %d "
            "(close the app holding it) and relaunch.",
            ROUTER_PORT, ROUTER_PORT,
        )
        return 1

    # webui (8765) and gateway/health (18790) drift upward to the next free port.
    resolved = ports_mod.resolve_ports(router=ROUTER_PORT)
    if resolved.webui_drifted or resolved.gateway_drifted:
        log.info(
            "port drift: webui %d→%d, gateway %d→%d",
            ports_mod.DEFAULT_WEBUI_PORT, resolved.webui,
            ports_mod.DEFAULT_GATEWAY_PORT, resolved.gateway,
        )
    log.info(
        "resolved ports: router=%d webui=%d gateway=%d",
        resolved.router, resolved.webui, resolved.gateway,
    )

    # Pin the resolved WebUI port into onboard_server so its loader redirect,
    # /api/status probe, and onboarding-written config all agree.
    configure_webui_port(resolved.webui)

    gateway = Gateway(resolved.gateway)
    gateway_ready = threading.Event()

    def bring_up_gateway() -> bool:
        """Start the gateway and wait for the WebUI port. Returns True if up."""
        gateway.start()
        for _ in range(90):
            if _port_open(resolved.webui):
                log.info("gateway is up (webui on %d)", resolved.webui)
                return True
            time.sleep(1)
        log.error("gateway did not come up (webui port %d)", resolved.webui)
        return False

    def on_setup() -> None:
        """Called by the router after the user submits the web onboarding form.

        By now config.json exists, so the gateway can finally start.
        """
        gateway.stop()
        bring_up_gateway()
        gateway_ready.set()

    # 1. router first — binds instantly, so the Pake window is never refused.
    router = OnboardRouter(on_setup=on_setup, ready_event=gateway_ready)
    router.start()
    log.info("router up on %d", ROUTER_PORT)

    # 2. only start the gateway when a provider is already configured.
    #    On first run there is none → the router serves the web onboarding, and
    #    the gateway is launched via on_setup() once the user submits it.
    if config_is_configured():
        log.info("config present — starting gateway immediately")
        _ensure_webui_port_in_config(resolved.webui)
        bring_up_gateway()
    else:
        log.info("no config yet — waiting for web onboarding before starting gateway")

    # 3. open the single Pake window at the router (loader handles the wait).
    pake = launch_pake(f"http://127.0.0.1:{ROUTER_PORT}")

    # 4. keep alive until the window closes.
    try:
        if pake is not None:
            pake.wait()
            log.info("pake window closed")
        else:
            while gateway.is_running():
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        gateway.stop()
        router.stop()
        log.info("=== launcher exit ===")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log.exception("launcher crashed")
        raise
