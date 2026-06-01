"""
daemon.py — core scheduler. Run this as a background process via launchd.

Starts each collector in its own thread on a configurable interval.
Clean shutdown on SIGTERM/SIGINT. One shared SQLite connection.
"""

import os
import sys
import signal
import threading
import time
import logging
from pathlib import Path

from heimdall import config
from heimdall.db.database import get_connection, init_schema, prune_old_data
from heimdall.collectors.system import SystemCollector
from heimdall.collectors.tokens_api import TokenAPICollector

# ── logging ───────────────────────────────────────────────────────────────────
config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("heimdall.daemon")

# ── shutdown ──────────────────────────────────────────────────────────────────
_shutdown = threading.Event()


def _handle_signal(signum, _frame):
    logger.info("Signal %d received — shutting down cleanly", signum)
    _shutdown.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)


# ── collector runner ──────────────────────────────────────────────────────────

def _run_collector(collector, interval: int) -> None:
    """
    Collect → sleep → collect → …
    Sleep is broken into 1s chunks so shutdown is always responsive.
    """
    logger.info("[%s] started (interval=%ds)", collector.name, interval)
    while not _shutdown.is_set():
        result = collector.safe_collect()
        logger.debug("[%s] %s", collector.name, result)
        for _ in range(interval):
            if _shutdown.is_set():
                break
            time.sleep(1)
    logger.info("[%s] stopped", collector.name)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=== Heimdall daemon starting (PID %d) ===", os.getpid())

    conn = get_connection(config.DB_PATH)
    init_schema(conn)
    prune_old_data(conn, keep_days=config.KEEP_HISTORY_DAYS)

    # Register collectors: (instance, interval_seconds)
    # Add new collectors here — nothing else to change
    schedule = [
        (SystemCollector(conn),   config.INTERVAL_SYSTEM_METRICS),
        (TokenAPICollector(conn), config.INTERVAL_TOKEN_API),
    ]

    threads = []
    for collector, interval in schedule:
        t = threading.Thread(
            target=_run_collector,
            args=(collector, interval),
            name=f"collector-{collector.name}",
            daemon=True,
        )
        t.start()
        threads.append(t)

    logger.info("%d collectors running. Ctrl-C or SIGTERM to stop.", len(threads))
    _shutdown.wait()

    logger.info("Waiting for threads to finish…")
    for t in threads:
        t.join(timeout=5)

    conn.close()
    logger.info("=== Heimdall daemon stopped ===")


if __name__ == "__main__":
    main()
