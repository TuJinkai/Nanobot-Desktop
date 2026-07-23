"""nanobot Desktop — backend lifecycle manager (zero-console).

Run via ``pythonw.exe`` so NO console window ever appears.

Flow:
  1. Start the frontend router on 8766 (binds instantly → Pake never sees
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

ROUTER_PORT = 8766
GATEWAY_WS_PORT = 8765
GATEWAY_HEALTH_PORT = 18790


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
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.stop()
        cmd = [
            _pythonw_exe(), "-m", "nanobot", "gateway",
            "--foreground", "--port", str(GATEWAY_HEALTH_PORT),
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


def main() -> int:
    from onboard_server import OnboardRouter, ROUTER_PORT, GATEWAY_PORT, config_is_configured

    log.info("=== launcher start (python=%s) ===", sys.executable)
    gateway = Gateway()
    gateway_ready = threading.Event()

    def bring_up_gateway() -> bool:
        """Start the gateway and wait for its port. Returns True if up."""
        gateway.start()
        for _ in range(90):
            if _port_open(GATEWAY_PORT):
                log.info("gateway is up on %d", GATEWAY_PORT)
                return True
            time.sleep(1)
        log.error("gateway did not come up on %d", GATEWAY_PORT)
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
