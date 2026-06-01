"""
collectors/system.py — CPU + memory snapshot collector.

Captures per-sample system state and fires alerts on sustained pressure.
psutil AccessDenied for cross-user processes is handled gracefully.
"""

import psutil
import logging

from heimdall.collectors.base import BaseCollector
from heimdall.db.database import write_snapshot, write_alert
from heimdall import config

logger = logging.getLogger(__name__)

_cpu_spike_streak = 0
_ram_spike_streak = 0


class SystemCollector(BaseCollector):
    name = "system"

    def collect(self) -> dict:
        global _cpu_spike_streak, _ram_spike_streak

        # 1-second blocking sample for accurate CPU reading
        cpu_pct = psutil.cpu_percent(interval=1)

        mem = psutil.virtual_memory()
        ram_used_mb  = mem.used  // (1024 * 1024)
        ram_total_mb = mem.total // (1024 * 1024)
        ram_pct      = mem.percent

        top_procs = self._top_procs()
        write_snapshot(self.conn, cpu_pct, ram_used_mb, ram_total_mb, top_procs)

        # Sustained CPU alert
        if cpu_pct >= config.ALERT_CPU_PCT:
            _cpu_spike_streak += 1
            if _cpu_spike_streak == config.ALERT_SPIKE_CONSECUTIVE:
                msg = (f"CPU at {cpu_pct:.0f}% for "
                       f"{config.ALERT_SPIKE_CONSECUTIVE} consecutive samples")
                write_alert(self.conn, "cpu_spike", cpu_pct, msg)
                logger.warning(msg)
        else:
            _cpu_spike_streak = 0

        # Sustained RAM alert
        if ram_pct >= config.ALERT_RAM_PCT:
            _ram_spike_streak += 1
            if _ram_spike_streak == config.ALERT_SPIKE_CONSECUTIVE:
                msg = (f"RAM at {ram_pct:.0f}% "
                       f"({ram_used_mb // 1024:.1f}GB / {ram_total_mb // 1024:.1f}GB)")
                write_alert(self.conn, "ram_pressure", ram_pct, msg)
                logger.warning(msg)
        else:
            _ram_spike_streak = 0

        return {
            "cpu_pct":     cpu_pct,
            "ram_pct":     ram_pct,
            "ram_used_mb": ram_used_mb,
            "top_proc":    top_procs[0]["name"] if top_procs else "—",
        }

    def _top_procs(self) -> list[dict]:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                info = p.info
                procs.append({
                    "pid":     info["pid"],
                    "name":    (info["name"] or "unknown")[:40],
                    "cpu_pct": round(info["cpu_percent"] or 0.0, 1),
                    "ram_mb":  (info["memory_info"].rss // (1024 * 1024))
                               if info["memory_info"] else 0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return sorted(procs, key=lambda x: x["cpu_pct"], reverse=True)[
            : config.TOP_PROCS_COUNT
        ]
