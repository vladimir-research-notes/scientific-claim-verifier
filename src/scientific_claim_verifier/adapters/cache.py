"""The response cache: pay for a given request at most once.

``CLAUDE.md`` requires a **response cache** in any paid-API mode. A cache is a cost
control before it is a speed control, so its correctness conditions are about money:

**A hit must be free, and must say so.** :meth:`ResponseCache.get` returns the stored
response with ``cached=True`` and ``cost_usd=0.0``, never the price the response cost
when it was first fetched. Re-reporting the original cost would double-count spend in
any caller that sums ``cost_usd`` — the guard's ``spent_usd`` is the ledger, and a hit
never touches it.

**A hit must be the same request.** The key is
:meth:`~scientific_claim_verifier.adapters.base.LLMRequest.fingerprint`, over model,
system, prompt, temperature, and max_tokens. The stored file repeats the fingerprint in
its body, and :meth:`get` re-derives it: a file that has been renamed, hand-edited, or
truncated is treated as a **miss**, not as an answer to a question nobody asked.

**A dry run must not populate the cache.** :meth:`put` refuses a ``dry_run`` response,
which carries no content by construction. Caching one would poison every later lookup
with an empty string that looks like a model answer.

Nothing here is on by default. ``directory=None`` gives an in-memory cache that dies
with the process; a directory adds a JSON file per entry under ``results/cache/``,
which ``.gitignore`` excludes — a cached paid-API response is exactly the kind of
artifact ``CLAUDE.md`` says must never be committed. Recorded *fixtures*, which are
hand-authored and free, live under ``data/fixtures/llm/`` and are committed; see
:mod:`~scientific_claim_verifier.adapters.recorded_llm`.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .base import LLMRequest, LLMResponse, TokenUsage

#: Where a disk-backed cache lives when a caller names no directory. Under
#: ``results/``, which ``.gitignore`` excludes.
DEFAULT_CACHE_DIR = Path("results/cache/llm")

#: Written into each entry so a future reader can tell what it is looking at.
CACHE_FORMAT = "scv-llm-cache-v1"


class ResponseCache:
    """Fingerprint-keyed response store: in memory, and optionally on disk."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else None
        self._memory: dict[str, LLMResponse] = {}

    # -- paths ---------------------------------------------------------------

    def path_for(self, fingerprint: str) -> Path | None:
        """The file backing ``fingerprint``, or ``None`` for a memory-only cache."""
        if self.directory is None:
            return None
        return self.directory / f"{fingerprint}.json"

    # -- reading -------------------------------------------------------------

    def get(self, request: LLMRequest) -> LLMResponse | None:
        """Return the stored response for ``request``, marked free and cached.

        A malformed, truncated, or fingerprint-mismatched file is a **miss**. The
        cache never raises on a corrupt entry: the correct recovery is to fetch the
        response again, not to fail a run.
        """
        fingerprint = request.fingerprint()
        hit = self._memory.get(fingerprint)
        if hit is None:
            hit = self._read_disk(fingerprint)
        if hit is None:
            return None
        return replace(hit, cached=True, cost_usd=0.0, estimated_usd=None)

    def _read_disk(self, fingerprint: str) -> LLMResponse | None:
        path = self.path_for(fingerprint)
        if path is None or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("fingerprint") != fingerprint:
                return None  # renamed or hand-edited: not an answer to this request
            stored = payload["response"]
            response = LLMResponse(
                text=stored["text"],
                model=stored["model"],
                adapter=stored["adapter"],
                usage=TokenUsage(
                    prompt_tokens=stored["usage"]["prompt_tokens"],
                    completion_tokens=stored["usage"]["completion_tokens"],
                ),
                finish_reason=stored.get("finish_reason", "stop"),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        self._memory[fingerprint] = response
        return response

    # -- writing -------------------------------------------------------------

    def put(self, request: LLMRequest, response: LLMResponse) -> None:
        """Store ``response`` under ``request``'s fingerprint.

        Refuses a dry-run response (it has no content to store). The entry records the
        response's content and usage but **not** its cost: what a call cost is a fact
        about that call, not about the answer.
        """
        if response.dry_run:
            raise ValueError("refusing to cache a dry-run response: it carries no content")
        fingerprint = request.fingerprint()
        self._memory[fingerprint] = replace(response, cached=False, cost_usd=0.0)
        self._write_disk(fingerprint, request, response)

    def _write_disk(self, fingerprint: str, request: LLMRequest, response: LLMResponse) -> None:
        path = self.path_for(fingerprint)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": CACHE_FORMAT,
            "fingerprint": fingerprint,
            "request": request.payload(),
            "response": {
                "text": response.text,
                "model": response.model,
                "adapter": response.adapter,
                "finish_reason": response.finish_reason,
                "usage": response.usage.describe(),
            },
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # -- inspection ----------------------------------------------------------

    def clear(self) -> None:
        """Drop every in-memory entry. Files on disk are left alone."""
        self._memory.clear()

    def __len__(self) -> int:
        """Number of entries held in memory (not counting unread files on disk)."""
        return len(self._memory)

    def describe(self) -> dict[str, object]:
        """A JSON-safe snapshot for the trace and the ``adapters`` command."""
        return {
            "backend": "memory" if self.directory is None else "memory+disk",
            "directory": str(self.directory) if self.directory else None,
            "entries_in_memory": len(self._memory),
            "policy": "a hit is free and reports cost_usd=0.0; dry runs are never cached",
        }


__all__ = ["CACHE_FORMAT", "DEFAULT_CACHE_DIR", "ResponseCache"]
