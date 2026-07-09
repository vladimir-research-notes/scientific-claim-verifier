# EXTRACTION — rule-based claim extraction

Reference for the claim extractor introduced in **Milestone 3**. The code lives in
[`src/scientific_claim_verifier/claims/extraction.py`](../src/scientific_claim_verifier/claims/extraction.py)
and [`normalization.py`](../src/scientific_claim_verifier/claims/normalization.py).

Extraction turns the claim *as authored* — an input `ScientificClaim` carrying
only `claim_id`, `claim_text`, `claim_type`, and provenance — into a **populated**
claim whose typed fields the later checks (M5) consume: `expected_value`,
`baseline_value`, `comparison_operator`, `units`, `metrics`, `datasets`,
`entities`, `conditions`, and a canonical `normalized_claim`.

## This is a heuristic, and it is labelled as one

The extractor is regular expressions plus small, closed lexicons. It performs no
learned NLP, no parsing, and no inference. It will not generalize to arbitrary
scientific prose, and it is not meant to — a stronger extractor (an LLM adapter,
M10) can be dropped in behind the same interface.

What the rule-based extractor *does* buy is the property this project exists for:
**auditability**. Every populated field is produced by a named rule, and the rules
that fired are recorded in `Extraction.rules_fired`, so a reviewer can see exactly
why a value was extracted:

```
Rules fired:
  - from-to: 72.0 -> 78.0
  - metrics: accuracy
  - datasets: SST-2
  - entities: Method A, baseline
  - operator: >
  - units: %
```

The rules are deliberately **conservative**: they prefer to leave a field empty
over guessing. An unextracted field is scored `underspecified` downstream, which
is a safe, honest outcome; a confidently wrong field is not.

## Input / gold separation

`LoadedTask.input_claim` builds the input claim with all extraction targets
empty. The gold target lives separately in the task's `expected.claim`
(`GoldClaim`). Loading a task therefore never leaks the answer to the extractor —
see `docs/ARTIFACT_FORMAT.md`. A test pins that the extractor does not mutate its
input claim.

## The rules

### Numbers

A numeric token is an optional sign, digits, an optional decimal part, and an
optional trailing `%`. A look-behind refuses digits that belong to an identifier
or a hyphenated name, so **`SST-2`, `CIFAR-10`, and `eval2.py` yield no number**,
while `72.0`, `-5`, `0.50`, and `90%` do. This matters: without it, the "2" in
`SST-2` would be read as a value.

### Comparison ("from X to Y")

The phrase `from <num> to <num>` sets `baseline_value = X` and
`expected_value = Y`. This is the only rule that populates `baseline_value`.

### Headline value

With no `from…to`, `expected_value` is the **first numeric token that is not a
sample count**. So in *"has 12 samples with a mean value of 3.4"*, `12` is
consumed as a count and the headline value is `3.4`.

### Sample counts

An integer immediately followed by a count noun (`samples`, `examples`,
`instances`, `observations`, `records`, `sequences`, `points`, `rows`,
`data points`) is a count: it adds the `count` metric and the condition `n = N`,
and it is excluded from the headline value.

### Comparison operator

Precedence, first match wins:

| Rule | Result |
| --- | --- |
| explicit `from X to Y` | `>` if `Y > X`, `<` if `Y < X`, else `=` |
| an "up" verb (`improve`, `outperform`, `increase`, `higher`, `better`, `gain`, `surpass`, `exceed`) | `>` |
| a "down" verb (`reduce`, `lower`, `decrease`, `drop`, `worse`, `fewer`, `shrink`) | `<` |
| `claim_type` is `dataset_claim` or `code_reproduction_claim` | `~` (recomputation compares within tolerance) |
| `claim_type` is `numeric_claim` | `=` |
| `claim_type` is `comparison_claim` | `>` |
| otherwise (e.g. `descriptive_claim`) | none |

Note that `reaches` is deliberately **not** an "up" verb: *"the method reaches 90%
accuracy"* asserts a value (`=`), it does not compare.

### Metrics

A closed surface-form → canonical-name lexicon, matched on word boundaries and
returned in first-appearance order:

`gc_content` · `f1` (also `f1 score`, `f1-score`) · `accuracy` · `precision` ·
`recall` · `auc` · `bleu` · `rouge` · `perplexity` · `correlation` · `std` (also
`standard deviation`) · `median` · `mean` (also `average`) · `loss` · `count`
(from `count` and the count nouns above).

Word boundaries matter: *"the meaning of the result"* yields no `mean`.

### Units

`%` if a percent sign is present. Otherwise — an explicit heuristic — a
percentage-scale metric (`accuracy`, `f1`, `precision`, `recall`, `auc`) whose
value **exceeds 1** is read as a percentage, so *"accuracy from 72.0 to 78.0"*
gets `%` while *"an accuracy of 0.80"* (a 0–1 fraction) stays unitless.

### Datasets — *best effort*

Two triggers: a **known-name lexicon** (`SST-2`, `MNLI`, `GLUE`, `SQuAD`,
`ImageNet`, `CIFAR-10`, `MNIST`, …) and the phrase pattern
`<name> dataset|corpus|benchmark`. Nothing else counts, so *"trained only on
synthetic data"* yields **no** dataset — "data" alone is not a trigger.

