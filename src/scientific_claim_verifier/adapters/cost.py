"""Token estimation, model prices, and the hard cost guard.

``CLAUDE.md`` requires that any paid-API mode carry a **token/cost estimator** and a
**hard max-cost guard**. This module is both. Three decisions define it.

**We ship no vendor price list, and that is the feature.**
:data:`_PRICES` starts with exactly two entries, both zero: the two in-process models
that never leave this interpreter. No real model has a price here, and
:func:`price_for` *raises* on a model it does not know. A stale price in a cost guard
is strictly worse than no price, because it looks authoritative while silently
under-reserving; and any number committed here would begin going stale the day it was
written. A caller who wants to spend money must therefore say what the money costs:

    register_price("some-vendor-model", ModelPrice(0.003, 0.015))

Until they do, :meth:`CostGuard.reserve` cannot price the call, so the call cannot
happen. An unpriced model is an uncallable model.

**The estimator over-counts on purpose, because a guard that under-counts is not a
guard.** :func:`estimate_tokens` is *not* a tokenizer. It divides characters by
:data:`CHARS_PER_TOKEN` = 3 and adds per-message framing overhead. Real byte-pair
encoders average closer to 4 characters per token on English prose, so this returns an
**upper bound** for prose and stays close to the truth on the JSON and code that
dominate this project's prompts. The bound is what matters: the guard reserves against
the estimate *before* the request is sent, and an estimate that could fall below the
true prompt size would let a call through that the budget does not cover. Vendoring a
real tokenizer would buy accuracy the guard has no use for, at the price of a
model-specific dependency this repo does not want. This is a heuristic, and it is
labelled as one.

**Reserve before the call; settle after it.** :meth:`CostGuard.reserve` prices the
*worst case* — the estimated prompt plus a completion that runs all the way to
``max_tokens`` — and refuses if that exceeds the remaining budget. Only then may an
adapter send anything. :meth:`CostGuard.settle` then records what the call really
consumed. The asymmetry is deliberate and the honest limitation is this: **the guard
bounds the next call, it cannot refund the last one.** If a vendor's true prompt
tokenization ever exceeded our upper bound, ``settle`` would faithfully record the
overspend and the *following* ``reserve`` would refuse. Nothing can un-spend money that
has already been spent, and this module does not pretend otherwise.

The default budget is ``$0.00`` (:data:`DEFAULT_MAX_USD`), so a guard nobody
configured refuses every call that costs anything at all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .base import MOCK_MODEL, RECORDED_MODEL, AdapterError, LLMRequest, TokenUsage

#: Characters per token. Deliberately below the ~4 that English prose averages under a
#: real BPE tokenizer, so :func:`estimate_tokens` returns an upper bound rather than a
#: mean. See the module docstring.
CHARS_PER_TOKEN = 3.0

#: Tokens a provider adds per message for role/framing, which the caller never sees.
#: Added once per message (system and prompt are separate messages).
MESSAGE_TOKEN_OVERHEAD = 8

#: A guard nobody configured has no budget, so it refuses every non-free call.
DEFAULT_MAX_USD = 0.0

#: Slack for float arithmetic on money, in USD. Applied in the *permissive* direction
#: in :meth:`CostGuard.reserve`, so the guard can be over-permissive by at most one
#: nanodollar — an error smaller than any price this table could hold.
EPSILON = 1e-9


class UnknownModelPrice(AdapterError):
    """Raised when a model has no registered price, so a call cannot be costed."""


class CostLimitExceeded(AdapterError):
    """Raised *before* a request is sent, when its worst case exceeds the budget."""


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1,000 prompt tokens and per 1,000 completion tokens."""

    prompt_usd_per_1k: float
    completion_usd_per_1k: float

    def __post_init__(self) -> None:
        if self.prompt_usd_per_1k < 0 or self.completion_usd_per_1k < 0:
            raise ValueError("prices must be non-negative")

    def cost(self, usage: TokenUsage) -> float:
        """The USD cost of ``usage`` at this price."""
        return (
            usage.prompt_tokens * self.prompt_usd_per_1k
            + usage.completion_tokens * self.completion_usd_per_1k
        ) / 1000.0

    def describe(self) -> dict[str, float]:
        """A JSON-safe snapshot."""
        return {
            "prompt_usd_per_1k": self.prompt_usd_per_1k,
            "completion_usd_per_1k": self.completion_usd_per_1k,
        }


#: The price of a model that never leaves this process.
FREE = ModelPrice(0.0, 0.0)

# The whole price table. Two in-process models, both free. No vendor model appears
# here, and none should be added: a caller who wants one registers it at runtime.
_PRICES: dict[str, ModelPrice] = {
    MOCK_MODEL: FREE,
    RECORDED_MODEL: FREE,
}


def register_price(model: str, price: ModelPrice) -> None:
    """Declare what ``model`` costs, making it callable by a guarded adapter.

    This is the explicit act by which a caller takes responsibility for a price. It
    is never done for them, and nothing in the default path calls it.
    """
    if not model:
        raise ValueError("model must be a non-empty string")
    _PRICES[model] = price


def unregister_price(model: str) -> None:
    """Revoke ``model``'s price, making it uncallable again. Absent models are ignored."""
    _PRICES.pop(model, None)


