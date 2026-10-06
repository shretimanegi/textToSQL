"""Embeddings: local fastembed model by default (free, no quota); Gemini optional."""

import asyncio
import hashlib
import json
import random
from pathlib import Path

import httpx

from app.config import settings

BATCH = 50
_RETRY_STATUS = {429, 500, 502, 503, 504}
# The eval harness points this at a directory so repeated runs never re-embed the same text.
CACHE_DIR: Path | None = None


def _cache_path(text: str, task: str) -> Path | None:
    if CACHE_DIR is None:
        return None
    key = hashlib.sha256(json.dumps([settings.embedding_model, settings.embedding_dim, task, text]).encode()).hexdigest()
    return CACHE_DIR / f"emb_{key}.json"


async def _post(client: httpx.AsyncClient, url: str, body: dict) -> dict:
    for attempt in range(7):
        try:
            resp = await client.post(url, json=body, headers={"x-goog-api-key": settings.gemini_api_key})
        except httpx.TransportError:
            resp = None
        if resp is not None and resp.status_code == 200:
            return resp.json()
        if resp is not None and resp.status_code not in _RETRY_STATUS:
            raise RuntimeError(f"Gemini embeddings {resp.status_code}: {resp.text[:300]}")
        if resp is not None and resp.status_code == 429 and "retry in" in resp.text and "h" in resp.text.split("retry in")[1][:12]:
            raise RuntimeError(f"Gemini embedding quota exhausted: {resp.text[:200]}")
        await asyncio.sleep(min(60, 2**attempt) + random.random())
    raise RuntimeError("Gemini embeddings failed after retries")


_local_model = None


def _embed_local_sync(texts: list[str]) -> list[list[float]]:
    global _local_model
    if _local_model is None:
        from fastembed import TextEmbedding

        _local_model = TextEmbedding(settings.embedding_model)
    return [v.tolist() for v in _local_model.embed(texts, batch_size=128)]


async def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """task: RETRIEVAL_DOCUMENT for stored text, RETRIEVAL_QUERY for the user's question (Gemini only;
    the local bge model embeds both sides identically)."""
    if settings.embedding_provider == "local":
        return await asyncio.to_thread(_embed_local_sync, texts)
    return await _embed_gemini(texts, task)


async def _embed_gemini(texts: list[str], task: str) -> list[list[float]]:
    out: list[list[float] | None] = [None] * len(texts)
    todo: list[int] = []
    for i, t in enumerate(texts):
        p = _cache_path(t, task)
        if p is not None and p.exists():
            out[i] = json.loads(p.read_text())
        else:
            todo.append(i)

    model = f"models/{settings.embedding_model}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:batchEmbedContents"
    async with httpx.AsyncClient(timeout=90) as client:
        for start in range(0, len(todo), BATCH):
            idx = todo[start:start + BATCH]
            body = {"requests": [{
                "model": model, "taskType": task, "outputDimensionality": settings.embedding_dim,
                "content": {"parts": [{"text": texts[i]}]}} for i in idx]}
            data = await _post(client, url, body)
            for i, e in zip(idx, data["embeddings"]):
                out[i] = e["values"]
                p = _cache_path(texts[i], task)
                if p is not None:
                    CACHE_DIR.mkdir(exist_ok=True)
                    p.write_text(json.dumps(e["values"]))
    return out  # type: ignore[return-value]


def to_pgvector(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"
