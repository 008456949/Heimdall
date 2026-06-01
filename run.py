#!/usr/bin/env python3
"""
run.py — Heimdall application launcher.

Starts all three components as coordinated processes:
  1. Daemon        — background collector (CPU, RAM, token API polling)
  2. Interceptor   — mitmproxy local proxy (captures every AI API call)
  3. Menubar       — macOS menubar app (reads from SQLite, shows live data)

Usage:
    python run.py                  # start everything
    python run.py --no-interceptor # skip mitmproxy (useful for first run / debugging)
    python run.py --daemon-only    # background collector only, no UI
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

# ── bootstrap: make sure we're running from the repo root ─────────────────────
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("heimdall.run")


# ── pre-flight checks ─────────────────────────────────────────────────────────

def check_python_version():
    if sys.version_info < (3, 11):
        sys.exit("❌  Python 3.11+ required. Current: " + sys.version)


def check_dependencies():
    missing = []
    for pkg in ["psutil", "rumps"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        sys.exit(
            f"❌  Missing packages: {', '.join(missing)}\n"
            f"    Run:  pip install -r requirements.txt"
        )


def check_mitmproxy():
    result = subprocess.run(
        ["which", "mitmdump"], capture_output=True, text=True
    )
    if result.returncode != 0:
        return False, "mitmdump not found — install: brew install mitmproxy"
    return True, result.stdout.strip()


def check_cert():
    from heimdall.config import CERT_PATH
    if not CERT_PATH.exists():
        return False, f"mitmproxy cert not found at {CERT_PATH}"
    return True, str(CERT_PATH)


def check_db():
    from heimdall.config import DB_PATH
    from heimdall.db.database import get_connection, init_schema
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(DB_PATH)
    init_schema(conn)
    conn.close()
    return True, str(DB_PATH)


def preflight(skip_interceptor: bool) -> bool:
    """Run all pre-flight checks. Return True if safe to start."""
    log.info("Running pre-flight checks…")
    ok = True

    check_python_version()
    check_dependencies()

    _, db_path = check_db()
    log.info("  ✓ database: %s", db_path)

    if not skip_interceptor:
        mitm_ok, mitm_msg = check_mitmproxy()
        if mitm_ok:
            log.info("  ✓ mitmproxy: %s", mitm_msg)
        else:
            log.warning("  ⚠  %s  (run with --no-interceptor to skip)", mitm_msg)
            ok = False

        cert_ok, cert_msg = check_cert()
        if cert_ok:
            log.info("  ✓ cert: %s", cert_msg)
        else:
            log.warning("  ⚠  %s", cert_msg)
            log.warning("     Run: bash scripts/setup.sh  to install the cert")
            ok = False

    return ok


# ── process management ────────────────────────────────────────────────────────

_children: list[subprocess.Popen] = []


def _start_daemon() -> subprocess.Popen:
    """Start the Heimdall background daemon as a subprocess."""
    log.info("Starting daemon…")
    proc = subprocess.Popen(
        [sys.executable, "-m", "heimdall.daemon"],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    _children.append(proc)
    log.info("  ✓ daemon PID %d", proc.pid)
    return proc


def _start_interceptor() -> subprocess.Popen:
    """Start the mitmproxy interceptor as a subprocess."""
    log.info("Starting interceptor…")
    proc = subprocess.Popen(
        [
            "mitmdump",
            "--mode", "local",
            "--quiet",
            "-s", str(ROOT / "interceptor" / "proxy.py"),
        ],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    _children.append(proc)
    log.info("  ✓ interceptor PID %d", proc.pid)
    return proc


def _watchdog(procs: list[subprocess.Popen], stop: threading.Event) -> None:
    """
    Watchdog thread: restarts any child that dies unexpectedly.
    Stops cleanly when stop event is set.
    """
    restart_map = {
        "daemon":      _start_daemon,
        "interceptor": _start_interceptor,
    }
    # Build name → proc mapping (by index in procs list)
    while not stop.is_set():
        for proc in list(_children):
            if proc.poll() is not None:  # process has exited
                rc = proc.returncode
                log.warning(
                    "Child PID %d exited (rc=%d) — restarting in 5s…",
                    proc.pid, rc
                )
                time.sleep(5)
                _children.remove(proc)
                # Re-start based on which script died
                if "daemon" in " ".join(proc.args):
                    _start_daemon()
                elif "mitmdump" in " ".join(proc.args):
                    _start_interceptor()
        stop.wait(timeout=3)


def _shutdown(sig, _frame):
    """Graceful shutdown: terminate all children, then exit."""
    log.info("Shutting down Heimdall (signal %d)…", sig)
    for proc in _children:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
    # Give them 3s to terminate cleanly
    for proc in _children:
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    log.info("All processes stopped. Goodbye.")
    sys.exit(0)


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Heimdall — macOS AI token interceptor + developer dashboard"
    )
    parser.add_argument(
        "--no-interceptor",
        action="store_true",
        help="Skip mitmproxy interceptor (useful for debugging or first run)",
    )
    parser.add_argument(
        "--daemon-only",
        action="store_true",
        help="Start daemon only, no menubar UI (for headless/server use)",
    )
    args = parser.parse_args()

    # Signal handlers
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    print()
    print("  ⬡  Heimdall  — the Bifrost between you and your AI spend")
    print()

    # Pre-flight
    if not preflight(skip_interceptor=args.no_interceptor):
        print()
        print("  Pre-flight failed. Run  bash scripts/setup.sh  first.")
        print("  Or start with:  python run.py --no-interceptor")
        print()
        sys.exit(1)

    # Start background processes
    _start_daemon()
    time.sleep(1)  # Give daemon a moment to initialize DB

    if not args.no_interceptor:
        _start_interceptor()
        time.sleep(1)

    # Watchdog thread
    stop_event = threading.Event()
    watchdog = threading.Thread(
        target=_watchdog, args=(_children, stop_event), daemon=True
    )
    watchdog.start()

    if args.daemon_only:
        log.info("Running in daemon-only mode. Ctrl-C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            _shutdown(signal.SIGINT, None)
        return

    # Start menubar — MUST be on main thread (macOS requirement)
    log.info("Starting menubar UI…")
    try:
        from heimdall.ui.menubar import main as menubar_main
        menubar_main()  # blocks until menubar is quit
    except Exception as e:
        log.error("Menubar crashed: %s", e)
    finally:
        stop_event.set()
        _shutdown(signal.SIGTERM, None)


if __name__ == "__main__":
    main()
