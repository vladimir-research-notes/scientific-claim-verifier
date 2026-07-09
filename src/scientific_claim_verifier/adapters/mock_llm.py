"""The mock adapter: a deterministic stand-in for a model, for tests.

Milestone 10, and ``docs/PLAN.md`` §8's ``MockLLMAdapter``. It answers from a pure
function of the request — by default, an extraction response with **every field null
or empty**.

That default is a deliberate choice about what "no model" should look like. The
alternative, returning a plausible-looking extraction, would let a test pass while the
adapter under test was never really consulted. An empty extraction is the same outcome
the rule-based extractor produces when its rules decline to fire, and it is scored
``underspecified`` downstream — the safe label. A mock that guesses would be a mock that
lies.

Usage is reported through :func:`~scientific_claim_verifier.adapters.cost.estimate_tokens`
rather than invented, so a mock run exercises the same estimator a paid run would, and
``mock-llm-v1`` is priced at zero because nothing about it costs anything.

This adapter opens no file, reads no environment variable, and touches no clock. Two
calls with the same request return the same response, forever.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, ClassVar

from . import cost
from .base import MOCK_MODEL, LLMAdapter, LLMRequest, LLMResponse, TokenUsage

#: What the default responder returns: a model that extracted nothing at all.
EMPTY_EXTRACTION: dict[str, Any] = {
    "expected_value": None,
    "baseline_value": None,
    "comparison_operator": None,
    "units": None,
    "metrics": [],
    "datasets": [],
    "entities": [],
    "conditions": [],
}

#: The default responder's text: :data:`EMPTY_EXTRACTION` as canonical JSON.
EMPTY_EXTRACTION_JSON = json.dumps(EMPTY_EXTRACTION, sort_keys=True)

#: A responder maps a request to the text a model would have returned.
Responder = Callable[[LLMRequest], str]


def empty_extraction_responder(_request: LLMRequest) -> str:
    """The default: an extraction in which the model committed to nothing."""
    return EMPTY_EXTRACTION_JSON


class MockLLMAdapter(LLMAdapter):
    """A deterministic, free, in-process adapter. Never leaves the interpreter."""

    name: ClassVar[str] = "mock"
    spends_money: ClassVar[bool] = False

    def __init__(self, responder: Responder | None = None, *, model: str = MOCK_MODEL) -> None:
        self._responder = responder or empty_extraction_responder
        self._model = model
        self.calls = 0

    @classmethod
    def returning(cls, text: str, *, model: str = MOCK_MODEL) -> MockLLMAdapter:
        """A mock that answers every request with ``text``. For tests."""
        return cls(lambda _request: text, model=model)

    @property
    def default_model(self) -> str:
        return self._model

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Answer from the responder. Usage is estimated; cost is zero, and true."""
        self.calls += 1
        text = self._responder(request)
        usage = TokenUsage(
            prompt_tokens=cost.estimate_request_tokens(request),
            completion_tokens=cost.estimate_tokens(text),
        )
        return LLMResponse(text=text, model=self._model, adapter=self.name, usage=usage)

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "calls": self.calls, "source": "in-process function"}


__all__ = [
    "EMPTY_EXTRACTION",
    "EMPTY_EXTRACTION_JSON",
    "MockLLMAdapter",
    "Responder",
    "empty_extraction_responder",
]
