# PAPER_PATH

What would have to be true before any of this became a claim about the world rather
than a claim about this repository.

This document exists because the repo's numbers are easy to misread. `10/11 support
labels`, `21/21 evidence links`, `11/11 replays` all look like results. They are
**properties of a regression harness over eleven hand-authored fixtures**, and the gap
between that and a publishable finding is the subject of this file.

Nothing here requires paid APIs or GPUs. Nothing here would relax the safety scope in
`docs/SAFETY.md`.

---

## 1. What this repository is, honestly

A **systems and auditability contribution**, not an NLP result.

The defensible claim is about *architecture*, and it is small:

> A claim-verification pipeline can be staged so that each stage is structurally
> incapable of doing the next stage's job; the resulting trace is a complete record of
> the verdict — provably, in the sense that the report is a pure function of the trace
> and a test asserts the round trip is exact; and the regression gate can be made to
> distinguish an assertion that is wrong from a refusal to assert, so that a change
> trading honesty for accuracy cannot land quietly.

Everything the repo measures is evidence for *that*, and for nothing else:

| Number | What it is evidence for | What it is **not** evidence for |
| --- | --- | --- |
| 21/21 evidence links, 0 spurious | the linker reproduces hand-authored provenance and invents nothing | that retrieval works on real papers |
| 10/11 support labels, **0 wrong verdicts** | the rule table is coherent and never asserts what gold denies | that claim verification is 91% solved |
| round trip exact on 11/11 | the trace is a complete record of the verdict | anything about verdict correctness |
| 11/11 replays, byte-identical traces | the pipeline is deterministic | that the verdicts generalize |
| 30/32 recorded-adapter fields | a request is fingerprinted, replayed, parsed, scored faithfully | **any** model's extraction ability |

The last row is the sharpest: no API was called, and no language model produced those
responses. The model name `recorded-fixture-v1` is fictitious precisely so the fixture
cannot imply otherwise.

## 2. Why the current evidence is weak, stated precisely

Three independent reasons, none of which is fixed by adding more fixtures of the same
kind.

**The fixtures and the rules were co-authored.** The extractor's lexicons, the linker's
locator conventions, and the scoring rule table were all written with the committed
fixtures in view. A perfect score under those conditions measures internal consistency.

**The fixtures are synthetic and tiny.** Passages are one or two sentences. Tables have
two rows. The CSV has twelve values. Real papers have hedged claims, claims split across
sentences, claims whose numbers appear only in an appendix, and tables whose captions
carry the conditions the claim omits.

**Eleven is not a sample.** The four fixtures added in Milestone 8 are the closest thing
to held-out data — authored *after* the rule table was frozen, landing on their gold
outcomes with no rule change. That is mildly better evidence. It is not a held-out set:
the same agent wrote both, with the rules in view.

## 3. The three studies that would be needed

In dependency order. Each is CPU-only and free; none needs a model.

### Study 1 — A real, annotated claim set

The blocking prerequisite for every downstream number.

- **Source**: claims from open-access papers with released artifacts (tables, CSVs,
  scripts). Not private papers, not paywalled PDFs. See `docs/SAFETY.md`.
- **Size**: enough that per-label counts are not single digits. Given six support labels
  and thirteen failure modes, that is *hundreds* of claims, not dozens.
- **Annotation**: at least two independent annotators per claim, with **inter-annotator
  agreement reported**. Without it, "gold" is one person's reading, and the pipeline's
  10/11 is measured against an unmeasured ruler.
- **The hard part is not the annotation.** It is deciding what `supported` means when the
  paper's table and its abstract disagree — which is exactly the `contradicted_f1`
  situation, and exactly why this system refuses to collapse the channels. A real corpus
  will be full of them, and the annotation guidelines are a research contribution in
  their own right.

Until this exists, every accuracy-shaped number in this repo is a self-report.

### Study 2 — Baselines the rule-based system must be measured against

The current extractor and linker have **no baseline**. `10/11` is unanchored: a system
that labelled everything `unverifiable_from_artifacts` would score 1/11 with *zero* wrong
verdicts, which is the metric this repo declares primary. That is a real weakness of the
metric, and it must be closed by reporting both numbers together, against baselines:

| Baseline | Purpose |
| --- | --- |
| always-`unverifiable_from_artifacts` | the degenerate floor the primary metric alone would reward |
| always-`supported` | the degenerate ceiling accuracy alone would reward on a supportive corpus |
| majority-label | the trivial prior |
| the rule-based pipeline | this repo |
| an LLM extractor, cost-guarded, behind the existing adapter | the interesting comparison |

The `ApiAdapterStub` and `RecordedLLMAdapter` exist so that last row can be run *without*
the paid path ever becoming the default, and so its cost is bounded and its responses are
cached and replayable.

### Study 3 — The ablation the architecture actually predicts

The design commitment in `docs/METHODOLOGY.md` §3–4 makes a falsifiable prediction:
**separating check `status` from claim `signal` prevents a specific class of error.**

Test it by ablating the separation — map `fail` → `refutes` unconditionally — and measure
the induced wrong verdicts. The prediction is that `evidence_presence` checks whose
passage never *mentions* the claim would flip from `undecided` to `refutes`, converting
honest refusals into confident contradictions. If that does not happen on a real corpus,
the central design claim of this repository is wrong and should be withdrawn.

That is the experiment worth running first, because it is the one that could *falsify* the
thing the repo is actually arguing.

## 4. The metric argument, which is the transferable part

The pipeline scores `10/11`. A version of it that guessed on its one honest refusal would
score `11/11`. Label accuracy — the metric a benchmark harness reaches for by default —
prefers the guesser.

So the exported `scv.benchmark` document **declares its metric**: `wrong_verdicts` (lower
is better) primary, `conservative_misses` (lower is better) secondary, and a note that says
*do not sum them*. `scv.metrics` emits a fixed key space of 40 metrics, of which only six
declare a direction; `checks_fail` is explicitly `neutral`, because a suite of contradicted
claims *should* produce failing checks.

The generalizable claim — and the one worth defending in a paper — is:

> For verification systems, an evaluation that cannot distinguish *asserting something
> false* from *declining to assert* will systematically select for models that guess.

This does not require a large corpus to state. It requires a corpus to *demonstrate*, and
Study 3 is the demonstration. §3's baseline table is the honest counterweight: a metric
that only punishes wrong verdicts is gameable by silence, so the pair must be reported
together, always.

## 5. Method work that would follow, in priority order

Deliberately modest. Each keeps the rule-based path as the interpretable floor.

1. **A stronger evidence check that does not lose the contradiction.** The measurable
   target is exact: move `synthetic_data_passage` from `inconclusive` to `pass` **without**
   moving `contradicted_f1`'s passage check off `pass`. Stemming and a synonym table are the
   obvious first attempt; both are transparent, and both are testable against that pair.
2. **`figure_recompute`.** `CheckType.FIGURE_RECOMPUTE` and `evidence/figures.py` exist;
   no check and no fixture do. Figures carry data series, never pixels, so this is a
   recomputation over a committed series — not a vision problem.
3. **Claim-level conditions.** The `10/11` on extraction's `conditions` field is the miss
   that matters: the extractor recovers `n = 12` but not `"synthetic data only"`. Semantic
   conditions are what make a claim `underspecified` rather than `supported`, and they are
   the field most likely to be wrong on real text.
4. **Cross-claim consistency.** Every claim is currently scored independently; the pipeline
   never asks whether two claims in one bundle contradict each other. A paper contradicting
   itself across sections is the most interesting object this tool could find, and it
   currently cannot.
5. **Distributional and seed-sensitivity checks.** A reported metric that holds only for one
   seed is a reproducibility failure the current `numeric_tolerance` check would call a pass.

## 6. Threats to validity, if this were written up today

- **Construct validity.** "Supported" is defined *relative to the supplied bundle*. A
  corpus builder chooses the bundle, and can therefore choose the verdict. Bundle
  construction must be pre-registered or adversarial.
- **The gold-standard problem.** Gold outcomes here were written by the same agent that
  wrote the rules. Study 1's inter-annotator agreement is the only fix.
- **The primary metric is gameable by silence.** Stated in §4; mitigated only by reporting
  `conservative_misses` alongside, never by summing.
- **Sandbox generalization.** Three stdlib-only scripts that embed their own data. The
  sandbox stages no declared inputs and pins no interpreter, so "reproduced" means less on
  real code than the word suggests.
- **Determinism is not correctness.** Eleven byte-identical replays prove the pipeline is a
  function. They say nothing about whether it is the right function.

## 7. What stays out, permanently

The safety boundaries are not roadmap items. They are the shape of the project
(`docs/SAFETY.md`):

- No clinical decision-making, medical advice, or treatment recommendations.
- No wet-lab protocol design or optimization.
- No dual-use biological instructions.
- No real patient data; no private or paywalled papers.
- No real credential handling.
- No claim to be a production untrusted-code sandbox.
- No universal oracle of scientific truth. A verdict is relative to the supplied
  artifacts, and that is not a limitation to be engineered away — it is the thesis.

## 8. The honest summary

This repository is a working, deterministic, auditable **instrument**, with an evaluation
protocol whose design is defensible and whose corpus is not yet real. The instrument is
finished enough to be pointed at something. The paper is the corpus, the baselines, and
the ablation in §3 — not the instrument.

Anyone reading the numbers in `docs/RESULTS.md` as evidence about scientific claim
verification has read them wrong, and `docs/LIMITATIONS.md` §4 says so in the same words.

## See also

- `docs/METHODOLOGY.md` — the design commitments a paper would have to defend
- `docs/LIMITATIONS.md` — what the system cannot do today
- `docs/RESULTS.md` — every number, and the sentence explaining how to read it
- `docs/REPRODUCIBILITY.md` — how to re-derive all of them offline
- `docs/SAFETY.md` — the permanent scope contract