**Limitation:** a novel dataset name that is neither in the lexicon nor followed
by the word "dataset" is missed.

### Entities — *best effort*

The proper-name pattern `Method X` (capitalized) plus a minimal role lexicon
(`baseline`, `model`). A bare lowercase *"the method"* is **not** tagged. This is
an illustrative, deliberately narrow lexicon, not a named-entity recognizer.

### Conditions — *best effort, and knowingly incomplete*

Only **sample-count** conditions (`n = 12`) are recovered. Free-form semantic
conditions — e.g. gold `"synthetic data only"` for *"The model is trained only on
synthetic data."* — are **not** guessed. See the results table below: this is the
one field the extractor misses on the committed fixtures, and it is the honest
face of a rule-based system's limits.

## References (not evidence links)

The extractor also records artifact references the claim text names *explicitly*,
resolved against the bundle where possible:

- a `.py` filename → the code artifact with that basename
  (`compute_accuracy.py` → `code_accuracy`);
- a dataset name → the dataset artifact whose id/description contains it
  (`measurements` → `ds_measurements`);
- a `Table N` / `Figure N` mention → recorded, **unresolved** (there is no
  number → id map).

These carry **no relevance score**. Searching the bundle for the passage that best
*supports* a claim, with a score, is the evidence linker's job (**Milestone 4**, see
[`docs/EVIDENCE_LINKING.md`](EVIDENCE_LINKING.md)); the extracted claim's
`evidence_links` is left empty here. The linker reuses two of this module's
functions — `extract_metrics` (so a table header and a claim metric canonicalize
identically) and `resolve_dataset_reference` (so a dataset mention resolves the
same way wherever it is seen).

## `normalized_claim`

A deterministic canonical rendering built from the populated fields:

| Shape | Example |
| --- | --- |
| comparison with both endpoints | `accuracy: 72 -> 78 (>) %` |
| a single value | `accuracy = 90 %`, `mean ~ 3.4`, `gc_content ~ 0.5` |
| no numeric value | the canonicalized claim text |

This is the **extractor's own** notation. It is deliberately *not* compared against
a task's gold `normalized_claim`, which is a hand-authored human reference in a
different notation — a rule-based system cannot be expected to reproduce arbitrary
phrasing, and scoring it as if it could would be overclaiming.

## Scoring

`score_extraction(extracted, gold)` compares the eight structured fields in
`SCORED_FIELDS`. List fields (`metrics`, `datasets`, `entities`, `conditions`)
compare as **sets** — order is not semantically meaningful. Float fields compare
with `math.isclose`. `normalized_claim` is excluded, per above.

### Results on the seven committed fixtures

Reproduce with `python3 -m pytest tests/test_extraction.py -q`, or per task with
`claimverifier extract-claims --task <task.yaml>`.

| Field | Recovered | Channel |
| --- | --- | --- |
| `expected_value` | 7/7 | reliable |
| `baseline_value` | 7/7 | reliable |
| `comparison_operator` | 7/7 | reliable |
| `units` | 7/7 | reliable |
| `metrics` | 7/7 | reliable |
| `datasets` | 7/7 | best effort |
| `entities` | 7/7 | best effort |
| `conditions` | **6/7** | best effort |

The single miss is `synthetic_data_passage`, whose gold condition
`"synthetic data only"` is a semantic paraphrase of *"trained only on synthetic
data"*. The extractor returns `[]` rather than guessing.

**Read these numbers honestly.** Seven hand-authored fixtures are a sanity check,
not a benchmark. The lexicons (datasets, entities, metrics) were chosen to cover
these fixtures; a `7/7` on `datasets` means "every dataset mention present was
found", not "dataset extraction is solved". The `6/7` on `conditions` is the more
informative number.

## CLI

Flag names follow the CLI contract in `docs/PLAN.md` §10 (`--task`, `--out`);
`--json` is an addition for machine-readable output.

```bash
claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml
claimverifier extract-claims --task tasks/statistical_claims/dataset_mean.yaml --json
claimverifier extract-claims --task tasks/bioinformatics_claims/gc_content.yaml --out results/runs/
python3 scripts/02_extract_claims.py --task tasks/code_reproduction/recompute_accuracy.yaml
```

The text report prints the recovered fields, the explicit references, the rules
that fired, and — because every task carries a gold target — a per-field
comparison. `--out DIR` writes `<task_id>.extraction.json` (sorted keys, so the
artifact is byte-stable).

## Status

**Milestone 3 complete.** Covered by `tests/test_extraction.py` (36 tests): unit
tests pin each rule on crafted inputs; integration tests run the extractor over
every committed fixture and score it against gold, including an explicit test that
the one condition miss is the documented semantic one.

The extractor's output feeds the evidence linker
([`docs/EVIDENCE_LINKING.md`](EVIDENCE_LINKING.md), Milestone 4), which uses the
recovered `metrics`, `entities`, `expected_value`, and `baseline_value` to locate
the exact table cells, dataset columns, and code artifacts a claim points at.
