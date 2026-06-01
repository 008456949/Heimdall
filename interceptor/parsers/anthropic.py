"""
interceptor/parsers/anthropic.py — parse Anthropic API responses.

Handles both streaming (SSE) and non-streaming JSON responses.
The usage block lives in different places depending on the response type.
"""

import json
import re


def parse(path: str, body: str, headers: dict) -> dict | None:
    """
    Returns {"provider", "model", "tokens_in", "tokens_out"} or None.
    Only parses /v1/messages — ignores other endpoints.
    """
    if not path.startswith("/v1/messages"):
        return None

    content_type = headers.get("content-type", "")

    if "text/event-stream" in content_type:
        return _parse_streaming(body)
    else:
        return _parse_json(body)


def _parse_json(body: str) -> dict | None:
    """Non-streaming: usage is top-level in the response JSON."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None

    usage = data.get("usage", {})
    tokens_in  = usage.get("input_tokens", 0)
    tokens_out = usage.get("output_tokens", 0)

    if tokens_in == 0 and tokens_out == 0:
        return None

    return {
        "provider":   "anthropic",
        "model":      data.get("model", ""),
        "tokens_in":  tokens_in,
        "tokens_out": tokens_out,
    }


def _parse_streaming(body: str) -> dict | None:
    """
    Streaming: usage arrives in the final message_delta event.
    event: message_delta
    data: {"type":"message_delta","delta":{...},"usage":{"output_tokens":N}}

    And input tokens in message_start:
    event: message_start
    data: {"type":"message_start","message":{"usage":{"input_tokens":N,...}}}
    """
    tokens_in = tokens_out = 0
    model = ""

    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw in ("[DONE]", ""):
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")

        if etype == "message_start":
            msg   = event.get("message", {})
            model = msg.get("model", model)
            usage = msg.get("usage", {})
            tokens_in = usage.get("input_tokens", tokens_in)

        elif etype == "message_delta":
            usage = event.get("usage", {})
            tokens_out = usage.get("output_tokens", tokens_out)

    if tokens_in == 0 and tokens_out == 0:
        return None

    return {
        "provider":   "anthropic",
        "model":      model,
        "tokens_in":  tokens_in,
        "tokens_out": tokens_out,
    }
