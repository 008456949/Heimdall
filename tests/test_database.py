"""Tests for the SQLite DB layer."""
import sqlite3
import time
import pytest
from heimdall.db.database import init_schema, write_snapshot, write_token_usage, write_alert
from heimdall.db.database import latest_snapshot, token_spend, recent_alerts


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)
    yield c
    c.close()


def test_snapshot_roundtrip(conn):
    procs = [{"pid": 1, "name": "Python", "cpu_pct": 12.0, "ram_mb": 100}]
    write_snapshot(conn, 55.0, 8192, 16384, procs)
    snap = latest_snapshot(conn)
    assert snap is not None
    assert snap["cpu_pct"] == 55.0
    assert snap["ram_used_mb"] == 8192


def test_token_spend_accumulates(conn):
    write_token_usage(conn, provider="anthropic", app="cursor", model="claude-sonnet-4-5",
                      tokens_in=1000, tokens_out=500, cost_usd=0.01)
    write_token_usage(conn, provider="openai", app="python", model="gpt-4o",
                      tokens_in=2000, tokens_out=800, cost_usd=0.02)
    total = token_spend(conn, days=30)
    assert total["tokens_in"] == 3000
    assert total["tokens_out"] == 1300
    assert abs(total["cost_usd"] - 0.03) < 1e-6


def test_token_spend_by_provider(conn):
    write_token_usage(conn, provider="anthropic", app="cursor", model="",
                      tokens_in=1000, tokens_out=200, cost_usd=0.005)
    anthropic = token_spend(conn, provider="anthropic", days=1)
    openai    = token_spend(conn, provider="openai",    days=1)
    assert anthropic["tokens_in"] == 1000
    assert openai["tokens_in"] == 0


def test_alerts(conn):
    write_alert(conn, "cpu_spike", 88.0, "CPU at 88%")
    alerts = recent_alerts(conn)
    assert len(alerts) == 1
    assert alerts[0]["kind"] == "cpu_spike"


def test_parsers_anthropic():
    from interceptor.parsers.anthropic import parse
    body = '{"id":"msg_01","model":"claude-sonnet-4-5","usage":{"input_tokens":150,"output_tokens":75}}'
    result = parse("/v1/messages", body, {"content-type": "application/json"})
    assert result is not None
    assert result["provider"] == "anthropic"
    assert result["tokens_in"] == 150
    assert result["tokens_out"] == 75


def test_parsers_ollama():
    from interceptor.parsers.ollama import parse
    body = '{"model":"llama3.2","done":false,"response":"Hello"}\n{"model":"llama3.2","done":true,"prompt_eval_count":12,"eval_count":8}'
    result = parse("/api/generate", body)
    assert result is not None
    assert result["provider"] == "ollama"
    assert result["tokens_in"] == 12
    assert result["tokens_out"] == 8
