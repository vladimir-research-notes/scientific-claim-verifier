# EVIDENCE_LINKING — linking a claim to the artifacts that bear on it

Reference for the evidence linker introduced in **Milestone 4**. The orchestrator
lives in [`src/scientific_claim_verifier/claims/linking.py`](../src/scientific_claim_verifier/claims/linking.py);
the per-artifact channels live in
[`src/scientific_claim_verifier/evidence/`](../src/scientific_claim_verifier/evidence/)
(`passages.py`, `tables.py`, `datasets.py`, `code_refs.py`, `figures.py`).

The linker takes a **populated** claim (the output of the M3 extractor) plus an
`ArtifactBundle`, and emits an ordered list of `EvidenceLink` records — one
passage, plus any table cells/columns, dataset columns, code files, and figure
series the claim resolves to. Each link carries a **score**, a **locator**, and
the **named rule** that produced it.

## Retrieval, not judgement

A link says *"this is where to look"*. It never says *"this proves the claim"*.

- A passage can be linked with a high score and **contradict** the claim.
- A table column is linked *precisely because* no cell matches the claimed value —
  otherwise a `contradicted` verdict could never be reached.

Deciding whether linked evidence **asserts** a claim is the `evidence_presence`
check and the value checks (**Milestone 5**), and the support label is assigned by
scoring (**Milestone 7**). Keeping retrieval and judgement apart is what lets the
report show *supporting text* and *computed check* as separately auditable things.

## Asserted vs. discovered provenance

A task may declare `claim.source_passage` — the passage a human says the claim was
authored from. That is **asserted provenance**, not a retrieval result. Using it
makes passage linking trivially correct, so:

- the link is labelled `match=declared_source_passage`, never confused with a
  discovered one;
- the passage's **measured** overlap is recorded alongside, so an asserted-but-poor
  link is visible (`match=declared_source_passage; overlap=0.211; rank=1`);
- `EvidenceLinker(use_declared_source=False)` — the `--no-declared-source` CLI
  flag — runs the linker **blind**, and that is the setting under which its
  retrieval is worth measuring. The results below are the blind numbers.

## Scores

`EvidenceLink.score` is a **retrieval confidence** in `[0, 1]`:

| Match | Score |
| --- | --- |
| declared source passage, verbatim passage, resolved artifact id, located cell | `1.0` |
| keyword-matched passage | the Dice overlap |

It is **not** a probability that the claim is true. Locator granularity — cell vs.
column vs. whole artifact — is expressed by the `locator`, not by the score.

---

## The channels

### Passages — exact lookup, then a keyword-overlap baseline

Three channels, in decreasing order of certainty:

1. **Declared source** (above), score `1.0`.
2. **Exact text** — the claim's canonicalized text (lowercased, whitespace
   collapsed, trailing period dropped) appears verbatim inside a passage's
   canonicalized text. Score `1.0`. Canonicalization is what lets a claim on one
   line match a passage that YAML wrapped across three.
3. **Keyword overlap** — a bag-of-words baseline over content tokens, scored with
   the **Dice coefficient** `2·|C∩P| / (|C|+|P|)`.

Every passage in the bundle is scored and ranked; **exactly one** is linked (the
best), and the *full ranking stays in the trace and the report* so the runners-up
and their scores remain auditable.

**Why Dice** and not a containment score (`|C∩P| / |C|`): containment rewards a
passage merely for being long — an essay that happens to mention every claim token
would score a perfect `1.0`. Dice is symmetric, lies in `[0, 1]`, and penalizes
padding. The case where a long passage genuinely *states* the claim is already
handled by channel 2, so containment's advantage is covered.

**Tokenization.** Lowercase, then a token is a run of letters/digits optionally
continued through internal `.`, `_`, or `-`. So `SST-2`, `72.0`, `10-base`, and
`compute_accuracy.py` survive whole, while `90%` yields `90`. Closed-class function
words are then dropped. The stopword list deliberately **keeps** negation and
quantifiers (`no`, `not`, `only`, `all`) — they carry claim-relevant meaning.

