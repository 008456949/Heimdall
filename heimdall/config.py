"""
config.py — all tunables in one place.

Edit this file to change API keys, thresholds, and intervals.
The daemon reads this at startup; restart to apply changes.
Never commit real API keys — use environment variables in production.
"""

import os
from pathlib import Path

# ── paths ─────────────────────────────────────────────────────────────────────
HOME_DIR    = Path.home() / ".heimdall"
DB_PATH     = HOME_DIR / "dashboard.db"
LOG_PATH    = HOME_DIR / "daemon.log"
ERR_PATH    = HOME_DIR / "daemon.err"
CERT_PATH   = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"

CLAUDE_DESKTOP_LOG = Path.home() / "Library/Logs/Claude/mcp.log"

# ── API keys (prefer env vars over hardcoding) ────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")

# ── collector intervals (seconds) ─────────────────────────────────────────────
INTERVAL_SYSTEM_METRICS = 3      # cpu + memory
INTERVAL_TOKEN_API      = 300    # poll usage APIs (5 min)
INTERVAL_OLLAMA         = 10     # local Ollama health

# ── alert thresholds ──────────────────────────────────────────────────────────
ALERT_CPU_PCT          = 85.0    # sustained CPU % to fire alert
ALERT_RAM_PCT          = 90.0    # RAM % threshold
ALERT_DAILY_SPEND      = 5.00    # USD — daily token spend limit
ALERT_MONTHLY_SPEND    = 20.00   # USD — monthly token spend limit
ALERT_SPIKE_CONSECUTIVE = 3      # consecutive samples before firing

# ── interceptor ───────────────────────────────────────────────────────────────
PROXY_PORT = 8080

# AI endpoint hostnames the interceptor cares about
AI_HOSTS = {
    "api.anthropic.com",
    "api.openai.com",
    "localhost",       # Ollama
    "127.0.0.1",       # Ollama alt
}

# Cloud-to-local routing: prompts under this token count go to Ollama
OLLAMA_ROUTING_ENABLED   = False   # set True once Ollama is configured
OLLAMA_ROUTING_THRESHOLD = 2000    # tokens — route below this to local
OLLAMA_HOST              = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL     = "llama3.2"

# ── display ───────────────────────────────────────────────────────────────────
TOP_PROCS_COUNT         = 8
MENUBAR_REFRESH_SECONDS = 3
KEEP_HISTORY_DAYS       = 90

# ── pricing (USD per 1K tokens) ───────────────────────────────────────────────
# Update these when Anthropic/OpenAI change pricing
PRICING = {
    "anthropic": {
        "claude-opus-4-5":        {"in": 0.015, "out": 0.075},
        "claude-sonnet-4-5":      {"in": 0.003, "out": 0.015},
        "claude-haiku-4-5":       {"in": 0.0008, "out": 0.004},
        "default":                {"in": 0.003, "out": 0.015},
    },
    "openai": {
        "gpt-4o":                 {"in": 0.005, "out": 0.015},
        "gpt-4o-mini":            {"in": 0.00015, "out": 0.0006},
        "o1":                     {"in": 0.015, "out": 0.060},
        "default":                {"in": 0.005, "out": 0.015},
    },
    "ollama": {
        "default":                {"in": 0.0, "out": 0.0},  # free, local
    },
}


def get_price(provider: str, model: str) -> dict:
    """Return {in, out} price per 1K tokens for a given provider + model."""
    provider_prices = PRICING.get(provider, {})
    for key in provider_prices:
        if key != "default" and key in model:
            return provider_prices[key]
    return provider_prices.get("default", {"in": 0.0, "out": 0.0})
