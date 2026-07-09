# LIMITATIONS

The canonical list of what this system does not do, cannot claim, and will not
become. Being explicit about limits is part of the auditability goal, not an
apology for it — a tool that hides its limits cannot be audited.

Every limitation below is either enforced by a test, visible in a fixture, or a
stated non-goal. Where a limitation has a name in the code, that name is given.

---

## 1. Scope of a verdict

### Verdicts are relative to the supplied artifacts

Every support label and reproduction status is **relative to the bundle it was
computed over**. `supported` means *the artifacts in this task back this claim,
under these checks, at these tolerances.* It does not mean the claim is true in the
world, that the paper is sound, or that the result replicates. There is no
universal scientific-truth judgement in this repository, and its absence is
deliberate (`docs/SAFETY.md`, "Auditability, not authority").

### `confidence` is not a probability

`VerificationResult.confidence` is the share of a claim's checks that reached a
pass/fail verdict — **decidedness**. It is not calibrated against anything, and it
does not estimate the chance that the label is correct. Producing a calibrated number
would need labelled data this project does not have. A claim whose only check is
`inconclusive` scores `0.00`, however confident its label sounds.

### Scoring is per-claim

Each task carries exactly one claim, and each claim is scored independently. The
pipeline never asks whether two claims in one bundle contradict each other, and there
is no cross-claim or cross-document consistency check. `checks/consistency.py` is
about claim-vs-passage consistency, not claim-vs-claim.

## 2. The methods are heuristics, and are labelled as such

### Extraction is rule-based and deliberately simple

The default extractor is regexes plus small **closed lexicons** (metric names, known
dataset names, role entities). It targets numeric and comparison claims in clean text
and will miss or mis-parse complex phrasing. Its lexicons were chosen with the
committed fixtures in view, so `11/11` on `datasets` means *"every dataset mention in
these eleven fixtures was found"* — not that dataset extraction is solved. It is a
transparent baseline, not a state-of-the-art NLP system. Every rule and its limits are
in `docs/EXTRACTION.md`.

`normalized_claim` is the extractor's own canonical notation. It is **not** scored
against gold, because it is not a match target.

### Passage linking is bag-of-words

Retrieval is verbatim containment, then token overlap. It has no model of morphology,
synonymy, or negation. Two consequences are visible in the committed fixtures:

- `corpus` does not match `corpora`, so `negated_training_data`'s distractor loses most
  of its overlap to a suffix.
- `synthetic_data_passage`'s winning passage scores **0.211**, and the margin over its
  distractor comes from the distractor being *completely* unrelated (0.000). A harder
  distractor sharing vocabulary without asserting the claim would not be separated.

The linker retrieves; it does not judge support. That is why `evidence_presence` is a
separate check.

### The evidence check cannot confirm a paraphrase

Deciding whether a passage *asserts* a claim is done lexically: verbatim containment,
or every content token present with matching polarity. So a passage that supports the
claim in different words is reported **`inconclusive`**, not `pass`. One of the eleven
committed fixtures lands there, and that is the correct answer for this method rather
than a bug — the alternative is to guess.

Three narrower limits of the same rule:

- Negation cues are a **closed set of function words**, so contractions (`doesn't`) are
  not detected.
- Verbatim containment is not polarity-checked.
- Polarity is read from the passage's **best-matching sentence**, so a negation living
  in a different sentence than the claim's tokens would be missed. No fixture covers
  that case.

See `docs/CHECKS.md`.

### Reproduction is lightweight

"Reproduction" means recomputing a statistic, or running a tiny script and comparing to
an expected value within tolerance. It does not attempt environment reconstruction,
dependency resolution, or long-running training.

- The sandbox copies **only the script**, so a fixture must embed its own data. Staging
  declared inputs is untouched work, not a hidden feature.
- **Nothing pins the interpreter.** The script runs under whichever Python invoked it,
  and the trace does not record the version, so two machines can disagree.
- Captured output is recorded verbatim apart from the sandbox path, so a *failing*
  script's traceback embeds the host's stdlib paths. Traces of failing runs are
  reproducible per machine, not across machines. Redacting the traceback would be worse.

### Two failure-mode mappings lose information, deliberately

- A `comparison` check failing (the asserted *relation* does not hold) is recorded as
  `numeric_out_of_tolerance`.
- A `code_execution` check failing (the script ran but printed the wrong text) is
  recorded as `other`, since the declared expectation may be arbitrary text and the
  script executed fine.

Both are named in `docs/SCORING.md` rather than hidden.

## 3. The sandbox is not a security boundary

> The code-execution layer runs **tiny, trusted fixture scripts** committed to this
> repository.

It copies the script to a fresh temp directory, scrubs the environment down to an
allowlist, closes stdin, applies POSIX resource limits before `exec`, kills the whole
process group on timeout, and installs an in-process guard that denies and **records**
`socket` calls. Every one of those is a **reproducibility** control — they exist so that
a number a script printed came from the script rather than from the machine.

**None of them is isolation.** There is no namespace, no seccomp filter, no chroot, no
user separation. It is controlled fixture execution for reproducibility, **not** a
production-grade or untrusted-code sandbox. Do not run untrusted code through it.

### The network guard is Python-level

It patches `socket` inside the child's interpreter, so it covers the script, everything
the script imports, and — via `PYTHONPATH` — any *Python* subprocess the script spawns,
whose attempts land in the same log. It does **not** cover `ctypes`, a raw syscall, a
reference captured before it installed, or a **non-Python** subprocess: `curl` has its
own interpreter. No environment variable fixes that; a network namespace or a seccomp
filter would, and this layer provides neither.

The guard catches accidental network use by trusted code, and records it. **It does not
contain adversaries.**

