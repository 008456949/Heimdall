"""
interceptor/parsers/openai.py — parse OpenAI API responses.
"""

import json


def parse(path: str, body: str) -> dict | None:
    if not path.startswith("/v1/chat/completions"):
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # Streaming responses — find the last data: line with usage
        return _parse_streaming(body)

    usage = data.get("usage", {})
    tokens_in  = usage.get("prompt_tokens", 0)
    tokens_out = usage.get("completion_tokens", 0)

    if tokens_in == 0 and tokens_out == 0:
        return None

    return {
        "provider":   "openai",
        "model":      data.get("model", ""),
        "tokens_in":  tokens_in,
        "tokens_out": tokens_out,
    }


def _parse_streaming(body: str) -> dict | None:
    """OpenAI streaming: usage appears in the final [DONE] chunk."""
    tokens_in = tokens_out = 0
    model = ""

    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            continue
        try:
            chunk = json.loads(raw)
        except json.JSONDecodeError:
            continue

        model = chunk.get("model", model)
        usage = chunk.get("usage") or {}
        if usage:
            tokens_in  = usage.get("prompt_tokens", tokens_in)
            tokens_out = usage.get("completion_tokens", tokens_out)

    if tokens_in == 0 and tokens_out == 0:
        return None

    return {
        "provider":   "openai",
        "model":      model,
        "tokens_in":  tokens_in,
        "tokens_out": tokens_out,
    }
