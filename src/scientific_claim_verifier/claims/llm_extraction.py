"""Claim extraction through an LLM adapter — the same contract, a different method.

Milestone 10. :class:`LLMClaimExtractor` implements the same call as
:class:`~scientific_claim_verifier.claims.extraction.RuleBasedClaimExtractor` —
``extract(claim, bundle) -> Extraction`` — so the two are swappable, and so
:func:`~scientific_claim_verifier.claims.extraction.score_extraction` scores them
against the same gold, field for field, with no special pleading for either.

**The model fills eight fields. It does not do anything else.** It is asked for exactly
the :data:`~scientific_claim_verifier.claims.extraction.SCORED_FIELDS`, as JSON. The
``normalized_claim`` is then computed by
:mod:`~scientific_claim_verifier.claims.normalization` and the artifact references by
:func:`~scientific_claim_verifier.claims.extraction.extract_references` — deterministic
code, not model output — because normalization is this project's own canonical notation
and reference resolution is a lookup against the bundle, not an act of language
understanding. :attr:`Extraction.rules_fired` says which parts came from where, so a
reader of the audit trail is never left guessing what the model was responsible for.

**The response is parsed strictly.** :class:`ExtractionResponse` forbids unknown keys, so
a hallucinated ``"confidence"`` field fails the parse instead of being dropped in
silence, and an operator outside :class:`~scientific_claim_verifier.schemas.ComparisonOperator`
fails rather than being coerced. A model that cannot produce the schema has not produced
an extraction. The one indulgence is a Markdown code fence around the JSON, which models
emit constantly and which :func:`strip_code_fence` removes; that tolerance is a
concession to reality and is bounded to exactly that.

**Failure is loud.** A malformed response raises :class:`ExtractionResponseError`; a
dry-run response — which carries no content by construction — raises before anything is
parsed, rather than being read as a model that extracted nothing. The rule-based
extractor's conservatism (leave a field empty rather than guess) is a property of its
*rules*; it is not a licence for this module to turn a broken response into an empty
claim, because the two are scored identically downstream and mean entirely different
things.

Determinism: the prompt is a pure function of the claim and the bundle, ordered as the
task file orders them, with no clock, no RNG, and no absolute path. Temperature is ``0``.
The prompt template's identity is recorded as :data:`PROMPT_VERSION`, and it is part of
each request's fingerprint by construction — change the template and every committed
recording misses, loudly. See :mod:`scientific_claim_verifier.adapters.recorded_llm`.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..adapters.base import DEFAULT_MAX_TOKENS, AdapterError, LLMAdapter, LLMRequest
from ..schemas import ArtifactBundle, ComparisonOperator, ScientificClaim
from . import extraction, normalization
from .extraction import Extraction

#: Identity of the prompt template below. Bump it when the template changes — though
#: nothing depends on you remembering to: the template's text is fingerprinted with the
#: request, so a stale recording misses whether or not this string moved.
PROMPT_VERSION = "claim-extract-v1"

#: How much output a claim extraction may take. Also the completion the cost guard
#: reserves against, so it is a budget knob, not only a generation one.
MAX_TOKENS = DEFAULT_MAX_TOKENS

#: The eight fields the model is asked for. Exactly the scored fields, in a fixed order.
RESPONSE_FIELDS = extraction.SCORED_FIELDS

SYSTEM_PROMPT = (
    "You are a claim-extraction function for a scientific claim verifier. "
    "You convert one scientific claim into structured fields. "
    "You output a single JSON object and nothing else: no prose, no explanation. "
    "Leave a field null or empty rather than guessing; an unextracted field is "
    "handled safely downstream, and a wrong one is not. "
    "Report values exactly as the claim states them; do not convert units or scales."
)

_SCHEMA_BLOCK = """{
  "expected_value": number or null,       // the headline value the claim asserts
  "baseline_value": number or null,       // the "from" value of a comparison, else null
  "comparison_operator": one of "=", ">", "<", ">=", "<=", "~", or null,
  "units": "%" or null,                   // only if the claim's value is a percentage
  "metrics": [string],                    // canonical metric names, e.g. ["accuracy"]
  "datasets": [string],                   // dataset or benchmark names named in the claim
  "entities": [string],                   // methods, models, or baselines named in the claim
  "conditions": [string]                  // stated conditions, e.g. ["n = 12"]
}"""


class ExtractionResponseError(AdapterError):
    """Raised when an adapter's response is not a valid extraction JSON object."""