def price_for(model: str) -> ModelPrice:
    """Return ``model``'s registered price, or raise :class:`UnknownModelPrice`.

    Raising is the safety property: a model whose cost is unknown cannot be
    reserved for, and therefore cannot be called.
    """
    try:
        return _PRICES[model]
    except KeyError:
        known = ", ".join(sorted(_PRICES)) or "(none)"
        raise UnknownModelPrice(
            f"no registered price for model {model!r}; this repository ships no vendor "
            f"price list on purpose (a stale price is worse than none). Known models: "
            f"{known}. Register one explicitly with "
            f"adapters.cost.register_price({model!r}, ModelPrice(prompt, completion))."
        ) from None


def price_table() -> dict[str, ModelPrice]:
    """A copy of the current price table, for display and for the trace."""
    return dict(_PRICES)


def estimate_tokens(text: str) -> int:
    """Upper-bound the tokens in one message. **A heuristic, not a tokenizer.**

    ``ceil(len(text) / CHARS_PER_TOKEN) + MESSAGE_TOKEN_OVERHEAD``. Monotonic
    non-decreasing in ``len(text)``, deterministic, and dependency-free. The empty
    string still costs the framing overhead, because an empty message is still a
    message.
    """
    return math.ceil(len(text) / CHARS_PER_TOKEN) + MESSAGE_TOKEN_OVERHEAD


def estimate_request_tokens(request: LLMRequest) -> int:
    """Upper-bound the prompt tokens of ``request`` — its system and user messages."""
    return estimate_tokens(request.system) + estimate_tokens(request.prompt)


@dataclass(frozen=True)
class CostEstimate:
    """The worst case for one request: full prompt, completion run to ``max_tokens``."""

    model: str
    prompt_tokens: int
    max_completion_tokens: int
    usd: float

    def describe(self) -> dict[str, Any]:
        """A JSON-safe snapshot, marked with the bound it represents."""
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "max_completion_tokens": self.max_completion_tokens,
            "usd": self.usd,
            "basis": "upper bound: estimated prompt + completion run to max_tokens",
        }


def estimate_request_cost(request: LLMRequest) -> CostEstimate:
    """Price ``request``'s worst case. Raises :class:`UnknownModelPrice` if it cannot."""
    price = price_for(request.model)
    prompt_tokens = estimate_request_tokens(request)
    usage = TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=request.max_tokens)
    return CostEstimate(
        model=request.model,
        prompt_tokens=prompt_tokens,
        max_completion_tokens=request.max_tokens,
        usd=price.cost(usage),
    )


@dataclass
class CostGuard:
    """A hard ceiling on what a session may spend. Mutable; one per run.

    Used as ``reserve`` (before the call, on the worst case) then ``settle`` (after
    it, on the truth). ``max_usd`` defaults to zero, so an unconfigured guard admits
    only calls that cost nothing.
    """

    max_usd: float = DEFAULT_MAX_USD
    spent_usd: float = 0.0
    calls: int = 0

    def __post_init__(self) -> None:
        if self.max_usd < 0:
            raise ValueError(f"max_usd must be non-negative, got {self.max_usd}")
        if self.spent_usd < 0:
            raise ValueError(f"spent_usd must be non-negative, got {self.spent_usd}")

    def remaining_usd(self) -> float:
        """Budget left. Never negative, even if a settled call overshot its reservation."""
        return max(0.0, self.max_usd - self.spent_usd)

    def reserve(self, estimate: CostEstimate) -> None:
        """Admit or refuse a call **before** it is sent.

        Raises :class:`CostLimitExceeded` when the estimate's worst case does not fit
        in the remaining budget. The exception is the guarantee: an adapter calls this
        before touching a transport, so a refusal means no request left the process.
        """
        if estimate.usd > self.remaining_usd() + EPSILON:
            raise CostLimitExceeded(
                f"cost guard refused a call to {estimate.model!r}: worst-case "
                f"${estimate.usd:.6f} exceeds the remaining budget "
                f"${self.remaining_usd():.6f} (of ${self.max_usd:.6f}, "
                f"${self.spent_usd:.6f} already spent). No request was sent."
            )

    def settle(self, model: str, usage: TokenUsage) -> float:
        """Record what a completed call actually consumed; return its USD cost.

        Records the truth even when it exceeds the reservation. The guard cannot
        refund a call that already happened — it can only refuse the next one, which
        it will, because ``spent_usd`` has grown.
        """
        usd = price_for(model).cost(usage)
        self.spent_usd += usd
        self.calls += 1
        return usd

    def describe(self) -> dict[str, Any]:
        """A JSON-safe snapshot for the trace, the report, and the CLI."""
        return {
            "max_usd": self.max_usd,
            "spent_usd": self.spent_usd,
            "remaining_usd": self.remaining_usd(),
            "calls": self.calls,
            "policy": "reserve worst case before the call; settle actual after it",
        }


__all__ = [
    "CHARS_PER_TOKEN",
    "DEFAULT_MAX_USD",
    "EPSILON",
    "FREE",
    "MESSAGE_TOKEN_OVERHEAD",
    "CostEstimate",
    "CostGuard",
    "CostLimitExceeded",
    "ModelPrice",
    "UnknownModelPrice",
    "estimate_request_cost",
    "estimate_request_tokens",
    "estimate_tokens",
    "price_for",
    "price_table",
    "register_price",
    "unregister_price",
]