## 4. The fixtures are a regression harness, not a benchmark

Eleven hand-authored synthetic tasks, tiny by design, whose gold outcomes were written
alongside the rules that score them.

- The locator conventions and the table row rule were written with the two committed
  table fixtures in view, so a perfect **21/21** on evidence linking is a *consistency
  check* — the linker reproduces the hand-authored provenance exactly and invents
  nothing — not evidence that retrieval is solved.
- **10/11** support labels is a regression-harness number. It does not mean scientific
  claim verification is 91% solved.
- The four fixtures added in Milestone 8 were authored *after* the rule table was frozen
  and needed no rule change, which is mildly better evidence. But the same agent wrote
  both, with the rules in view, so **it is not a held-out set in any meaningful sense.**

`docs/PAPER_PATH.md` states what would have to change before any of these numbers were a
claim about the world.

### The suite gates on regressions, not on correctness

`claimverifier run-suite` exiting 0 means: *"this commit did not make the pipeline assert
something its own fixtures deny, and did not change the set of claims it declines to
decide."* It does not mean the verdicts are right, and it certainly does not mean the
claims are true.

Passing `--no-execute` **disables the gate entirely**, because the gold outcomes assume
the fixture scripts ran.

## 5. What is built but unexercised, and what is not built

### `figure_recompute` is named, not implemented

`CheckType.FIGURE_RECOMPUTE` exists, `evidence/figures.py` links figures by data series,
and the extractor detects "Figure N" mentions. **No check recomputes a figure, and no
committed fixture has one.** The linking module is unit-tested against synthetic figures
only. This is recorded in `docs/CHECKS.md` under "Not implemented" rather than stubbed
into something that looks live.

### Four vocabulary values are unreachable end to end

They are pinned by unit tests instead of by a fixture:

| Value | Why no fixture reaches it |
| --- | --- |
| `not_checked` | the check runner always emits an `evidence_presence` check |
| `failed_missing_data` | a task naming an absent fixture file fails to **load** |
| `failed_missing_code` | same |
| `not_attempted` | reachable only via `--no-execute` |

### The trace records what was computed, not how it was invoked

A schema-1.3 trace carries none of the four controls (`execute`, `use_declared_source`,
`abs_tol`, `rel_tol`). `export --format episodes` recovers `execute` from the one artifact
that does record it — a suite `summary.json` — and **refuses** when the operator's declared
`--no-execute` disagrees with it. The other three are taken from the operator's flags.

A wrongly declared control does not silently lie: replaying the episode reports `drifted`
and names the field. But it is an assumption. Removing it means recording the controls in
the trace (a `scoring.controls` event, schema 1.4) — a schema change, which belongs to the
milestone that needs it.

### The export contracts were not validated against any consumer

The five `claimverifier export` formats are shaped for a consumer **role** — a code-agent
runtime, an evidence store, a benchmark harness, an observability sink, a replay bench.
**No external schema was consulted.** None of those systems was read, imported, or run, so
nothing here is a measurement of compatibility with any of them, and the word is not used.
What is claimed, and tested, is *containment*: every module under `integrations/` imports
nothing but the standard library, `pydantic`, and this project.

## 6. A report describes the run, not the benchmark

`claimverifier report` renders a claim's verdict and the evidence behind it. It **never
prints the task's gold outcome**, and it cannot: the report is a function of the JSONL
trace, and a trace records what the pipeline concluded, not what it should have concluded.
Gold agreement lives in `summary.csv` and `summary.json` beside the traces, where a wrong
verdict and an honest refusal to decide are counted apart. A report that scored itself
would be answering a different question.

Two smaller limits of the renderer, both stated rather than papered over:

- Markdown **table cells** escape `|` and collapse newlines, because an unescaped pipe
  silently eats a column. **Prose is not escaped**, so a claim sentence containing `*` or
  `_` renders with emphasis. That is a formatting artefact, not a correctness one —
  mangling `p < 0.05` to defend against it would cost more than it buys.
- No committed fixture is refuted by its table *and* undecidable from its text at once, so
  the report's multi-cause block is exercised by a unit test rather than by a real run.

## 7. No paid model in the loop, by construction

The default path is fully deterministic, offline, and free. Optional LLM adapters exist but
are **disabled**, and the paid path is inert by construction rather than by configuration:
`ApiAdapterStub` is the only adapter capable of a paid call, and `build_adapter("api")`
returns it disabled, in dry-run, with a `$0.00` cost guard and **no transport**.

A live call requires four independent acts — flip `enabled`, set `SCV_ENABLE_PAID_API=1`,
register a price for the model (the repo ships none), and inject an HTTP transport (the repo
ships none, and a test asserts no module under `adapters/` and no declared dependency imports
one).

The recorded adapter's `30/32` measures exactly one thing: that a request is fingerprinted,
replayed, parsed, and scored faithfully. It says **nothing at all** about any model's ability
to extract a claim. No API was called and no language model produced those responses; the
model name `recorded-fixture-v1` is fictitious so the fixture cannot imply otherwise.

## 8. Permanent non-goals

These are not gaps to be filled later. They are the boundary of the project
(`docs/SAFETY.md`):

- Clinical decision-making or patient-specific advice.
- Medical or treatment recommendations.
- Wet-lab protocol design or optimization.
- Dual-use biological instructions.
- Real patient data; private or real papers.
- Real credential handling.
- A production-grade untrusted-code sandbox.
- A universal oracle of scientific truth.

## See also

- `docs/SAFETY.md` — the scope contract and why it is permanent
- `docs/METHODOLOGY.md` — the design commitments these limits follow from
- `docs/RESULTS.md` — every measured number, with the command beside it
- `docs/PAPER_PATH.md` — what would have to be true to publish any of this