class ExtractionResponse(BaseModel):
    """The strict schema of the model's reply. Unknown keys are a parse failure."""

    model_config = ConfigDict(extra="forbid")

    expected_value: float | None = None
    baseline_value: float | None = None
    comparison_operator: ComparisonOperator | None = None
    units: str | None = None
    metrics: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)

    def populated_fields(self) -> list[str]:
        """The names of the fields the model actually committed to, in schema order."""
        return [
            name
            for name in RESPONSE_FIELDS
            if getattr(self, name) not in (None, [], "")
        ]


# ---------------------------------------------------------------------------
# Prompt construction (a pure function of the claim and the bundle)
# ---------------------------------------------------------------------------


def bundle_inventory(bundle: ArtifactBundle) -> list[str]:
    """A compact, ordered inventory of what the bundle holds.

    Ids and shapes only — passage sections, table columns, dataset columns, code
    entrypoints. Passage *text* and dataset *descriptions* are deliberately omitted: the
    fields being extracted come from the claim sentence, the inventory exists so a
    dataset or table named in that sentence can be recognised, and a prompt that carried
    the whole paper would cost more and say less. Order follows the task file, which is
    itself deterministic.
    """
    lines: list[str] = []
    for paper in bundle.papers:
        passages = ", ".join(
            f"{p.passage_id}" + (f" ({p.section})" if p.section else "") for p in paper.passages
        )
        lines.append(f"paper {paper.artifact_id}: passages [{passages or 'none'}]")
    for table in bundle.tables:
        lines.append(f"table {table.table_id}: columns {list(table.columns)}")
    for dataset in bundle.datasets:
        lines.append(f"dataset {dataset.artifact_id}: columns {list(dataset.columns)}")
    for code in bundle.code_files:
        lines.append(f"code {code.artifact_id}: entrypoint {code.entrypoint or 'unspecified'}")
    return lines


def build_extraction_prompt(claim: ScientificClaim, bundle: ArtifactBundle) -> str:
    """Render the user prompt for one claim. Deterministic; no clock, no paths."""
    inventory = bundle_inventory(bundle) or ["(the bundle holds no artifacts)"]
    inventory_block = "\n".join(f"  - {line}" for line in inventory)
    return (
        f"Claim id: {claim.claim_id}\n"
        f"Claim type: {claim.claim_type.value}\n"
        f"Claim text: {claim.claim_text.strip()}\n"
        f"\n"
        f"Artifacts available (ids and shapes only):\n"
        f"{inventory_block}\n"
        f"\n"
        f"Return one JSON object with exactly these keys:\n"
        f"{_SCHEMA_BLOCK}\n"
        f"\n"
        f"Rules:\n"
        f"  - Use only what the claim text states. The artifact list is for recognising "
        f"names, not for reading values out of.\n"
        f"  - A comparison such as \"improves from X to Y\" sets baseline_value=X, "
        f"expected_value=Y, comparison_operator=\">\".\n"
        f"  - A recomputation claim (a dataset statistic, a script's output) uses \"~\".\n"
        f"  - A sample count such as \"12 samples\" is the metric \"count\" and the "
        f"condition \"n = 12\", not the headline value.\n"
        f"  - Output the JSON object alone."
    )