**Ranking.** Best-first by `(score, method, overlap, passage_id)`. The
`passage_id` tie-break makes the ordering total, so the output is deterministic.

**Floor.** A passage scoring below `MIN_PASSAGE_SCORE = 0.05` is not linked at
all. This rejects passages with essentially no lexical overlap. It is **not** a
support threshold: a passage can clear it and still contradict the claim.

#### What this baseline cannot do

It is bag-of-words. It has **no model of negation, morphology, or synonymy**:

- *"the model is **not** trained on synthetic data"* scores identically to the
  assertion;
- `trained` does not match `training`, `corpus` does not match `corpora`;
- a paraphrase sharing no vocabulary scores `0.0`.

This is deliberate, and it is why `evidence_presence` exists as a separate check.
A stronger retriever (embeddings, or the M10 LLM adapter) can be dropped in behind
the same interface without touching anything downstream.

### Tables — the row rule

A table is linked only if one of its columns denotes one of the claim's metrics
(the header is canonicalized through *the extractor's own metric lexicon*, so
`F1 Score` and `f1` are the same metric in both places). Then:

> **A cell link is emitted only when the claim names the row.**

Consider *"The method reaches 90% accuracy"* against a table with `dev 90.0` and
`test 82.0`. The value `90.0` matches exactly one cell, so it is tempting to link
`row=dev,col=accuracy`. That would silently attribute the claim to a split the
claim never mentioned — **the underspecification would vanish into a
confident-looking locator.** Instead the linker emits `col=accuracy`, and the
claim stays visibly ambiguous over that column. That ambiguity is the signal
scoring (M7) needs to label it `underspecified`.

Conversely *"Method A improves accuracy from 72.0 to 78.0 over the baseline"* names
both rows — `Method A` names row `A`, the word "baseline" names row `baseline` —
so both cell locators are justified and emitted.

A row is *named* by the claim when:

| Rule | Example |
| --- | --- |
| an extracted **entity** contains the label as a whole word (case-sensitive) | entity `Method A` names row `A` |
| the label (≥ 3 chars, not a stopword) is a whole word in the claim text, case-insensitively | "over the baseline" names row `baseline` |
| a 1–2 char label is a whole word in the claim text, **case-sensitively** | a lowercase article "a" must not name row `A` |

When the metric column exists but **no** cell is both value-matched and
row-named, the column link is emitted instead. As a last resort, a claim that says
"Table 1" in a bundle holding exactly one table links that table whole.

**Known limitation (test-pinned).** Case-sensitivity cannot separate the row label
`A` from a sentence-initial article "A": *"A method reaches 90% accuracy."* would
name row `A`. `tests/test_linking.py::test_claim_names_row_false_positive_on_sentence_initial_article`
pins this so a future fix shows up as a visible test change.

### Datasets — resolve the name, then name the measured column

A dataset mention (from the extractor's known-name lexicon and its
`"<name> dataset"` pattern) resolves to an artifact by substring match against
`"<artifact_id> <description>"` — `measurements` → `ds_measurements`. This is the
*same function* the extractor uses for its explicit references, so a mention
resolves identically wherever it is seen.

The column locator (`column=value`) is what lets the M5 statistic check recompute
a mean without guessing. Selection is narrow:

1. Drop **identifier** columns (`id`, `sample_id`, `index`, `name`, `label`, …).
2. If a remaining column is named after one of the claim's metrics, take it.
3. Otherwise, if **exactly one** column remains, take it.
4. Otherwise **decline** — link the dataset whole, with no column locator.

Step 4 matters. A dataset with several candidate columns and a claim that names
none of them is underspecified, and the honest link says so by leaving the locator
empty rather than picking the first column.

### Code — which script, and what to observe

