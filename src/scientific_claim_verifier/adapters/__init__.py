"""Optional LLM adapters. Off by default; the default pipeline never comes here.

Milestone 10. ``docs/PLAN.md`` §8 fixes the policy: version 1 of this project is
non-LLM or mock-LLM. The rule-based extractor (Milestone 3) is the baseline that runs,
and it is transparent — every field it populates names the rule that produced it. These
adapters exist so that a *comparison* is possible and a paid path is *specified*, not so
that a model is in the loop.

Three adapters, one interface:

=================  ===========================================================
``mock``           :class:`~.mock_llm.MockLLMAdapter` — a deterministic pure
                   function of the request. Answers "I extracted nothing" unless
                   told otherwise. For tests.
``recorded``       :class:`~.recorded_llm.RecordedLLMAdapter` — replays committed,
                   hand-authored fixture responses by request fingerprint. Raises
                   on a miss; never falls back to a live call.
``api``            :class:`~.api_stub.ApiAdapterStub` — the paid interface.
                   Disabled, dry-run, cost-guarded, and shipped with no transport.
=================  ===========================================================

The first two are free and offline by construction: they open no socket because nothing
in this package can. The third is free because it cannot reach anything — see
:mod:`~scientific_claim_verifier.adapters.api_stub` for the four gates, and
:mod:`~scientific_claim_verifier.adapters.cost` for why an unpriced model is an
uncallable one.

``spends_money`` is declared per adapter so this can be checked rather than asserted:
``tests/test_adapters.py`` enumerates the registry and pins that exactly one adapter is
capable of a paid call, that :func:`build_adapter` returns it disabled and in dry-run,
and that a counting fake transport is never reached from a default build.

Nothing in :mod:`scientific_claim_verifier.cli`'s default path constructs an adapter.
``claimverifier extract-claims`` uses the rule-based extractor unless ``--extractor`` says
otherwise, and ``verify``, ``run-suite``, and ``report`` do not accept an adapter at all.
"""

from __future__ import annotations

from .api_stub import (
    OPT_IN_ENV,
    OPT_IN_VALUE,
    ApiAdapterStub,
    NoTransportConfigured,
    PaidAPIDisabled,
    Transport,
    paid_api_enabled,
)
from .base import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    MOCK_MODEL,
    RECORDED_MODEL,
    AdapterError,
    LLMAdapter,
    LLMRequest,
    LLMResponse,
    TokenUsage,
)
from .cache import DEFAULT_CACHE_DIR, ResponseCache
from .cost import (
    DEFAULT_MAX_USD,
    CostEstimate,
    CostGuard,
    CostLimitExceeded,
    ModelPrice,
    UnknownModelPrice,
    estimate_request_cost,
    estimate_request_tokens,
    estimate_tokens,
    price_for,
    price_table,
    register_price,
    unregister_price,
)
from .mock_llm import MockLLMAdapter
from .recorded_llm import (
    RecordedLLMAdapter,
    Recording,
    RecordingNotFound,
    RecordingsError,
    default_recordings_path,
    read_recordings,
    write_recordings,
)

#: Every adapter name :func:`build_adapter` accepts, in the order the CLI lists them.
ADAPTER_NAMES = ("mock", "recorded", "api")

#: The extractor the pipeline uses when nobody says otherwise. Not an adapter.
DEFAULT_EXTRACTOR = "rule"

#: What ``--extractor`` accepts. ``rule`` is the default and the only one in the
#: default path; the rest route claim extraction through an adapter.
EXTRACTOR_NAMES = ("rule", "recorded", "mock")


def build_adapter(
    name: str,
    *,
    recordings: str | None = None,
    model: str | None = None,
) -> LLMAdapter:
    """Construct the named adapter in its **safe** configuration.

    ``api`` is returned disabled, in dry-run, with a zero-dollar
    :class:`~.cost.CostGuard` and no transport. Making it spend money takes four
    deliberate acts, none of which this function performs. ``model`` names the model the
    ``api`` stub would address; it is unpriced, so even a fully opted-in caller is
    refused until they register a price.
    """
    if name == "mock":
        return MockLLMAdapter()
    if name == "recorded":
        return RecordedLLMAdapter.from_file(recordings)
    if name == "api":
        return ApiAdapterStub(model or "unpriced-model")
    raise ValueError(f"unknown adapter {name!r}; expected one of {', '.join(ADAPTER_NAMES)}")


def registry() -> dict[str, type[LLMAdapter]]:
    """Map each adapter name to its class, without constructing anything."""
    return {"mock": MockLLMAdapter, "recorded": RecordedLLMAdapter, "api": ApiAdapterStub}


__all__ = [
    "ADAPTER_NAMES",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_EXTRACTOR",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MAX_USD",
    "DEFAULT_TEMPERATURE",
    "EXTRACTOR_NAMES",
    "MOCK_MODEL",
    "OPT_IN_ENV",
    "OPT_IN_VALUE",
    "RECORDED_MODEL",
    "AdapterError",
    "ApiAdapterStub",
    "CostEstimate",
    "CostGuard",
    "CostLimitExceeded",
    "LLMAdapter",
    "LLMRequest",
    "LLMResponse",
    "MockLLMAdapter",
    "ModelPrice",
    "NoTransportConfigured",
    "PaidAPIDisabled",
    "RecordedLLMAdapter",
    "Recording",
    "RecordingNotFound",
    "RecordingsError",
    "ResponseCache",
    "TokenUsage",
    "Transport",
    "UnknownModelPrice",
    "build_adapter",
    "default_recordings_path",
    "estimate_request_cost",
    "estimate_request_tokens",
    "estimate_tokens",
    "paid_api_enabled",
    "price_for",
    "price_table",
    "read_recordings",
    "register_price",
    "registry",
    "unregister_price",
    "write_recordings",
]
