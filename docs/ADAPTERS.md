# ADAPTERS — optional LLM adapters (Milestone 10)

`docs/PLAN.md` §8 fixes the policy: version 1 of this project is **non-LLM or mock-LLM**.
The rule-based extractor (Milestone 3) is the baseline that runs, and it is transparent —
every field it populates names the rule that produced it. These adapters exist so that a
*comparison* is possible and a paid path is *specified*, **not** so that a model is in the
loop. Nothing in the default path constructs an adapter.

## The contract

Every adapter speaks three types (`adapters/base.py`):

- `LLMRequest` — one call, fully described by its content: `model`, `system`, `prompt`,
  `temperature`, `max_tokens`. Its `fingerprint()` is the SHA-256 of the canonical JSON of
  those five fields. It is the cache key, the recording key, and the trace's handle on the
  call. Two requests that differ in any field are different requests.
- `LLMResponse` — what an adapter returns. **Estimated money and actual money never share a
  field:** `cost_usd` is money a call *actually* spent (`0.0` for a mock, a replay, a cache
  hit, and a dry run); `estimated_usd` is populated *only* on a dry run. The type enforces
  it: a dry-run response may not carry content or a cost, and a cached response may not carry
  a cost.
- `TokenUsage` — non-negative prompt/completion counts.

## The three adapters, one interface

| Name | Class | `spends_money` | What it does |
| --- | --- | --- | --- |
| `mock` | `MockLLMAdapter` | `False` | Deterministic pure function of the request. Returns an **empty** extraction by default. For tests. |
| `recorded` | `RecordedLLMAdapter` | `False` | Replays committed synthetic fixtures by request fingerprint. A miss **raises**; it never falls back to a live call. |
| `api` | `ApiAdapterStub` | `True` | The paid interface. Disabled, dry-run, cost-guarded, and shipped with no transport. |

`spends_money` is a class-level declaration so it can be *checked*, not asserted:
`tests/test_adapters.py` enumerates the registry and pins that **exactly one** adapter can
cause a paid call, and that `build_adapter("api")` returns it disabled.

## Why the default path is free — by construction, not configuration

`CLAUDE.md` names five things any paid-API mode must have, and all five are present:

1. **dry-run** — `ApiAdapterStub(dry_run=True)` is the default; it prices a call and returns
   content-free.
2. **response cache** — `adapters/cache.py`; a hit is free and says so, and dry runs are
   never cached.
3. **token/cost estimator** — `adapters/cost.py`; a deliberately over-counting heuristic
   (chars ÷ 3 + framing), so the guard reserves an **upper bound**. It is a heuristic, not a
   tokenizer, and is labelled as one.
4. **hard max-cost guard** — `CostGuard`; reserves the worst case *before* the call, settles
   the actual *after*. Default budget `$0.00`.
5. **explicit opt-in** — both an `enabled=True` flag *and* `SCV_ENABLE_PAID_API=1` in the
   environment.

But none of those five is what makes the default path free. **What makes it free is that
there is nothing to call:** `transport` is `None`, `pyproject.toml` declares no HTTP client,
and no module under `adapters/` imports one — a property a test asserts by reading the
source. A caller who genuinely wants to spend money must inject a transport
(`(LLMRequest) -> (text, TokenUsage)`) themselves.

### The four gates (checked in order)

A request reaches a transport only past all four; the default configuration fails all four:

1. **Opt-in, in code** — `enabled=False` → `PaidAPIDisabled`.
2. **Opt-in, in the environment** — `SCV_ENABLE_PAID_API=1` must also be set → `PaidAPIDisabled`.
3. **The cost guard** — `reserve` refuses if the worst case exceeds the budget → `CostLimitExceeded`.
4. **The transport** — `None` → `NoTransportConfigured`.

A fifth gate sits before all of them: an **unpriced model cannot be costed**, so `price_for`
raises `UnknownModelPrice` and the call ends before any gate is consulted. The repo registers
no vendor prices; a stale committed price is worse than none because it looks authoritative
while under-reserving.

## Extraction through an adapter

`claims/llm_extraction.py` implements the same call as the rule-based extractor —
`extract(claim, bundle) -> Extraction` — so the two are swappable and scored against the same
gold, field for field. The model fills exactly the eight scored fields as JSON; the
`normalized_claim` and the artifact references are computed by deterministic code, not the
model, and `rules_fired` records which parts came from where. The response is parsed
strictly (unknown key → parse failure); the one tolerated deviation is a Markdown code fence.
A dry-run response raises rather than being read as "the model extracted nothing".

```bash
# rule-based (default, the transparent baseline)
claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml

# through the recorded adapter (offline, free); scored against the same gold
claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml --extractor recorded

# the mock adapter returns an empty extraction on purpose
claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml --extractor mock
```

`api` is intentionally **not** an extractor: in its default configuration it returns no
content, and `LLMClaimExtractor` refuses a dry-run response rather than parsing `""`.

## Recordings

The replayed responses are hand-authored synthetic fixtures under
`data/fixtures/llm/` — see that directory's `README.md` for provenance. The file is a
**derived** artifact regenerated from the prompt template and tasks; a template edit makes
every recording miss, and `scripts/06_record_llm_fixtures.py --check` (which the tests run)
fails the build when the committed file has drifted.

## Honest limitations

- The token estimator is a heuristic upper bound, not a real tokenizer. It bounds the *next*
  call; it cannot un-spend a call already made if a vendor's true tokenization ever exceeded
  the bound. `settle` records the overspend faithfully and the following `reserve` refuses.
- The recorded results measure the replay/parse/score harness, not any model.
- No paid provider is integrated. `ApiAdapterStub` is an interface with guards, not a client.