1. **By filename.** The claim names a `.py` file matching a code artifact's
   basename (*"Running compute_accuracy.py reports an accuracy of 0.80"*).
2. **Sole artifact.** The claim is a `code_reproduction_claim` and the bundle holds
   exactly one code file. *"The synthetic sequence has a GC content of 0.50"* names
   no script, but only one script could produce it.

Neither holds — several scripts, no filename — and **no code link is emitted**. A
reproduction claim with no resolvable script is a real, reportable state
(`failed_missing_code`, M7), not something to paper over by taking the first
artifact.

The **observable** is read from the bundle, never guessed: when `expected_outputs`
declares a `stdout*` key, the locator is `stdout`.

### Figures

Linked by the data **series** whose name is one of the claim's metrics
(`locator=series=accuracy`), else by a sole-figure "Figure N" mention. Figures
carry metadata and series, never pixels.

**No committed fixture has a figure yet.** The module exists because
`EvidenceKind.FIGURE` and the extractor's "Figure N" detection already do, and a
mention that silently resolved to nothing would be a hole in the audit trail. It
is unit-tested against synthetic figures. Figure *recomputation* lands with M5.

---

## Scoring the linker

`score_linking(predicted, gold)` compares emitted links against a task's
`expected.evidence`, two ways:

- **strict** keys on `(kind, target_id, locator)` — the linker must find the right
  cell/column, not merely the right table;
- **loose** keys on `(kind, target_id)` — "did it find the right artifact at all?"

Keys compare as **sets**, so two gold links into the same table collapse to one
loose key (hence 21 strict / 20 loose links across the eleven fixtures — the two
`accuracy_improvement` table cells share a table).

`quote` is deliberately **not** compared. Gold quotes are hand-trimmed spans; the
linker quotes the best-matching whole sentence. Scoring a rule-based system on
reproducing hand-authored spans would be overclaiming — the same reason M3 does
not score `normalized_claim`.

### Results on the eleven committed fixtures

Reproduce with `python3 -m pytest tests/test_linking.py -q`, or per task with
`claimverifier link-evidence --task <task.yaml> --no-declared-source`.

Blind (`--no-declared-source`), strict keys:

| Task | Gold links | Recovered | Spurious |
| --- | --- | --- | --- |
| `accuracy_improvement` | 3 | 3 | 0 |
| `contradicted_f1` | 2 | 2 | 0 |
| `dataset_mean` | 2 | 2 | 0 |
| `dataset_mean_overstated` | 2 | 2 | 0 |
| `dataset_std` | 2 | 2 | 0 |
| `gc_content` | 2 | 2 | 0 |
| `negated_training_data` | 1 | 1 | 0 |
| `recompute_accuracy` | 2 | 2 | 0 |
| `synthetic_data_passage` | 1 | 1 | 0 |
| `underspecified_split` | 2 | 2 | 0 |
| `unreproducible_accuracy` | 2 | 2 | 0 |
| **total** | **21** | **21** | **0** |

