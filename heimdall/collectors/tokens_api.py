"""
collectors/tokens_api.py — polls Anthropic + OpenAI usage APIs.

Stores deltas (not cumulative totals) so rows are additive.
Falls back gracefully when keys are missing or endpoints are unreachable.
"""

import json
import time
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone

from heimdall.collectors.base import BaseCollector
from heimdall.db.database import write_token_usage, write_alert, token_spend
from heimdall import config

logger = logging.getLogger(__name__)


def _http_get(url: str, headers: dict) -> dict | None:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        logger.warning("HTTP %d from %s: %s", e.code, url, e.reason)
    except urllib.error.URLError as e:
        logger.warning("URL error %s: %s", url, e.reason)
    except Exception as e:
        logger.warning("Request failed (%s): %s", url, e)
    return None


class TokenAPICollector(BaseCollector):
    name = "tokens_api"

    def __init__(self, conn):
        super().__init__(conn)
        self._last: dict[str, dict] = {}

    def collect(self) -> dict:
        results = {}

        if config.ANTHROPIC_API_KEY:
            results["anthropic"] = self._collect_anthropic()
        else:
            logger.debug("No Anthropic key configured — skipping API poll")

        if config.OPENAI_API_KEY:
            results["openai"] = self._collect_openai()
        else:
            logger.debug("No OpenAI key configured — skipping API poll")

        self._check_spend_alerts()
        return results

    def _collect_anthropic(self) -> dict:
        """
        Anthropic Usage API:
        GET /v1/usage  (requires Admin API key — sk-ant-admin...)
        Returns cumulative input_tokens + output_tokens for billing period.
        """
        data = _http_get(
            "https://api.anthropic.com/v1/usage",
            {
                "x-api-key": config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            }
        )
        if not data:
            return {"error": "no response"}

        total_in  = data.get("input_tokens", 0)
        total_out = data.get("output_tokens", 0)
        last = self._last.get("anthropic", {"in": 0, "out": 0})

        delta_in  = max(0, total_in  - last["in"])
        delta_out = max(0, total_out - last["out"])
        self._last["anthropic"] = {"in": total_in, "out": total_out}

        if delta_in == 0 and delta_out == 0:
            return {"skipped": "no new usage"}

        price = config.get_price("anthropic", "default")
        cost = (delta_in / 1000 * price["in"] + delta_out / 1000 * price["out"])

        write_token_usage(
            self.conn,
            provider="anthropic", app="api", model="",
            tokens_in=delta_in, tokens_out=delta_out, cost_usd=cost,
        )
        logger.info("Anthropic +%d in +%d out  $%.5f", delta_in, delta_out, cost)
        return {"tokens_in": delta_in, "tokens_out": delta_out, "cost_usd": cost}

    def _collect_openai(self) -> dict:
        """
        OpenAI Usage API:
        GET /v1/organization/usage/completions
        Returns bucketed usage; we sum today's buckets and delta against last poll.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Convert to unix timestamps for the API
        start_ts = int(datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp())

        data = _http_get(
            f"https://api.openai.com/v1/organization/usage/completions"
            f"?start_time={start_ts}",
            {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
        )
        if not data:
            return {"error": "no response"}

        total_in = total_out = 0
        for bucket in data.get("data", []):
            for result in bucket.get("results", []):
                total_in  += result.get("input_tokens", 0)
                total_out += result.get("output_tokens", 0)

        last = self._last.get("openai", {"in": 0, "out": 0, "date": today})
        # Reset delta tracking at day boundary
        if last.get("date") != today:
            last = {"in": 0, "out": 0, "date": today}

        delta_in  = max(0, total_in  - last["in"])
        delta_out = max(0, total_out - last["out"])
        self._last["openai"] = {"in": total_in, "out": total_out, "date": today}

        if delta_in == 0 and delta_out == 0:
            return {"skipped": "no new usage"}

        price = config.get_price("openai", "gpt-4o")
        cost = (delta_in / 1000 * price["in"] + delta_out / 1000 * price["out"])

        write_token_usage(
            self.conn,
            provider="openai", app="api", model="",
            tokens_in=delta_in, tokens_out=delta_out, cost_usd=cost,
        )
        logger.info("OpenAI +%d in +%d out  $%.5f", delta_in, delta_out, cost)
        return {"tokens_in": delta_in, "tokens_out": delta_out, "cost_usd": cost}

    def _check_spend_alerts(self) -> None:
        """Fire alerts if daily or monthly spend thresholds are crossed."""
        daily   = token_spend(self.conn, days=1)
        monthly = token_spend(self.conn, days=30)

        if daily["cost_usd"] >= config.ALERT_DAILY_SPEND:
            write_alert(
                self.conn, "spend_daily", daily["cost_usd"],
                f"Daily AI spend ${daily['cost_usd']:.2f} exceeded "
                f"limit ${config.ALERT_DAILY_SPEND:.2f}"
            )

        if monthly["cost_usd"] >= config.ALERT_MONTHLY_SPEND:
            write_alert(
                self.conn, "spend_monthly", monthly["cost_usd"],
                f"Monthly AI spend ${monthly['cost_usd']:.2f} exceeded "
                f"limit ${config.ALERT_MONTHLY_SPEND:.2f}"
            )
