"""The adapter contract: what a model call *is*, before anyone makes one.

Milestone 10. Every LLM adapter in this package speaks the same three types — a
:class:`LLMRequest` in, a :class:`LLMResponse` out, and a :class:`TokenUsage`
saying what it consumed. Nothing here talks to a network, and nothing in this
package's dependency set could: ``pyproject.toml`` declares no HTTP client, and
``tests/test_adapters.py`` asserts that no module under ``adapters/`` imports one.

Three properties are enforced by the types rather than by convention.

**A request is identified by its content, not by when it was made.**
:meth:`LLMRequest.fingerprint` is the SHA-256 of the canonical JSON of the five
fields that determine a response — model, system, prompt, temperature, max_tokens.
It is the cache key, the recording key, and the trace's handle on the call. Two
requests that differ in any of the five are different requests, including a
``temperature`` change: a cached sample from a stochastic decode is one draw, not
a distribution, and pretending a fingerprint could span both would quietly make a
replay unfaithful.

**A dry-run response cannot carry content or a cost.** ``dry_run=True`` with a
non-empty ``text`` or a non-zero ``cost_usd`` raises at construction. The whole
point of a dry run is to price a call without making it, so a dry-run response
that carried model output would mean the call *was* made, and a caller downstream
could not tell. See :class:`~scientific_claim_verifier.adapters.api_stub.ApiAdapterStub`.

**A cached response cannot carry a cost.** A cache hit spends nothing. The field
records *money this call actually spent*, so a hit records ``0.0`` — not the price
the response cost when it was first fetched. Estimated and actual money never share
a field: ``estimated_usd`` is populated only on a dry run, ``cost_usd`` only by a
call that really happened. That separation is the same discipline the report applies
to the extracted claim, the computed check, and the inference.

The two model names below are **fictitious on purpose**. ``mock-llm-v1`` and
``recorded-fixture-v1`` never leave this process, and naming a real vendor model in
a committed fixture would imply that a real vendor model produced it. None did; see
``data/fixtures/llm/README.md``.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

#: Default completion cap. Bounds the *worst case* a cost guard must reserve for,
#: so it is a budget parameter as much as a generation parameter.
DEFAULT_MAX_TOKENS = 512

#: Default decoding temperature. Zero, because a reproducible extraction is the
#: only kind this project has any use for.
DEFAULT_TEMPERATURE = 0.0

#: The in-process model served by
#: :class:`~scientific_claim_verifier.adapters.mock_llm.MockLLMAdapter`.
MOCK_MODEL = "mock-llm-v1"

#: The in-process model served by
#: :class:`~scientific_claim_verifier.adapters.recorded_llm.RecordedLLMAdapter`. Fictitious:
#: the committed recordings are hand-authored, and no API produced them.
RECORDED_MODEL = "recorded-fixture-v1"

#: Fields of a request that determine its response, and therefore its fingerprint.
FINGERPRINTED_FIELDS = ("max_tokens", "model", "prompt", "system", "temperature")


class AdapterError(RuntimeError):
    """Base class for every failure raised by this package."""


@dataclass(frozen=True)
class TokenUsage:
    """Tokens consumed by one call. Non-negative; ``0/0`` means "not reported"."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __post_init__(self) -> None:
        if self.prompt_tokens < 0 or self.completion_tokens < 0:
            raise ValueError(
                f"token counts must be non-negative, got "
                f"prompt={self.prompt_tokens} completion={self.completion_tokens}"
            )

    @property
    def total_tokens(self) -> int:
        """Prompt plus completion."""
        return self.prompt_tokens + self.completion_tokens

    def describe(self) -> dict[str, int]:
        """A JSON-safe snapshot for a trace or a report."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class LLMRequest:
    """One model call, fully described by its content.

    Immutable and hashable, so it can be a dict key and cannot be mutated between
    the moment a cost guard prices it and the moment an adapter sends it.
    """

    model: str
    prompt: str
    system: str = ""
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("request.model must be a non-empty string")
        if not self.prompt:
            raise ValueError("request.prompt must be a non-empty string")
        if self.max_tokens <= 0:
            raise ValueError(f"request.max_tokens must be positive, got {self.max_tokens}")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(f"request.temperature must lie in [0, 2], got {self.temperature}")

    def payload(self) -> dict[str, Any]:
        """The canonical view that :meth:`fingerprint` hashes."""
        return {name: getattr(self, name) for name in FINGERPRINTED_FIELDS}

    def fingerprint(self) -> str:
        """SHA-256 over the canonical payload. Stable across runs and machines.

        Keys are sorted and ``ensure_ascii`` is off, so the digest depends on the
        request's meaning and not on dict insertion order or an escaping choice.
        """
        canonical = json.dumps(self.payload(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def describe(self) -> dict[str, Any]:
        """A JSON-safe snapshot: the payload plus its fingerprint."""
        return {**self.payload(), "fingerprint": self.fingerprint()}


@dataclass(frozen=True)
class LLMResponse:
    """What an adapter returns. Estimated and actual money never share a field.

    ``cost_usd`` is money this call *actually* spent — ``0.0`` for a cache hit, a
    replay, a mock, and a dry run. ``estimated_usd`` is populated **only** on a dry
    run, and says what a live call would have cost. The invariants below are
    enforced here so no adapter can violate them by accident.
    """

    text: str
    model: str
    adapter: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    cached: bool = False
    dry_run: bool = False
    cost_usd: float = 0.0
    estimated_usd: float | None = None
    finish_reason: str = "stop"

    def __post_init__(self) -> None:
        if self.cost_usd < 0:
            raise ValueError(f"cost_usd must be non-negative, got {self.cost_usd}")
        if self.dry_run:
            if self.text:
                raise ValueError("a dry-run response must not carry model content")
            if self.cost_usd:
                raise ValueError("a dry-run response must not carry a cost; it spent nothing")
        else:
            if self.estimated_usd is not None:
                raise ValueError("estimated_usd is meaningful only on a dry-run response")
            if self.cached and self.cost_usd:
                raise ValueError("a cached response must not carry a cost; a cache hit is free")

    def describe(self) -> dict[str, Any]:
        """A JSON-safe snapshot for a trace, a report, or an audit trail."""
        return {
            "adapter": self.adapter,
            "model": self.model,
            "cached": self.cached,
            "dry_run": self.dry_run,
            "cost_usd": self.cost_usd,
            "estimated_usd": self.estimated_usd,
            "finish_reason": self.finish_reason,
            "usage": self.usage.describe(),
        }


class LLMAdapter(ABC):
    """The interface every adapter implements.

    ``spends_money`` is a class-level declaration, not a runtime observation: it is
    what lets a test enumerate the registry and assert that exactly one adapter is
    even *capable* of a paid call, and that it is disabled.
    """

    #: Short registry name (``"mock"``, ``"recorded"``, ``"api"``).
    name: ClassVar[str] = "adapter"

    #: Whether this adapter can, under any configuration, cause a paid API call.
    spends_money: ClassVar[bool] = False

    @property
    @abstractmethod
    def default_model(self) -> str:
        """The model name this adapter serves when a caller names none."""

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Answer ``request``. Raises an :class:`AdapterError` subclass on refusal."""

    def describe(self) -> dict[str, Any]:
        """A JSON-safe snapshot of this adapter's configuration and posture."""
        return {
            "adapter": self.name,
            "default_model": self.default_model,
            "spends_money": self.spends_money,
        }


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TEMPERATURE",
    "FINGERPRINTED_FIELDS",
    "MOCK_MODEL",
    "RECORDED_MODEL",
    "AdapterError",
    "LLMAdapter",
    "LLMRequest",
    "LLMResponse",
    "TokenUsage",
]