Strict precision 1.00, recall 1.00. Honouring the declared `source_passage` gives
the same 21/21 (it changes the passage link's *method*, not its target).

### How to read this

**This is a consistency check, not a benchmark.** Eleven hand-authored fixtures, and
the locator conventions (`row=…,col=…`, `col=…`, `column=…`, `stdout`) plus the
table row rule were written with the committed table fixtures in view. A
21/21 means *"the linker reproduces the hand-authored provenance exactly, and
invents nothing"* — a real property, and the one M5 depends on. It does **not**
mean retrieval is solved. The count moves whenever a fixture is added; the **zeros
are the invariant**, and they are what the test asserts.

The informative numbers are the passage overlap scores, because that is the only
channel where the outcome was not forced by an identifier:

| Task | Best passage | Overlap | Runner-up | Overlap |
| --- | --- | --- | --- | --- |
| `synthetic_data_passage` | `p_data` | **0.211** | `p_hardware` | **0.000** |
| `negated_training_data` | `p_corpora` | **0.571** | `p_eval_corpora` | **0.182** |
| `accuracy_improvement` | `p_results` | 0.824 (also verbatim) | `p_setup` | 0.308 |
| `underspecified_split` | `p_headline` | 1.000 (verbatim) | `p_detail` | 0.154 |

The three single-passage bundles (`dataset_mean` 1.000, `recompute_accuracy` 0.625,
`gc_content` 0.588) have no runner-up, so their scores test nothing about ranking.

`synthetic_data_passage` is the fixture where keyword overlap is most genuinely
load-bearing: the claim *"The model is trained only on synthetic data"* appears
nowhere verbatim, and the linker must separate the passage that paraphrases it
(0.211) from a distractor about compute hardware (0.000). It does — but note that
0.211 is a **low absolute score**, achieved on two shared tokens (`synthetic`,
`data`). The margin comes from the distractor being *completely* unrelated. A
harder distractor that shared vocabulary without asserting the claim would not be
separated by this baseline. That is the honest limit of bag-of-words retrieval.

`negated_training_data` (M8) shows the two halves of that limit together. Its winning
passage **negates** the claim and still scores 0.571 — retrieval says *"look here"*,
never *"this supports it"*, which is exactly why `evidence_presence` is a separate
check (M5). And its distractor's strongest word never counts at all: `corpus` does
not match `corpora`, so morphology costs the runner-up most of its overlap.

## CLI

`link-evidence` is an addition beyond the `docs/PLAN.md` §10 contract (which lists
the end-to-end verbs); a per-stage command keeps each subsystem independently
runnable and auditable. There is no numbered script — `scripts/03_run_checks.py`
belongs to M5.

```bash
claimverifier link-evidence --task tasks/table_claims/accuracy_improvement.yaml
claimverifier link-evidence --task tasks/ml_claims/synthetic_data_passage.yaml --no-declared-source
claimverifier link-evidence --task tasks/statistical_claims/dataset_mean.yaml --json
claimverifier link-evidence --task tasks/bioinformatics_claims/gc_content.yaml --out results/runs/
```

The linker consumes the extractor's output, so the command runs extraction first.
The text report prints the ranked passage candidates, the emitted links with their
locators and rules, the supporting quote, and — because every task carries gold
evidence — a comparison. `--out DIR` writes `<task_id>.linking.json` (sorted keys,
byte-stable).

```
$ claimverifier link-evidence --task tasks/table_claims/accuracy_improvement.yaml --no-declared-source

Ranked passage candidates (retrieval, not support):
  -> 1. p_results [Results] score=1.000 overlap=0.824 (exact_text)
     2. p_setup [Setup] score=0.308 overlap=0.308 (token_overlap)

Evidence links:
  - passage: p_results score=1  (match=exact_text; overlap=0.824; rank=1)
  - table: t_results [row=A,col=accuracy] score=1  (match=table_cell; value=78)
  - table: t_results [row=baseline,col=accuracy] score=1  (match=table_cell; value=72)

Gold comparison : strict 3/3 gold links recovered, 0 spurious (P=1.00 R=1.00)
  [ok ] predicted links match gold exactly (kind, target, locator)
```

## Determinism and purity

The linker never mutates its input claim (it returns a copy with `evidence_links`
populated), uses no wall clock and no RNG, and orders links by a fixed evidence-kind
sequence. Two runs produce identical links, identical rankings, and an identical
`rules_fired` trail. All three properties are test-pinned.

## Status

**Milestone 4 complete.** Covered by `tests/test_linking.py` (69 tests): unit tests
pin each channel on synthetic bundles; integration tests run the linker over every
committed fixture and score it against gold, blind and with the declared source,
including explicit tests for the distractor separation, the column-not-cell rule,
and the documented row-label false positive.

Next: **M5 — verification checks** (table value, dataset statistic recomputation,
numeric tolerance, comparison, evidence presence, and code execution), which
consume exactly these locators.
