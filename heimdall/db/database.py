"""
db/database.py — single source of truth for all DB operations.

One connection, one schema, one file.
Thread-safe via check_same_thread=False (daemon + UI share this).
"""

import sqlite3
import json
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads + writes
    conn.execute("PRAGMA synchronous=NORMAL")  # faster writes, safe enough
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS system_snapshots (
            ts           INTEGER PRIMARY KEY,
            cpu_pct      REAL,
            ram_used_mb  INTEGER,
            ram_total_mb INTEGER,
            top_procs    TEXT     -- JSON: [{pid,name,cpu_pct,ram_mb}]
        );

        CREATE TABLE IF NOT EXISTS token_usage (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         INTEGER NOT NULL,
            provider   TEXT NOT NULL,  -- anthropic | openai | ollama
            app        TEXT NOT NULL,  -- cursor | claude_desktop | api | unknown
            model      TEXT DEFAULT '',
            git_repo   TEXT DEFAULT '',
            git_branch TEXT DEFAULT '',
            tokens_in  INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            cost_usd   REAL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      INTEGER NOT NULL,
            kind    TEXT NOT NULL,   -- cpu_spike | ram_pressure | spend_daily | spend_monthly
            value   REAL,
            message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_ts
            ON system_snapshots(ts);
        CREATE INDEX IF NOT EXISTS idx_tokens_ts
            ON token_usage(ts);
        CREATE INDEX IF NOT EXISTS idx_tokens_provider
            ON token_usage(provider, ts);
        CREATE INDEX IF NOT EXISTS idx_tokens_app
            ON token_usage(app, ts);
    """)
    conn.commit()
    logger.debug("Schema initialized")


# ── writers ───────────────────────────────────────────────────────────────────

def write_snapshot(conn, cpu_pct: float, ram_used_mb: int,
                   ram_total_mb: int, top_procs: list) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO system_snapshots VALUES (?,?,?,?,?)",
        (int(time.time()), round(cpu_pct, 1), ram_used_mb,
         ram_total_mb, json.dumps(top_procs))
    )
    conn.commit()


def write_token_usage(conn, *, provider: str, app: str, model: str = "",
                      git_repo: str = "", git_branch: str = "",
                      tokens_in: int, tokens_out: int,
                      cost_usd: float) -> None:
    conn.execute(
        """INSERT INTO token_usage
           (ts, provider, app, model, git_repo, git_branch,
            tokens_in, tokens_out, cost_usd)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (int(time.time()), provider, app, model,
         git_repo, git_branch,
         tokens_in, tokens_out, round(cost_usd, 6))
    )
    conn.commit()


def write_alert(conn, kind: str, value: float, message: str) -> None:
    conn.execute(
        "INSERT INTO alerts(ts,kind,value,message) VALUES (?,?,?,?)",
        (int(time.time()), kind, value, message)
    )
    conn.commit()


# ── readers ───────────────────────────────────────────────────────────────────

def latest_snapshot(conn) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM system_snapshots ORDER BY ts DESC LIMIT 1"
    ).fetchone()


def snapshots_last_minutes(conn, minutes: int = 60) -> list:
    since = int(time.time()) - minutes * 60
    return conn.execute(
        "SELECT * FROM system_snapshots WHERE ts > ? ORDER BY ts ASC",
        (since,)
    ).fetchall()


def token_spend(conn, *, provider: str | None = None,
                app: str | None = None, days: int = 30) -> dict:
    """Aggregate token + cost totals for a rolling window."""
    since = int(time.time()) - days * 86400
    conditions = ["ts > ?"]
    params: list = [since]
    if provider:
        conditions.append("provider = ?")
        params.append(provider)
    if app:
        conditions.append("app = ?")
        params.append(app)

    where = " AND ".join(conditions)
    row = conn.execute(
        f"SELECT SUM(tokens_in) ti, SUM(tokens_out) to_, SUM(cost_usd) cost "
        f"FROM token_usage WHERE {where}",
        params
    ).fetchone()
    return {
        "tokens_in":  row["ti"]   or 0,
        "tokens_out": row["to_"]  or 0,
        "cost_usd":   row["cost"] or 0.0,
    }


def token_spend_by_provider(conn, days: int = 30) -> list[dict]:
    since = int(time.time()) - days * 86400
    rows = conn.execute(
        """SELECT provider,
                  SUM(tokens_in)  as tokens_in,
                  SUM(tokens_out) as tokens_out,
                  SUM(cost_usd)   as cost_usd
           FROM token_usage WHERE ts > ?
           GROUP BY provider ORDER BY cost_usd DESC""",
        (since,)
    ).fetchall()
    return [dict(r) for r in rows]


def token_spend_by_model(conn, days: int = 30) -> list[dict]:
    since = int(time.time()) - days * 86400
    rows = conn.execute(
        """SELECT model,
                  SUM(tokens_in)  as tokens_in,
                  SUM(tokens_out) as tokens_out,
                  SUM(cost_usd)   as cost_usd
           FROM token_usage WHERE ts > ?
           GROUP BY model ORDER BY cost_usd DESC""",
        (since,)
    ).fetchall()
    return [dict(r) for r in rows]


def recent_alerts(conn, limit: int = 20) -> list:
    return conn.execute(
        "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()


def prune_old_data(conn, keep_days: int = 90) -> None:
    cutoff = int(time.time()) - keep_days * 86400
    conn.execute("DELETE FROM system_snapshots WHERE ts < ?", (cutoff,))
    conn.execute("DELETE FROM token_usage WHERE ts < ?", (cutoff,))
    conn.execute("DELETE FROM alerts WHERE ts < ?", (cutoff,))
    conn.execute("VACUUM")
    conn.commit()
    logger.info("Pruned data older than %d days", keep_days)
