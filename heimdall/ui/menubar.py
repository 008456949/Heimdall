"""
ui/menubar.py — macOS menubar app. Reads from SQLite, never touches psutil.

Run: python -m heimdall.ui.menubar
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


class HeimdallApp(rumps.App):

    def __init__(self):
        super().__init__("⬡", quit_button=None)
        self.conn = get_connection(config.DB_PATH)
        init_schema(self.conn)

        # system section
        self.cpu_item    = rumps.MenuItem("CPU  —")
        self.ram_item    = rumps.MenuItem("RAM  —")
        self.procs_item  = rumps.MenuItem("Processes")

        # spend section
        self.today_item  = rumps.MenuItem("Today   —")
        self.month_item  = rumps.MenuItem("Month   —")
        self.by_prov     = rumps.MenuItem("By provider")

        # alerts section
        self.alerts_item = rumps.MenuItem("Alerts  —")

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
            logger.error("refresh error: %s", e)

    def _refresh_system(self):
        snap = latest_snapshot(self.conn)
        if not snap:
            self.title = "⬡"
            return

        cpu  = snap["cpu_pct"]
        rpct = round(snap["ram_used_mb"] / snap["ram_total_mb"] * 100) if snap["ram_total_mb"] else 0

        # Today's spend for icon
        today = token_spend(self.conn, days=1)
        spend_str = f"${today['cost_usd']:.3f}" if today["cost_usd"] > 0 else ""
        warn = "🔴 " if cpu >= config.ALERT_CPU_PCT else ""
        self.title = f"{warn}⬡ {spend_str}  CPU {cpu:.0f}%"

        self.cpu_item.title = f"CPU  {_bar(cpu)}"
        self.ram_item.title = (
            f"RAM  {_bar(rpct)}  "
            f"{_fmt_mb(snap['ram_used_mb'])} / {_fmt_mb(snap['ram_total_mb'])}"
        )

        procs = json.loads(snap["top_procs"] or "[]")
        self.procs_item.clear()
        for p in procs[:6]:
            label = f"{p['name'][:26]:<26}  CPU {p['cpu_pct']:5.1f}%  RAM {_fmt_mb(p['ram_mb'])}"
            self.procs_item[label] = None

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

        self.by_prov.clear()
        for row in token_spend_by_provider(self.conn, days=30):
            if row["tokens_in"] + row["tokens_out"] == 0:
                continue
            label = (
                f"{row['provider'].capitalize():<14}"
                f"${row['cost_usd']:.3f}  "
                f"{row['tokens_in'] + row['tokens_out']:,} tok"
            )
            self.by_prov[label] = None

    def _refresh_alerts(self):
        alerts = recent_alerts(self.conn, limit=5)
        if not alerts:
            self.alerts_item.title = "Alerts  none"
            self.alerts_item.clear()
            return

        self.alerts_item.title = f"Alerts  {len(alerts)} recent"
        self.alerts_item.clear()
        for a in alerts:
            label = f"[{a['kind']}]  {a['message'][:48]}  ({_age(a['ts'])})"
            self.alerts_item[label] = None

    def _open_logs(self, _):
        subprocess.run(["open", str(config.HOME_DIR)])


def main():
    logging.basicConfig(level=logging.INFO)
    HeimdallApp().run()


if __name__ == "__main__":
    main()