def build_request(
    claim: ScientificClaim,
    bundle: ArtifactBundle,
    *,
    model: str,
    max_tokens: int = MAX_TOKENS,
) -> LLMRequest:
    """The full request for one claim: system message, prompt, model, ``temperature=0``."""
    return LLMRequest(
        model=model,
        prompt=build_extraction_prompt(claim, bundle),
        system=SYSTEM_PROMPT,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# Response parsing (strict)
# ---------------------------------------------------------------------------


def strip_code_fence(text: str) -> str:
    """Remove a surrounding Markdown code fence, if present. Otherwise a no-op.

    Handles ```` ```json ```` and a bare ```` ``` ````. This is the single tolerated
    deviation from "a single JSON object and nothing else": models emit fences
    reflexively, and refusing them would test the prompt rather than the extraction.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    lines = lines[1:]  # drop the opening fence and any language tag
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _excerpt(text: str, limit: int = 200) -> str:
    """A bounded, single-line excerpt of a bad response, for the error message."""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit] + "…"


def parse_extraction_response(text: str) -> ExtractionResponse:
    """Parse a model reply into an :class:`ExtractionResponse`, strictly.

    Raises :class:`ExtractionResponseError` on anything that is not a JSON object
    matching the schema exactly: a fenced blob is unwrapped first, but an unknown key,
    a bad operator, a JSON array, or prose is a failure. It is not this function's job
    to salvage a response the model was asked, unambiguously, to format.
    """
    body = strip_code_fence(text)
    if not body:
        raise ExtractionResponseError("the adapter returned an empty response")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ExtractionResponseError(
            f"response is not valid JSON ({exc.msg}): {_excerpt(body)!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise ExtractionResponseError(
            f"response must be a JSON object, got {type(payload).__name__}: {_excerpt(body)!r}"
        )
    try:
        return ExtractionResponse.model_validate(payload)
    except ValidationError as exc:
        raise ExtractionResponseError(
            f"response does not match the extraction schema: {exc.error_count()} problem(s); "
            f"first: {exc.errors()[0].get('loc')} {exc.errors()[0].get('msg')}"
        ) from exc


# ---------------------------------------------------------------------------
# The extractor
# ---------------------------------------------------------------------------


class LLMClaimExtractor:
    """Extracts a claim's structured fields by asking an adapter. Not the default path."""

    def __init__(self, adapter: LLMAdapter, *, model: str | None = None) -> None:
        self.adapter = adapter
        self.model = model or adapter.default_model

    def extract(self, claim: ScientificClaim, bundle: ArtifactBundle) -> Extraction:
        """Populate a copy of ``claim`` from the adapter's reply. Never mutates the input.

        Raises :class:`ExtractionResponseError` if the reply is unusable — including a
        dry-run reply, which carries no content by construction and must not be mistaken
        for a model that extracted nothing.
        """
        request = build_request(claim, bundle, model=self.model)
        response = self.adapter.complete(request)

        if response.dry_run:
            raise ExtractionResponseError(
                "the adapter is in dry-run mode and returned no content; a dry run prices "
                "a call, it does not make one. Its estimate was "
                f"${response.estimated_usd:.6f}."
            )

        parsed = parse_extraction_response(response.text)
        populated = ScientificClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            source_document_id=claim.source_document_id,
            source_passage=claim.source_passage,
            claim_type=claim.claim_type,
            entities=list(parsed.entities),
            metrics=list(parsed.metrics),
            datasets=list(parsed.datasets),
            conditions=list(parsed.conditions),
            expected_value=parsed.expected_value,
            baseline_value=parsed.baseline_value,
            comparison_operator=parsed.comparison_operator,
            units=parsed.units,
        )
        populated.normalized_claim = normalization.normalize(populated)

        return Extraction(
            claim=populated,
            references=extraction.extract_references(claim.claim_text, bundle),
            rules_fired=self._provenance(request, response, parsed),
        )

    def _provenance(
        self, request: LLMRequest, response: Any, parsed: ExtractionResponse
    ) -> list[str]:
        """The audit trail: what the model was asked, what it answered, what it did not do."""
        returned = ", ".join(parsed.populated_fields()) or "(none)"
        return [
            f"llm: adapter={self.adapter.name} model={self.model} prompt={PROMPT_VERSION}",
            f"llm: request fingerprint={request.fingerprint()[:12]}",
            (
                f"llm: usage prompt={response.usage.prompt_tokens} "
                f"completion={response.usage.completion_tokens} "
                f"cost_usd={response.cost_usd:.6f} cached={str(response.cached).lower()}"
            ),
            f"llm: fields returned = {returned}",
            "deterministic (not model output): normalized_claim, references",
        ]


__all__ = [
    "MAX_TOKENS",
    "PROMPT_VERSION",
    "RESPONSE_FIELDS",
    "SYSTEM_PROMPT",
    "ExtractionResponse",
    "ExtractionResponseError",
    "LLMClaimExtractor",
    "build_extraction_prompt",
    "build_request",
    "bundle_inventory",
    "parse_extraction_response",
    "strip_code_fence",
]
