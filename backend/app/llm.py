"""Provider-agnostic text completion (Gemini, Claude or GPT, chosen by LLM_PROVIDER)."""

import asyncio
import random
import re
from dataclasses import dataclass

import httpx

from app.config import settings


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 7


def _retry_delay_s(body: str) -> float:
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", body)
    if not m:
        return 0.0
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3))


def thinking_config() -> dict | None:
    """Gemini 2.5 takes a token budget, Gemini 3.x takes a level and rejects the budget."""
    if settings.llm_thinking_level:
        return {"thinkingLevel": settings.llm_thinking_level}
    if settings.llm_thinking_budget >= 0:
        return {"thinkingBudget": settings.llm_thinking_budget}
    return None


async def _gemini(system: str, user: str, max_tokens: int) -> Completion:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.llm_model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0},
    }
    if (tc := thinking_config()) is not None:
        body["generationConfig"]["thinkingConfig"] = tc
    async with httpx.AsyncClient(timeout=90) as client:
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await client.post(url, json=body, headers={"x-goog-api-key": settings.gemini_api_key})
            except httpx.TransportError:
                resp = None
            if resp is not None and resp.status_code == 200:
                break
            if resp is not None and resp.status_code not in _RETRY_STATUS:
                raise RuntimeError(f"Gemini API {resp.status_code}: {resp.text[:300]}")
            if resp is not None and resp.status_code == 429 and _retry_delay_s(resp.text) > 120:
                # Daily quota exhausted: retrying within this process cannot help.
                raise RuntimeError(f"Gemini quota exhausted (retry in {_retry_delay_s(resp.text):.0f}s): {resp.text[:200]}")
            if attempt == _MAX_ATTEMPTS - 1:
                detail = f"{resp.status_code}: {resp.text[:200]}" if resp is not None else "network error"
                raise RuntimeError(f"Gemini API failed after {_MAX_ATTEMPTS} attempts ({detail})")
            await asyncio.sleep(min(60, 2**attempt) + random.random())  # free-tier rate limits
    data = resp.json()
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    usage = data.get("usageMetadata", {})
    return Completion(
        "".join(p.get("text", "") for p in parts),
        usage.get("promptTokenCount", 0),
        usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
    )


async def complete_with_usage(system: str, user: str, max_tokens: int = 2048) -> Completion:
    if settings.llm_provider == "mock":
        from app.llm_mock import mock_complete

        return Completion(mock_complete(system, user))

    if settings.llm_provider == "gemini":
        return await _gemini(system, user, max_tokens)

    if settings.llm_provider == "anthropic":
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return Completion("".join(b.text for b in msg.content if b.type == "text"),
                          msg.usage.input_tokens, msg.usage.output_tokens)

    if settings.llm_provider == "openai":
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        u = resp.usage
        return Completion(resp.choices[0].message.content or "",
                          u.prompt_tokens if u else 0, u.completion_tokens if u else 0)

    raise ValueError(f"unknown LLM_PROVIDER: {settings.llm_provider}")


async def complete(system: str, user: str, max_tokens: int = 2048) -> str:
    return (await complete_with_usage(system, user, max_tokens)).text
