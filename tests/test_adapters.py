"""Milestone 10 — optional LLM adapters (CPU-only, offline, free).

These tests hold the adapters to the promises their docstrings make. The load-bearing
ones are about money and network:

- Exactly one adapter is even *capable* of a paid call, and :func:`build_adapter`
  returns it disabled, in dry-run, with a zero-dollar guard and no transport.
- No module under ``adapters/`` imports an HTTP client, and ``pyproject.toml`` declares
  none — so the free path is free by construction, not by configuration.
- The four gates (opt-in flag, opt-in env, cost guard, transport) each stop a call on
  their own, and a counting fake transport is never reached from a default build.
- Estimated money and actual money never share a field; a dry run and a cache hit both
  spend nothing and say so.

The recorded-adapter results measure the *harness* (fingerprint → replay → parse →
score), not any model; the recordings are hand-authored synthetic fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scientific_claim_verifier.adapters import (
    ADAPTER_NAMES,
    OPT_IN_ENV,
    OPT_IN_VALUE,
    ApiAdapterStub,
    CostGuard,
    CostLimitExceeded,
    LLMRequest,
    LLMResponse,
    MockLLMAdapter,
    ModelPrice,
    NoTransportConfigured,
    PaidAPIDisabled,
    RecordedLLMAdapter,
    RecordingNotFound,
    ResponseCache,
    TokenUsage,
    UnknownModelPrice,
    build_adapter,
    paid_api_enabled,
    registry,
)
from scientific_claim_verifier.adapters import cost as cost_mod
from scientific_claim_verifier.adapters import fixtures as fixtures_mod
from scientific_claim_verifier.adapters.base import MOCK_MODEL, RECORDED_MODEL
from scientific_claim_verifier.adapters.cache import CACHE_FORMAT
from scientific_claim_verifier.adapters.recorded_llm import (
    Recording,
    RecordingsError,
    default_recordings_path,
    read_recordings,
    render_recordings,
)
from scientific_claim_verifier.artifacts import loader
from scientific_claim_verifier.claims import extraction as extraction_mod
from scientific_claim_verifier.claims.extraction import build_extractor, score_extraction
from scientific_claim_verifier.claims.llm_extraction import (
    ExtractionResponse,
    ExtractionResponseError,
    LLMClaimExtractor,
    build_request,
    parse_extraction_response,
    strip_code_fence,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "tasks"

#: HTTP clients that must never appear in this package or its declared dependencies.
HTTP_CLIENTS = (
    "requests", "httpx", "aiohttp", "urllib3", "http.client", "socket", "urllib.request",
)

#: The four recorded fixtures and their known scores against gold (dataset_mean is the
#: one deliberate miss; see adapters/fixtures.py).
RECORDED_SCORES = {
    "accuracy_improvement": 8,
    "dataset_mean": 6,
    "underspecified_split": 8,
    "gc_content": 8,
}


@pytest.fixture(autouse=True)
def _isolate_prices():
    """Snapshot and restore the module-global price table around every test."""
    before = cost_mod.price_table()
    yield
    for model in list(cost_mod.price_table()):
        if model not in before:
            cost_mod.unregister_price(model)
    for model, price in before.items():
        cost_mod.register_price(model, price)


class CountingTransport:
    """A fake transport that records how many times it was reached."""

    def __init__(self, text: str = "live", usage: TokenUsage | None = None) -> None:
        self.calls = 0
        self.text = text
        self.usage = usage or TokenUsage(prompt_tokens=10, completion_tokens=5)

    def __call__(self, request: LLMRequest) -> tuple[str, TokenUsage]:
        self.calls += 1
        return self.text, self.usage


# ---------------------------------------------------------------------------
# base.py — the request/response contract
# ---------------------------------------------------------------------------


def test_request_fingerprint_is_deterministic():
    a = LLMRequest(model="m", prompt="p", system="s", temperature=0.0, max_tokens=64)
    b = LLMRequest(model="m", prompt="p", system="s", temperature=0.0, max_tokens=64)
    assert a.fingerprint() == b.fingerprint()
    assert len(a.fingerprint()) == 64  # sha256 hex


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "other"},
        {"prompt": "other"},
        {"system": "other"},
        {"temperature": 0.7},
        {"max_tokens": 128},
    ],
)
def test_each_fingerprinted_field_changes_the_digest(kwargs):
    base = {"model": "m", "prompt": "p", "system": "s", "temperature": 0.0, "max_tokens": 64}
    assert LLMRequest(**base).fingerprint() != LLMRequest(**{**base, **kwargs}).fingerprint()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "", "prompt": "p"},
        {"model": "m", "prompt": ""},
        {"model": "m", "prompt": "p", "max_tokens": 0},
        {"model": "m", "prompt": "p", "temperature": 2.5},
        {"model": "m", "prompt": "p", "temperature": -0.1},
    ],
)
def test_request_rejects_invalid_fields(kwargs):
    with pytest.raises(ValueError):
        LLMRequest(**kwargs)


def test_token_usage_rejects_negative_and_sums():
    with pytest.raises(ValueError):
        TokenUsage(prompt_tokens=-1)
    assert TokenUsage(prompt_tokens=10, completion_tokens=5).total_tokens == 15


def test_response_dry_run_may_not_carry_content_or_cost():
    with pytest.raises(ValueError):
        LLMResponse(text="hi", model="m", adapter="api", dry_run=True)
    with pytest.raises(ValueError):
        LLMResponse(text="", model="m", adapter="api", dry_run=True, cost_usd=0.01)


def test_response_estimated_usd_only_on_dry_run():
    with pytest.raises(ValueError):
        LLMResponse(text="hi", model="m", adapter="api", estimated_usd=0.5)
    # allowed on a dry run
    r = LLMResponse(text="", model="m", adapter="api", dry_run=True, estimated_usd=0.5)
    assert r.estimated_usd == 0.5


def test_cached_response_may_not_carry_a_cost():
    with pytest.raises(ValueError):
        LLMResponse(text="hi", model="m", adapter="api", cached=True, cost_usd=0.01)
    with pytest.raises(ValueError):
        LLMResponse(text="hi", model="m", adapter="api", cost_usd=-1.0)


# ---------------------------------------------------------------------------
# cost.py — estimator, prices, and the hard guard
# ---------------------------------------------------------------------------


def test_estimate_tokens_is_monotonic_and_charges_overhead():
    assert cost_mod.estimate_tokens("") == cost_mod.MESSAGE_TOKEN_OVERHEAD
    assert cost_mod.estimate_tokens("a" * 30) >= cost_mod.estimate_tokens("a" * 3)
    # upper bound: chars/3 rounds up, well above a real ~chars/4 tokenizer
    assert cost_mod.estimate_tokens("a" * 300) >= 100


def test_price_for_unknown_model_raises():
    with pytest.raises(UnknownModelPrice):
        cost_mod.price_for("some-vendor-model")


def test_builtin_models_are_free():
    assert cost_mod.price_for(MOCK_MODEL).cost(TokenUsage(1000, 1000)) == 0.0
    assert cost_mod.price_for(RECORDED_MODEL).cost(TokenUsage(1000, 1000)) == 0.0


def test_register_and_unregister_price():
    cost_mod.register_price("vendor-x", ModelPrice(0.003, 0.015))
    assert cost_mod.price_for("vendor-x").prompt_usd_per_1k == 0.003
    cost_mod.unregister_price("vendor-x")
    with pytest.raises(UnknownModelPrice):
        cost_mod.price_for("vendor-x")


def test_model_price_rejects_negative():
    with pytest.raises(ValueError):
        ModelPrice(-1.0, 0.0)


def test_estimate_request_cost_prices_the_worst_case():
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))  # $1 / 1k tokens
    req = LLMRequest(model="vendor-x", prompt="p" * 30, max_tokens=100)
    est = cost_mod.estimate_request_cost(req)
    assert est.max_completion_tokens == 100
    assert est.usd == pytest.approx((est.prompt_tokens + 100) / 1000.0)


def test_guard_default_budget_refuses_any_paid_call():
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))
    guard = CostGuard()  # max_usd == 0
    req = LLMRequest(model="vendor-x", prompt="hello", max_tokens=50)
    est = cost_mod.estimate_request_cost(req)
    with pytest.raises(CostLimitExceeded):
        guard.reserve(est)
    assert guard.spent_usd == 0.0


def test_guard_admits_within_budget_and_settles_actuals():
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))
    guard = CostGuard(max_usd=10.0)
    est = cost_mod.estimate_request_cost(LLMRequest(model="vendor-x", prompt="hi", max_tokens=10))
    guard.reserve(est)  # does not raise, does not spend
    assert guard.spent_usd == 0.0
    spent = guard.settle("vendor-x", TokenUsage(100, 50))
    assert spent == pytest.approx(0.15)
    assert guard.spent_usd == pytest.approx(0.15)
    assert guard.calls == 1


def test_guard_records_overshoot_then_refuses_the_next_call():
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))
    guard = CostGuard(max_usd=0.10)
    guard.settle("vendor-x", TokenUsage(1000, 0))  # $1.00, over the $0.10 budget
    assert guard.spent_usd == pytest.approx(1.0)
    assert guard.remaining_usd() == 0.0  # never negative
    est = cost_mod.estimate_request_cost(LLMRequest(model="vendor-x", prompt="x", max_tokens=1))
    with pytest.raises(CostLimitExceeded):
        guard.reserve(est)


# ---------------------------------------------------------------------------
# cache.py — pay for a request at most once
# ---------------------------------------------------------------------------


def _sample_response(text: str = "answer") -> LLMResponse:
    return LLMResponse(text=text, model=MOCK_MODEL, adapter="mock", usage=TokenUsage(5, 3))


def test_cache_miss_then_hit_is_free_and_marked():
    cache = ResponseCache()
    req = LLMRequest(model=MOCK_MODEL, prompt="p")
    assert cache.get(req) is None
    cache.put(req, _sample_response())
    hit = cache.get(req)
    assert hit is not None
    assert hit.cached is True
    assert hit.cost_usd == 0.0
    assert hit.text == "answer"


def test_cache_refuses_dry_run_response():
    cache = ResponseCache()
    req = LLMRequest(model=MOCK_MODEL, prompt="p")
    dry = LLMResponse(text="", model=MOCK_MODEL, adapter="api", dry_run=True, estimated_usd=0.0)
    with pytest.raises(ValueError):
        cache.put(req, dry)


def test_disk_cache_round_trips_and_detects_tampering(tmp_path):
    directory = tmp_path / "cache"
    req = LLMRequest(model=MOCK_MODEL, prompt="p")
    ResponseCache(directory).put(req, _sample_response())
    # a fresh instance reads the file from disk
    fresh = ResponseCache(directory)
    hit = fresh.get(req)
    assert hit is not None and hit.cached and hit.cost_usd == 0.0
    # the file is a well-formed cache entry
    entry = next(directory.glob("*.json"))
    assert CACHE_FORMAT in entry.read_text()
    # a fingerprint that no longer matches the body is a miss, not an answer
    tampered = entry.read_text().replace(req.fingerprint(), "0" * 64)
    entry.write_text(tampered)
    assert ResponseCache(directory).get(req) is None


def test_disk_cache_corrupt_file_is_a_miss_not_an_error(tmp_path):
    directory = tmp_path / "cache"
    req = LLMRequest(model=MOCK_MODEL, prompt="p")
    ResponseCache(directory).put(req, _sample_response())
    next(directory.glob("*.json")).write_text("{ not json")
    assert ResponseCache(directory).get(req) is None  # recovers by refetching, never raises


# ---------------------------------------------------------------------------
# mock_llm.py
# ---------------------------------------------------------------------------


def test_mock_default_returns_empty_extraction_and_is_free():
    mock = MockLLMAdapter()
    assert mock.spends_money is False
    req = LLMRequest(model=MOCK_MODEL, prompt="anything")
    r1 = mock.complete(req)
    r2 = mock.complete(req)
    assert r1.text == r2.text  # deterministic
    assert r1.cost_usd == 0.0
    assert '"metrics": []' in r1.text
    assert mock.calls == 2


def test_mock_returning_answers_with_fixed_text():
    mock = MockLLMAdapter.returning('{"expected_value": 1.0}')
    assert mock.complete(LLMRequest(model=MOCK_MODEL, prompt="p")).text == '{"expected_value": 1.0}'


# ---------------------------------------------------------------------------
# recorded_llm.py
# ---------------------------------------------------------------------------


def test_recorded_adapter_replays_and_misses_loudly():
    adapter = RecordedLLMAdapter.from_file()
    assert adapter.spends_money is False
    assert set(adapter.labels) == set(RECORDED_SCORES)
    # a request that matches no recording raises, never falls back to a live call
    with pytest.raises(RecordingNotFound):
        adapter.complete(LLMRequest(model=RECORDED_MODEL, prompt="unrecorded prompt"))


def test_recorded_rejects_ambiguous_recordings():
    req = LLMRequest(model=RECORDED_MODEL, prompt="p")
    dup = Recording(label="a", request=req, text="{}", usage=TokenUsage())
    dup2 = Recording(label="b", request=req, text="{}", usage=TokenUsage())
    with pytest.raises(RecordingsError):
        RecordedLLMAdapter([dup, dup2])


def test_recordings_round_trip_is_byte_stable():
    recs = read_recordings(default_recordings_path())
    once = render_recordings(recs)
    twice = render_recordings(read_recordings(default_recordings_path()))
    assert once == twice


def test_read_recordings_rejects_wrong_format(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"format": "not-ours", "recordings": []}')
    with pytest.raises(RecordingsError):
        read_recordings(bad)


# ---------------------------------------------------------------------------
# api_stub.py — the four gates
# ---------------------------------------------------------------------------


def test_api_stub_is_the_only_paid_adapter_and_ships_disabled():
    paid = [name for name, cls in registry().items() if cls.spends_money]
    assert paid == ["api"]  # exactly one, and it is the api stub
    api = build_adapter("api", model="unpriced-model")
    assert isinstance(api, ApiAdapterStub)
    assert api.enabled is False
    assert api.dry_run is True
    assert api.transport is None
    assert api.guard.max_usd == 0.0


def test_api_unpriced_model_cannot_be_called_at_all():
    api = build_adapter("api", model="unpriced-model")
    with pytest.raises(UnknownModelPrice):
        api.complete(LLMRequest(model="unpriced-model", prompt="p"))


def test_api_dry_run_prices_without_spending():
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))
    api = ApiAdapterStub("vendor-x")  # dry_run default True, enabled default False
    r = api.complete(LLMRequest(model="vendor-x", prompt="hello", max_tokens=20))
    assert r.dry_run is True
    assert r.text == ""
    assert r.estimated_usd is not None and r.estimated_usd > 0.0
    assert api.guard.spent_usd == 0.0


def test_api_dry_run_over_cache_hit_estimates_zero():
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))
    cache = ResponseCache()
    req = LLMRequest(model="vendor-x", prompt="hello")
    cached_resp = LLMResponse(
        text="cached", model="vendor-x", adapter="api", usage=TokenUsage(1, 1)
    )
    cache.put(req, cached_resp)
    api = ApiAdapterStub("vendor-x", cache=cache)
    r = api.complete(req)
    assert r.dry_run is True and r.cached is True
    assert r.estimated_usd == 0.0  # a hit would not make a live call


@pytest.mark.parametrize(
    "enabled,env",
    [(False, {OPT_IN_ENV: OPT_IN_VALUE}), (True, {}), (True, {OPT_IN_ENV: "true"})],
)
def test_api_refuses_live_call_unless_both_opt_in_gates_open(enabled, env):
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))
    transport = CountingTransport()
    api = ApiAdapterStub(
        "vendor-x", enabled=enabled, dry_run=False, guard=CostGuard(max_usd=10.0),
        transport=transport, env=env,
    )
    with pytest.raises(PaidAPIDisabled):
        api.complete(LLMRequest(model="vendor-x", prompt="p"))
    assert transport.calls == 0  # nothing was sent


def test_api_cost_guard_stops_the_call_before_the_transport():
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))
    transport = CountingTransport()
    api = ApiAdapterStub(
        "vendor-x", enabled=True, dry_run=False, guard=CostGuard(max_usd=0.0),
        transport=transport, env={OPT_IN_ENV: OPT_IN_VALUE},
    )
    with pytest.raises(CostLimitExceeded):
        api.complete(LLMRequest(model="vendor-x", prompt="p", max_tokens=100))
    assert transport.calls == 0


def test_api_all_gates_open_but_no_transport_still_cannot_call():
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))
    api = ApiAdapterStub(
        "vendor-x", enabled=True, dry_run=False, guard=CostGuard(max_usd=10.0),
        transport=None, env={OPT_IN_ENV: OPT_IN_VALUE},
    )
    with pytest.raises(NoTransportConfigured):
        api.complete(LLMRequest(model="vendor-x", prompt="p"))


def test_api_full_opt_in_makes_the_call_settles_cost_and_caches():
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))
    transport = CountingTransport(text="live-answer", usage=TokenUsage(100, 50))
    cache = ResponseCache()
    api = ApiAdapterStub(
        "vendor-x", enabled=True, dry_run=False, guard=CostGuard(max_usd=10.0),
        transport=transport, cache=cache, env={OPT_IN_ENV: OPT_IN_VALUE},
    )
    req = LLMRequest(model="vendor-x", prompt="p")
    r = api.complete(req)
    assert transport.calls == 1
    assert r.text == "live-answer"
    assert r.cost_usd == pytest.approx(0.15)
    assert api.guard.spent_usd == pytest.approx(0.15)
    # the second call is served free from cache; the transport is not reached again
    r2 = api.complete(req)
    assert transport.calls == 1
    assert r2.cached is True and r2.cost_usd == 0.0


def test_paid_api_enabled_requires_exact_opt_in_value():
    assert paid_api_enabled({OPT_IN_ENV: "1"}) is True
    for value in ("true", "yes", "1 ", "", "0"):
        assert paid_api_enabled({OPT_IN_ENV: value}) is False
    assert paid_api_enabled({}) is False


# ---------------------------------------------------------------------------
# package: registry, build_adapter, and the no-network property
# ---------------------------------------------------------------------------


def test_adapter_names_and_registry_agree():
    assert set(ADAPTER_NAMES) == set(registry())
    for name, cls in registry().items():
        assert cls.name == name  # registry maps a name to its class without constructing


def test_build_adapter_rejects_unknown_name():
    with pytest.raises(ValueError):
        build_adapter("nope")


def test_no_adapter_module_imports_an_http_client():
    package_dir = Path(fixtures_mod.__file__).parent
    offenders = []
    for module in sorted(package_dir.glob("*.py")):
        source = module.read_text(encoding="utf-8")
        for client in HTTP_CLIENTS:
            if f"import {client}" in source:
                offenders.append((module.name, client))
    assert offenders == []


def test_pyproject_declares_no_http_client():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    deps_section = pyproject.split("dependencies")[1].split("[")[0].lower()
    for client in ("requests", "httpx", "aiohttp", "urllib3"):
        assert client not in deps_section


# ---------------------------------------------------------------------------
# llm_extraction.py — the same contract, a different method
# ---------------------------------------------------------------------------


def test_build_request_is_deterministic_and_zero_temperature():
    task = loader.load_task(loader.index_tasks(TASKS_DIR)["accuracy_improvement"])
    a = build_request(task.input_claim, task.bundle, model=RECORDED_MODEL)
    b = build_request(task.input_claim, task.bundle, model=RECORDED_MODEL)
    assert a.fingerprint() == b.fingerprint()
    assert a.temperature == 0.0


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
    ],
)
def test_strip_code_fence(text, expected):
    assert strip_code_fence(text) == expected


def test_parse_valid_extraction_response():
    parsed = parse_extraction_response('{"expected_value": 78.0, "comparison_operator": ">"}')
    assert isinstance(parsed, ExtractionResponse)
    assert parsed.expected_value == 78.0
    assert "expected_value" in parsed.populated_fields()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json at all",
        "[1, 2, 3]",
        '{"expected_value": 1.0, "confidence": 0.9}',  # unknown key
        '{"comparison_operator": "much greater"}',  # bad operator
    ],
)
def test_parse_rejects_malformed_responses(text):
    with pytest.raises(ExtractionResponseError):
        parse_extraction_response(text)


def test_llm_extractor_with_mock_yields_empty_claim():
    task = loader.load_task(loader.index_tasks(TASKS_DIR)["accuracy_improvement"])
    result = LLMClaimExtractor(MockLLMAdapter()).extract(task.input_claim, task.bundle)
    assert result.claim.expected_value is None
    assert result.claim.metrics == []
    assert any("adapter=mock" in rule for rule in result.rules_fired)


def test_llm_extractor_refuses_a_dry_run_response():
    cost_mod.register_price("vendor-x", ModelPrice(1.0, 1.0))
    api = ApiAdapterStub("vendor-x")  # dry-run by default
    task = loader.load_task(loader.index_tasks(TASKS_DIR)["accuracy_improvement"])
    with pytest.raises(ExtractionResponseError):
        LLMClaimExtractor(api, model="vendor-x").extract(task.input_claim, task.bundle)


# ---------------------------------------------------------------------------
# fixtures.py + the committed recordings, end to end
# ---------------------------------------------------------------------------


def test_committed_recordings_are_current():
    # The byte-stability guarantee: a prompt-template or task edit would make this fail.
    assert fixtures_mod.check() == []


@pytest.mark.parametrize("label,expected", RECORDED_SCORES.items())
def test_recorded_adapter_scores_match_gold(label, expected):
    adapter = RecordedLLMAdapter.from_file()
    extractor = LLMClaimExtractor(adapter)
    task = loader.load_task(loader.index_tasks(TASKS_DIR)[label])
    result = extractor.extract(task.input_claim, task.bundle)
    score = score_extraction(result.claim, task.spec.expected.claim)
    assert score.n_correct == expected


def test_recorded_aggregate_is_thirty_of_thirty_two():
    # The deliberate 6/8 on dataset_mean is what proves the scorer is connected.
    assert sum(RECORDED_SCORES.values()) == 30
    assert len(RECORDED_SCORES) * 8 == 32


# ---------------------------------------------------------------------------
# CLI wiring: extract-claims --extractor
# ---------------------------------------------------------------------------


def test_build_extractor_returns_the_right_engine():
    assert build_extractor("rule").__class__.__name__ == "RuleBasedClaimExtractor"
    assert isinstance(build_extractor("recorded"), LLMClaimExtractor)
    assert isinstance(build_extractor("mock"), LLMClaimExtractor)
    with pytest.raises(ValueError):
        build_extractor("bogus")


def test_extract_claims_recorded_succeeds_and_unrecorded_fails(capsys):
    idx = loader.index_tasks(TASKS_DIR)
    ok = extraction_mod.extract_and_report(idx["accuracy_improvement"], extractor="recorded")
    assert ok == 0
    missing = extraction_mod.extract_and_report(idx["contradicted_f1"], extractor="recorded")
    assert missing == 1  # no recording; refused, not fabricated


def test_extract_claims_mock_runs_offline(capsys):
    idx = loader.index_tasks(TASKS_DIR)
    assert extraction_mod.extract_and_report(idx["accuracy_improvement"], extractor="mock") == 0
