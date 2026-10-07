"""On-disk LLM response cache. Makes reruns free and lets an interrupted run resume."""

import hashlib
import json
import time
from pathlib import Path

from app import llm
from app.config import settings

CACHE_DIR = Path(__file__).parent / "cache"


def _key(system: str, user: str) -> str:
    parts = [settings.llm_provider, settings.llm_model, settings.llm_thinking_budget]
    if settings.llm_thinking_level:  # only when set, so entries cached before this setting existed stay valid
        parts.append(settings.llm_thinking_level)
    return hashlib.sha256(json.dumps(parts + [system, user]).encode()).hexdigest()


async def cached_complete(system: str, user: str) -> dict:
    """Returns {text, input_tokens, output_tokens, latency_ms, cached}. Latency is the original call's."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{_key(system, user)}.json"
    if path.exists():
        return {**json.loads(path.read_text()), "cached": True}
    start = time.monotonic()
    c = await llm.complete_with_usage(system, user)
    entry = {"text": c.text, "input_tokens": c.input_tokens, "output_tokens": c.output_tokens,
             "latency_ms": int((time.monotonic() - start) * 1000)}
    if c.text.strip():  # never cache an empty (failed/truncated) answer
        path.write_text(json.dumps(entry))
    return {**entry, "cached": False}
