"""The paid-API stub: an interface, four gates, and no way to spend money.

Milestone 10, and ``docs/PLAN.md`` §8's ``ApiAdapterStub`` — "interface only, disabled
by default, cost-guarded". ``CLAUDE.md`` names five things any paid-API mode must have:
**dry-run**, a **response cache**, a **token/cost estimator**, a **hard max-cost guard**,
and **explicit opt-in**. All five are here. None of them is what actually makes the
default path free.

What makes it free is that there is nothing to call. ``transport`` is ``None`` by
default, ``pyproject.toml`` declares no HTTP client, and no module in this package
imports one — a property ``tests/test_adapters.py`` asserts by reading the source. A
caller who genuinely wants to spend money must **inject** a transport: a callable taking
an :class:`~scientific_claim_verifier.adapters.base.LLMRequest` and returning
``(text, TokenUsage)``. That inversion is what lets every guard below be tested to
destruction offline, with a counting fake, and it is why this module is a stub rather
than a client.

Four gates stand between a request and a transport, checked in this order. Each is
independently sufficient to stop the call, and the default configuration fails all four:

1. **Opt-in, in code.** ``enabled=False`` by default. → :class:`PaidAPIDisabled`
2. **Opt-in, in the environment.** ``SCV_ENABLE_PAID_API=1`` must also be set, so a
   library that flipped ``enabled`` cannot spend an operator's money without the
   operator's shell agreeing. → :class:`PaidAPIDisabled`
3. **The cost guard.** :meth:`~scientific_claim_verifier.adapters.cost.CostGuard.reserve`
   prices the worst case and refuses if it does not fit the budget, which is ``$0.00``
   unless set. → :class:`~scientific_claim_verifier.adapters.cost.CostLimitExceeded`
4. **The transport.** ``None``. → :class:`NoTransportConfigured`

A fifth gate sits before all of them and is not about permission: an **unpriced model
cannot be costed**, so :func:`~scientific_claim_verifier.adapters.cost.price_for` raises
and the call ends before any gate is consulted. The repo registers no vendor prices.

Dry run
-------
``dry_run=True`` is the default, and it is checked *before* the opt-in gates: pricing a
run must not require permission to pay for it. The invariant is one line —

    **a dry run never returns model content and never spends** —

and it is enforced by :class:`~scientific_claim_verifier.adapters.base.LLMResponse`
itself, which refuses to hold text or a cost when ``dry_run`` is set. A dry run reports
``estimated_usd``: the upper bound for a live call, or ``0.0`` when the response is
already cached and a live call would not be made at all. Content-free is the point —
a caller cannot mistake a plan for an answer, and
:class:`~scientific_claim_verifier.claims.llm_extraction.LLMClaimExtractor` refuses a
dry-run response explicitly rather than parsing ``""`` into an empty extraction.

Cache hits are free and skip the guard entirely: money already spent is not spent again.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any, ClassVar

from . import cost
from .base import AdapterError, LLMAdapter, LLMRequest, LLMResponse, TokenUsage
from .cache import ResponseCache

#: The environment variable that must equal :data:`OPT_IN_VALUE` for a live call.
OPT_IN_ENV = "SCV_ENABLE_PAID_API"

#: The only value of :data:`OPT_IN_ENV` that opts in. ``"true"``, ``"yes"``, and
#: ``"1 "`` do not: an ambiguous opt-in is not an opt-in.
OPT_IN_VALUE = "1"

#: A transport takes a request and returns ``(text, usage)``. The repo ships none.
Transport = Callable[[LLMRequest], tuple[str, TokenUsage]]


class PaidAPIDisabled(AdapterError):
    """Raised when a live call is attempted without both opt-in gates open."""


class NoTransportConfigured(AdapterError):
    """Raised when every gate is open but no transport was injected. There is none to find."""


def paid_api_enabled(env: Mapping[str, str] | None = None) -> bool:
    """True only if :data:`OPT_IN_ENV` is exactly :data:`OPT_IN_VALUE` in ``env``."""
    source = os.environ if env is None else env
    return source.get(OPT_IN_ENV) == OPT_IN_VALUE


class ApiAdapterStub(LLMAdapter):
    """A cost-guarded, opt-in, transport-less paid-API adapter. Disabled by default."""

    name: ClassVar[str] = "api"
    spends_money: ClassVar[bool] = True

    def __init__(
        self,
        model: str,
        *,
        enabled: bool = False,
        dry_run: bool = True,
        guard: cost.CostGuard | None = None,
        cache: ResponseCache | None = None,
        transport: Transport | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._model = model
        self.enabled = enabled
        self.dry_run = dry_run
        self.guard = guard if guard is not None else cost.CostGuard()
        self.cache = cache
        self.transport = transport
        self._env = env
        self.calls = 0

    @property
    def default_model(self) -> str:
        return self._model

    # -- gates ---------------------------------------------------------------

    def opted_in(self) -> bool:
        """True when both opt-in gates are open: the flag *and* the environment."""
        return self.enabled and paid_api_enabled(self._env)

    def _require_opt_in(self) -> None:
        if not self.enabled:
            raise PaidAPIDisabled(
                "paid API calls are disabled: this adapter was constructed with "
                "enabled=False. Nothing was sent."
            )
        if not paid_api_enabled(self._env):
            raise PaidAPIDisabled(
                f"paid API calls are disabled: set {OPT_IN_ENV}={OPT_IN_VALUE} to opt in. "
                f"Nothing was sent."
            )

    # -- estimation ----------------------------------------------------------

    def estimate(self, request: LLMRequest) -> cost.CostEstimate:
        """The worst-case cost of ``request``. Raises if the model has no price."""
        return cost.estimate_request_cost(request)

    # -- the call ------------------------------------------------------------

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Answer ``request``, or refuse. The transport is the last thing reached.

        Order: price it (an unpriced model is uncallable) → look in the cache → dry-run
        reports and stops → a hit returns free → both opt-in gates → the cost guard →
        the transport. Every path that returns without a transport call also leaves
        ``guard.spent_usd`` untouched.
        """
        self.calls += 1
        estimate = self.estimate(request)
        cached = self.cache.get(request) if self.cache is not None else None

        if self.dry_run:
            would_cost = 0.0 if cached is not None else estimate.usd
            return LLMResponse(
                text="",
                model=request.model,
                adapter=self.name,
                usage=TokenUsage(
                    prompt_tokens=estimate.prompt_tokens,
                    completion_tokens=estimate.max_completion_tokens,
                ),
                cached=cached is not None,
                dry_run=True,
                estimated_usd=would_cost,
                finish_reason="dry_run",
            )

        if cached is not None:
            return cached

        self._require_opt_in()
        self.guard.reserve(estimate)

        if self.transport is None:
            raise NoTransportConfigured(
                "no transport is configured, and this repository ships none: no HTTP "
                "client is declared in pyproject.toml and no module under adapters/ "
                "imports one. Inject a callable (LLMRequest) -> (text, TokenUsage) to "
                "make a real call, and accept responsibility for what it costs."
            )

        text, usage = self.transport(request)
        spent = self.guard.settle(request.model, usage)
        response = LLMResponse(
            text=text, model=request.model, adapter=self.name, usage=usage, cost_usd=spent
        )
        if self.cache is not None:
            self.cache.put(request, response)
        return response

    def describe(self) -> dict[str, Any]:
        """A JSON-safe snapshot of every gate, for the ``adapters`` command and traces."""
        return {
            **super().describe(),
            "calls": self.calls,
            "enabled": self.enabled,
            "env_opt_in": paid_api_enabled(self._env),
            "env_var": OPT_IN_ENV,
            "opted_in": self.opted_in(),
            "dry_run": self.dry_run,
            "transport": "configured" if self.transport is not None else "none (ships none)",
            "guard": self.guard.describe(),
            "cache": self.cache.describe() if self.cache is not None else None,
        }


__all__ = [
    "OPT_IN_ENV",
    "OPT_IN_VALUE",
    "ApiAdapterStub",
    "NoTransportConfigured",
    "PaidAPIDisabled",
    "Transport",
    "paid_api_enabled",
]
