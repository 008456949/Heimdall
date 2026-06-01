#!/usr/bin/env python3
"""
status.py — Heimdall health check and live stats.

Usage:
    python status.py          # full status report
    python status.py --watch  # refresh every 3 seconds
"""

import sys
import time
import argparse
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def _check_process(name: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["pgrep", "-f", name], capture_output=True, text=True
    )
    pids = result.stdout.strip().split()
    if pids:
        return True, f"running (PID {', '.join(pids)})"
    return False, "not running"


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def _fmt_cost(usd: float) -> str:
    return f"${usd:.4f}"


def print_status():
    db_path = Path.home() / ".heimdall" / "dashboard.db"

    print()
    print("  ⬡  Heimdall Status")
    print("  " + "─" * 46)

    # Process checks
    daemon_ok, daemon_msg = _check_process("heimdall.daemon")
    mitm_ok,   mitm_msg   = _check_process("mitmdump")
    menubar_ok, menubar_msg = _check_process("heimdall.ui.menubar")

    d = "✓" if daemon_ok     else "✗"
    m = "✓" if mitm_ok       else "✗"
    u = "✓" if menubar_ok    else "✗"

    print(f"  {d}  Daemon       {daemon_msg}")
    print(f"  {m}  Interceptor  {mitm_msg}")
    print(f"  {u}  Menubar      {menubar_msg}")
    print()

    # DB stats
    if not db_path.exists():
        print("  ✗  Database not found — run: python run.py")
        print()
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Latest snapshot
    snap = conn.execute(
        "SELECT * FROM system_snapshots ORDER BY ts DESC LIMIT 1"
    ).fetchone()

    if snap:
        ram_pct = round(snap["ram_used_mb"] / snap["ram_total_mb"] * 100)
        age = int(time.time()) - snap["ts"]
        print(f"  System  (last update: {age}s ago)")
        print(f"    CPU  {snap['cpu_pct']:.1f}%   RAM  {ram_pct}%  "
              f"({snap['ram_used_mb']//1024:.1f}GB / {snap['ram_total_mb']//1024:.1f}GB)")
    else:
        print("  System  no snapshots yet")

    print()

    # Token spend
    now = int(time.time())
    for label, since in [("Today", now - 86400), ("This week", now - 604800),
                          ("This month", now - 2592000)]:
        row = conn.execute(
            "SELECT SUM(tokens_in) ti, SUM(tokens_out) to_, SUM(cost_usd) cost "
            "FROM token_usage WHERE ts > ?", (since,)
        ).fetchone()
        ti    = row["ti"]   or 0
        to_   = row["to_"]  or 0
        cost  = row["cost"] or 0.0
        total = ti + to_
        print(f"  AI spend — {label:<11}  {_fmt_cost(cost):<10}  {_fmt_tokens(total)} tokens")

    print()

    # Per-provider breakdown (this month)
    rows = conn.execute(
        """SELECT provider, SUM(tokens_in) ti, SUM(tokens_out) to_, SUM(cost_usd) cost
           FROM token_usage WHERE ts > ?
           GROUP BY provider ORDER BY cost DESC""",
        (now - 2592000,)
    ).fetchall()

    if rows:
        print("  By provider (this month):")
        for r in rows:
            total = (r["ti"] or 0) + (r["to_"] or 0)
            print(f"    {r['provider']:<14}  {_fmt_cost(r['cost'] or 0):<10}  "
                  f"{_fmt_tokens(total)} tokens")
        print()

    # Recent alerts
    alerts = conn.execute(
        "SELECT * FROM alerts ORDER BY ts DESC LIMIT 3"
    ).fetchall()
    if alerts:
        print("  Recent alerts:")
        for a in alerts:
            age = int(time.time()) - a["ts"]
            print(f"    [{a['kind']}]  {a['message'][:50]}  ({age}s ago)")
        print()

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Heimdall status")
    parser.add_argument("--watch", action="store_true",
                        help="Refresh every 3 seconds (Ctrl-C to stop)")
    args = parser.parse_args()

    if args.watch:
        try:
            while True:
                print("\033[2J\033[H", end="")  # clear screen
                print_status()
                time.sleep(3)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        print_status()


if __name__ == "__main__":
    main()
