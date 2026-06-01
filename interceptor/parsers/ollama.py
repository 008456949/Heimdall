"""
interceptor/parsers/ollama.py — parse Ollama API responses.

Ollama streams NDJSON. The final line (done=true) contains
prompt_eval_count (input tokens) and eval_count (output tokens).
"""

import json


def parse(path: str, body: str) -> dict | None:
    if path not in ("/api/generate", "/api/chat"):
        return None

    tokens_in = tokens_out = 0
    model = ""

    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue

        model = chunk.get("model", model)

        if chunk.get("done"):
            tokens_in  = chunk.get("prompt_eval_count", 0)
            tokens_out = chunk.get("eval_count", 0)
            break

    if tokens_in == 0 and tokens_out == 0:
        return None

    return {
        "provider":   "ollama",
        "model":      model,
        "tokens_in":  tokens_in,
        "tokens_out": tokens_out,
    }
