#!/usr/bin/env python3
"""
run.py — Heimdall application launcher.

Starts all three components as coordinated processes:
  1. Daemon        — background collector (CPU, RAM, token API polling)
  2. Interceptor   — mitmproxy local proxy (captures every AI API call)
  3. Menubar       — macOS menubar app (reads from SQLite, shows live data)

Usage:
    python3 run.py                  # start everything
    python3 run.py --no-interceptor # skip mitmproxy (useful for first run / debugging)
    python3 run.py --daemon-only    # background collector only, no UI
"""

import argparse
import os
import signal
import subprocess
import sys
import time
import threading
import logging
from pathlib import Path

# ── bootstrap ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("heimdall.run")

# ── find the right python executable ─────────────────────────────────────────
def _find_python() -> str:
    """
    Prefer the venv python so subprocesses have all packages installed.
    Falls back to sys.executable (works when venv is already activated).
    """
    venv_python = ROOT / ".venv" / "bin" / "python3"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


PYTHON = _find_python()


# ── pre-flight checks ─────────────────────────────────────────────────────────

def check_dependencies() -> bool:
    missing = []
    for pkg in ["psutil", "rumps"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        log.error(
            "Missing packages: %s\n"
            "  Run:  pip install -r requirements.txt\n"
            "  Or:   source .venv/bin/activate  (if you used setup.sh)",
            ", ".join(missing),
        )
        return False
    return True


def check_mitmproxy() -> tuple[bool, str]:
    result = subprocess.run(["which", "mitmdump"], capture_output=True, text=True)
    if result.returncode != 0:
        return False, "mitmdump not found — install: brew install mitmproxy"
    return True, result.stdout.strip()


def check_cert() -> tuple[bool, str]:
    from heimdall.config import CERT_PATH
    if not CERT_PATH.exists():
        return False, f"mitmproxy cert not found at {CERT_PATH}"
    return True, str(CERT_PATH)


def check_db() -> tuple[bool, str]:
    from heimdall.config import DB_PATH
    from heimdall.db.database import get_connection, init_schema
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(DB_PATH)
    init_schema(conn)
    conn.close()
    return True, str(DB_PATH)


def preflight(skip_interceptor: bool) -> bool:
    log.info("Running pre-flight checks…")

    if not check_dependencies():
        return False

    _, db_path = check_db()
    log.info("  ✓ database: %s", db_path)
    log.info("  ✓ python:   %s", PYTHON)

    if not skip_interceptor:
        mitm_ok, mitm_msg = check_mitmproxy()
        if mitm_ok:
            log.info("  ✓ mitmproxy: %s", mitm_msg)
        else:
            log.warning("  ⚠  %s", mitm_msg)
            log.warning("     Run with --no-interceptor to skip, or: brew install mitmproxy")
            return False

        cert_ok, cert_msg = check_cert()
        if cert_ok:
            log.info("  ✓ cert: %s", cert_msg)
        else:
            log.warning("  ⚠  %s", cert_msg)
            log.warning("     Run: bash scripts/setup.sh")
            return False

    return True


# ── process management ────────────────────────────────────────────────────────

_children: list[subprocess.Popen] = []


def _env() -> dict:
    """Environment for subprocesses — ensures project root is on PYTHONPATH."""
    return {**os.environ, "PYTHONPATH": str(ROOT)}


def _start_daemon() -> subprocess.Popen:
    log.info("Starting daemon…")
    proc = subprocess.Popen(
        [PYTHON, "-m", "heimdall.daemon"],
        cwd=str(ROOT),
        env=_env(),
    )
    _children.append(proc)
    # Give daemon 1s to initialize before checking it
    time.sleep(1)
    if proc.poll() is not None:
        log.error("Daemon failed to start (exit code %d) — check logs at ~/.heimdall/daemon.log", proc.returncode)
    else:
        log.info("  ✓ daemon PID %d", proc.pid)
    return proc


def _start_interceptor() -> subprocess.Popen:
    log.info("Starting interceptor…")
    proc = subprocess.Popen(
        [
            "mitmdump",
            "--mode", "local",
            "--quiet",
            "-s", str(ROOT / "interceptor" / "proxy.py"),
        ],
        cwd=str(ROOT),
        env=_env(),
    )
    _children.append(proc)
    time.sleep(1)
    if proc.poll() is not None:
        log.error("Interceptor failed to start — check System Settings → Privacy & Security → Network Extensions")
    else:
        log.info("  ✓ interceptor PID %d", proc.pid)
    return proc


def _watchdog(stop: threading.Event) -> None:
    while not stop.is_set():
        for proc in list(_children):
            if proc.poll() is not None:
                rc = proc.returncode
                log.warning("Child PID %d exited (rc=%d) — restarting in 5s…", proc.pid, rc)
                stop.wait(timeout=5)
                if stop.is_set():
                    break
                _children.remove(proc)
                if "heimdall.daemon" in " ".join(proc.args):
                    _start_daemon()
                elif "mitmdump" in proc.args[0]:
                    _start_interceptor()
        stop.wait(timeout=3)


def _shutdown(sig=None, _frame=None):
    log.info("Shutting down Heimdall…")
    for proc in _children:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
    for proc in _children:
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    log.info("Stopped. Goodbye.")
    sys.exit(0)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Heimdall — macOS AI token interceptor + developer dashboard"
    )
    parser.add_argument("--no-interceptor", action="store_true",
                        help="Skip mitmproxy (for testing or first run)")
    parser.add_argument("--daemon-only", action="store_true",
                        help="Start daemon only, no menubar UI")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    print()
    print("  ⬡  Heimdall  — the Bifrost between you and your AI spend")
    print()

    if not preflight(skip_interceptor=args.no_interceptor):
        print()
        print("  Pre-flight failed. See errors above.")
        print("  Quick start:  source .venv/bin/activate && python3 run.py --no-interceptor")
        print()
        sys.exit(1)

    _start_daemon()

    if not args.no_interceptor:
        _start_interceptor()

    stop_event = threading.Event()
    watchdog = threading.Thread(target=_watchdog, args=(stop_event,), daemon=True)
    watchdog.start()

    if args.daemon_only:
        log.info("Daemon-only mode. Ctrl-C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            _shutdown()
        return

    log.info("Starting menubar UI…")
    try:
        from heimdall.ui.menubar import main as menubar_main
        menubar_main()
    except Exception as e:
        log.error("Menubar error: %s", e, exc_info=True)
    finally:
        stop_event.set()
        _shutdown()


if __name__ == "__main__":
    main()
