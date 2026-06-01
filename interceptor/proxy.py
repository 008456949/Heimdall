"""
interceptor/proxy.py — the heart of Heimdall.

A mitmproxy addon that intercepts every AI API call on this machine,
parses token usage from the response, and writes it to SQLite.

Run with:
    mitmdump --mode local --quiet -s interceptor/proxy.py

The addon fires response() for every intercepted flow.
We filter to known AI hosts, parse the response body,
and write one token_usage row per API call.
"""

import json
import logging
import sys
from pathlib import Path

# Add project root to path when run as a mitmproxy addon
sys.path.insert(0, str(Path(__file__).parent.parent))

from mitmproxy import http
from mitmproxy.net.http import encoding as http_encoding

from heimdall import config
from heimdall.db.database import get_connection, init_schema, write_token_usage
from interceptor.parsers import anthropic, openai, ollama
from interceptor.git_context import get_git_context

logger = logging.getLogger("heimdall.proxy")


class HeimdallInterceptor:
    """
    mitmproxy addon class. mitmproxy discovers it via the `addons` list below.
    """

    def __init__(self):
        self.conn = get_connection(config.DB_PATH)
        init_schema(self.conn)
        logger.info("Heimdall interceptor online — watching %s", config.AI_HOSTS)

    def response(self, flow: http.HTTPFlow) -> None:
        """Called by mitmproxy for every completed HTTP(S) response."""
        host = flow.request.pretty_host

        # Only care about AI endpoints
        if not any(h in host for h in config.AI_HOSTS):
            return

        path    = flow.request.path
        body    = self._decode_body(flow.response)
        app     = self._detect_app(flow)
        repo, branch = get_git_context()

        parsed = None

        if "anthropic.com" in host:
            parsed = anthropic.parse(path, body, flow.response.headers)

        elif "openai.com" in host:
            parsed = openai.parse(path, body)

        elif host in ("localhost", "127.0.0.1") and "11434" in str(flow.request.port or ""):
            parsed = ollama.parse(path, body)

        if not parsed:
            return

        price = config.get_price(parsed["provider"], parsed.get("model", ""))
        cost  = (
            parsed["tokens_in"]  / 1000 * price["in"] +
            parsed["tokens_out"] / 1000 * price["out"]
        )

        write_token_usage(
            self.conn,
            provider   = parsed["provider"],
            app        = app,
            model      = parsed.get("model", ""),
            git_repo   = repo,
            git_branch = branch,
            tokens_in  = parsed["tokens_in"],
            tokens_out = parsed["tokens_out"],
            cost_usd   = cost,
        )

        logger.info(
            "[%s/%s] %s  in=%d out=%d  $%.5f  (%s@%s)",
            parsed["provider"], app, parsed.get("model", "?"),
            parsed["tokens_in"], parsed["tokens_out"], cost,
            repo or "?", branch or "?",
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _decode_body(response: http.Response) -> str:
        """Decode response body, handling gzip/br/deflate transparently."""
        try:
            content = response.get_content(strict=False)
            return content.decode("utf-8", errors="replace") if content else ""
        except Exception:
            return ""

    @staticmethod
    def _detect_app(flow: http.HTTPFlow) -> str:
        """
        Infer which application made the request.
        mitmproxy local mode exposes flow.process in newer versions.
        Falls back to User-Agent header heuristics.
        """
        # flow.process is available in mitmproxy >= 10.1 local mode
        proc = getattr(flow, "process", None)
        if proc and proc.name:
            name = proc.name.lower()
            if "cursor" in name:   return "cursor"
            if "claude" in name:   return "claude_desktop"
            if "code" in name:     return "vscode"
            if "python" in name:   return "python"
            if "node" in name:     return "node"
            return proc.name

        ua = flow.request.headers.get("user-agent", "").lower()
        if "cursor"       in ua: return "cursor"
        if "claude"       in ua: return "claude_desktop"
        if "python"       in ua: return "python"
        if "node"         in ua: return "node"
        if "openai-node"  in ua: return "openai_sdk_node"
        if "openai-python" in ua: return "openai_sdk_python"
        return "unknown"


# mitmproxy discovers addons via this module-level list
addons = [HeimdallInterceptor()]
