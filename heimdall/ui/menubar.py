"""
ui/menubar.py — macOS menubar app. Reads from SQLite, never touches psutil.

Run: python3 -m heimdall.ui.menubar
The daemon must be running separately to populate the DB.
"""

import sys
import json
import time
import logging
import subprocess
from pathlib import Path

try:
    import rumps
except ImportError:
    sys.exit("Install rumps:  pip install rumps")

from heimdall import config
from heimdall.db.database import (
    get_connection, init_schema,
    latest_snapshot, token_spend, token_spend_by_provider,
    recent_alerts,
)

logger = logging.getLogger("heimdall.menubar")


def _bar(pct: float, width: int = 8) -> str:
    filled = round(pct / 100 * width)
    return "▓" * filled + "░" * (width - filled) + f" {pct:.0f}%"


def _fmt_mb(mb: int) -> str:
    return f"{mb / 1024:.1f}GB" if mb >= 1024 else f"{mb}MB"


def _age(ts: int) -> str:
    d = int(time.time()) - ts
    if d < 60:   return f"{d}s ago"
    if d < 3600: return f"{d // 60}m ago"
    return f"{d // 3600}h ago"


def _make_submenu(title: str) -> rumps.MenuItem:
    """
    Create a MenuItem with one placeholder child so NSMenu backing
    is created immediately. Without this, calling .clear() on an
    empty MenuItem crashes with 'NoneType has no attribute removeAllItems'.
    """
    item = rumps.MenuItem(title)
    item["—"] = None   # forces NSMenu creation
    return item


class HeimdallApp(rumps.App):

    def __init__(self):
        super().__init__("⬡", quit_button=None)
        self.conn = get_connection(config.DB_PATH)
        init_schema(self.conn)

        # ── system section ────────────────────────────────────────────────────
        self.cpu_item   = rumps.MenuItem("CPU  —")
        self.ram_item   = rumps.MenuItem("RAM  —")
        self.procs_item = _make_submenu("Top processes")

        # ── spend section ─────────────────────────────────────────────────────
        self.today_item = rumps.MenuItem("Today   $0.000")
        self.month_item = rumps.MenuItem("Month   $0.00")
        self.by_prov    = _make_submenu("By provider")

        # ── alerts section ────────────────────────────────────────────────────
        self.alerts_item = _make_submenu("Alerts")

        self.menu = [
            rumps.separator,
            "── System ──",
            self.cpu_item,
            self.ram_item,
            self.procs_item,
            rumps.separator,
            "── AI Spend ──",
            self.today_item,
            self.month_item,
            self.by_prov,
            rumps.separator,
            "── Alerts ──",
            self.alerts_item,
            rumps.separator,
            rumps.MenuItem("Open logs", callback=self._open_logs),
            rumps.MenuItem("Quit Heimdall", callback=rumps.quit_application),
        ]

    @rumps.timer(config.MENUBAR_REFRESH_SECONDS)
    def refresh(self, _):
        try:
            self._refresh_system()
            self._refresh_spend()
            self._refresh_alerts()
        except Exception as e:
            self.title = "⬡ ?"
            logger.error("refresh error: %s", e, exc_info=True)

    # ── system ────────────────────────────────────────────────────────────────

    def _refresh_system(self):
        snap = latest_snapshot(self.conn)
        if not snap:
            self.title = "⬡  no data"
            return

        cpu  = snap["cpu_pct"]
        rpct = round(snap["ram_used_mb"] / snap["ram_total_mb"] * 100) \
               if snap["ram_total_mb"] else 0

        today = token_spend(self.conn, days=1)
        spend_str = f"${today['cost_usd']:.3f}" if today["cost_usd"] > 0 else "$0.000"
        warn = "🔴 " if cpu >= config.ALERT_CPU_PCT else ""
        self.title = f"{warn}⬡ {spend_str}  {cpu:.0f}%"

        self.cpu_item.title = f"CPU  {_bar(cpu)}"
        self.ram_item.title = (
            f"RAM  {_bar(rpct)}  "
            f"{_fmt_mb(snap['ram_used_mb'])} / {_fmt_mb(snap['ram_total_mb'])}"
        )

        self._update_submenu(
            self.procs_item,
            "Top processes",
            [
                f"{p['name'][:26]:<26}  CPU {p['cpu_pct']:5.1f}%  RAM {_fmt_mb(p['ram_mb'])}"
                for p in json.loads(snap["top_procs"] or "[]")[:6]
            ] or ["— no data yet —"],
        )

    # ── spend ─────────────────────────────────────────────────────────────────

    def _refresh_spend(self):
        today = token_spend(self.conn, days=1)
        month = token_spend(self.conn, days=30)

        self.today_item.title = (
            f"Today   ${today['cost_usd']:.3f}  "
            f"({today['tokens_in'] + today['tokens_out']:,} tok)"
        )
        self.month_item.title = (
            f"Month   ${month['cost_usd']:.2f}  "
            f"({month['tokens_in'] + month['tokens_out']:,} tok)"
        )

        rows = token_spend_by_provider(self.conn, days=30)
        lines = [
            f"{r['provider'].capitalize():<14}${r['cost_usd']:.3f}  "
            f"{r['tokens_in'] + r['tokens_out']:,} tok"
            for r in rows if (r["tokens_in"] or 0) + (r["tokens_out"] or 0) > 0
        ] or ["— no usage recorded yet —"]

        self._update_submenu(self.by_prov, "By provider", lines)

    # ── alerts ────────────────────────────────────────────────────────────────

    def _refresh_alerts(self):
        alerts = recent_alerts(self.conn, limit=5)
        if not alerts:
            self.alerts_item.title = "Alerts  none"
            self._update_submenu(self.alerts_item, "Alerts  none", ["— all clear —"])
            return

        lines = [
            f"[{a['kind']}]  {a['message'][:48]}  ({_age(a['ts'])})"
            for a in alerts
        ]
        self._update_submenu(self.alerts_item, f"Alerts  {len(alerts)}", lines)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _update_submenu(item: rumps.MenuItem, title: str, lines: list[str]):
        """Safely clear and repopulate a submenu."""
        item.title = title
        # Remove all existing children
        for key in list(item.keys()):
            del item[key]
        # Add new children
        for line in lines:
            item[line] = None

    def _open_logs(self, _):
        subprocess.run(["open", str(config.HOME_DIR)])


def main():
    logging.basicConfig(level=logging.INFO)
    HeimdallApp().run()


if __name__ == "__main__":
    main()
