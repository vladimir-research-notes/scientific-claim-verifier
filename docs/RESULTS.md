# RESULTS

Measured outcomes, updated by the milestone that produces them. Every number here
is reproducible offline on a single CPU with the command shown beside it. Numbers
that do not exist yet are marked pending, not estimated.

## Status

| Result | Milestone | State |
| --- | --- | --- |
| Fixture validation | M2 | 7/7 tasks valid |
| Claim extraction vs. gold | M3 | measured below |
| Evidence linking vs. gold | M4 | measured below |
| Verification checks | M5 | measured below |
| Sandbox reproduction | M6 | pending |
| Support labels / failure modes | M7 | pending |
| Smoke suite (8–15 tasks, end to end) | M8 | pending |

## M2 — fixture validation

```bash
python3 scripts/01_validate_fixtures.py
```

7 tasks ok, 0 failed, 0 warnings — `VALID`. The committed tasks span the families
in `docs/PLAN.md` §7: numeric table, dataset statistic, evidence passage,
underspecified, contradiction, code reproduction, and a bioinformatics GC toy. Six
were authored in M2; `contradicted_f1` was added in M5 to exercise the `fail` path
of the table check with a real task rather than a synthetic one.

## M3 — rule-based claim extraction

```bash
python3 -m pytest tests/test_extraction.py -q            # 36 tests
claimverifier extract-claims --task <task.yaml>          # per-task report vs. gold
```

Per-field recovery of the rule-based extractor against each task's gold
extraction target (`expected.claim`), over all seven committed fixtures. List
fields compare as sets; floats with `math.isclose`. `normalized_claim` is not
scored — it is the extractor's own canonical notation, not a gold match target
(see `docs/EXTRACTION.md`).

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

Per-task scored-field totals (8 fields each):

| Task | Claim type | Score |
| --- | --- | --- |
| `accuracy_improvement` | `comparison_claim` | 8/8 |
| `contradicted_f1` | `numeric_claim` | 8/8 |
| `dataset_mean` | `dataset_claim` | 8/8 |
| `gc_content` | `code_reproduction_claim` | 8/8 |
| `recompute_accuracy` | `code_reproduction_claim` | 8/8 |
| `underspecified_split` | `numeric_claim` | 8/8 |
| `synthetic_data_passage` | `descriptive_claim` | 7/8 |

### How to read this

These seven fixtures are a **sanity check, not a benchmark**. They are hand-authored,
and the extractor's lexicons (metrics, known dataset names, role entities) were
chosen with them in view. A `7/7` on `datasets` means "every dataset mention
present in these fixtures was found" — it does not mean dataset extraction is
solved. Extraction is a clearly-labelled heuristic (regexes plus small closed
lexicons); see `docs/EXTRACTION.md` for every rule and its known limits.

The **`6/7` on `conditions` is the most informative number here.** The miss is
`synthetic_data_passage`: gold expects the semantic condition
`"synthetic data only"` for the claim *"The model is trained only on synthetic
data."* The extractor recovers only sample-count conditions (`n = 12`) and returns
`[]` rather than guessing a paraphrase. This is by design — an empty field is
scored `underspecified` downstream, which is honest; a confidently wrong field is
not.

### Worked example

```
$ claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml
(abridged: the header and the per-field gold table are omitted)

Claim           : c_accuracy_improvement (comparison_claim)
Text            : Method A improves accuracy from 72.0 to 78.0 over the baseline on SST-2.
Normalized      : accuracy: 72 -> 78 (>) %

expected_value  : 78.0
baseline_value  : 72.0
operator        : >
units           : %
metrics         : accuracy
datasets        : SST-2
entities        : Method A, baseline
conditions      : —

References (explicit in text; scored linking: link-evidence):
  - dataset: 'SST-2' -> unresolved

Rules fired:
  - from-to: 72.0 -> 78.0
  - metrics: accuracy
  - datasets: SST-2
  - entities: Method A, baseline
  - operator: >
  - units: %

Gold comparison : 8/8 scored fields match
```

The `Rules fired` block is the point: each field is traceable to the rule that
produced it. Note `SST-2` resolves to no artifact — the bundle for this task has
no dataset file, only a table — so the reference is honestly recorded as
`unresolved` rather than silently dropped.

## M4 — evidence linking

```bash
python3 -m pytest tests/test_linking.py -q                      # 70 tests
claimverifier link-evidence --task <task.yaml> --no-declared-source
```

Emitted `EvidenceLink`s scored against each task's gold `expected.evidence`,
**blind** — that is, ignoring the task's declared `claim.source_passage`, which is
asserted provenance rather than something the linker discovers. Keys are compared
strictly, on `(kind, target_id, locator)`: the linker must find the right cell or
column, not merely the right table. `quote` is not compared (see
`docs/EVIDENCE_LINKING.md`).

| Task | Gold links | Recovered | Spurious |
| --- | --- | --- | --- |
| `accuracy_improvement` | 3 | 3 | 0 |
| `contradicted_f1` | 2 | 2 | 0 |
| `dataset_mean` | 2 | 2 | 0 |
| `gc_content` | 2 | 2 | 0 |
| `recompute_accuracy` | 2 | 2 | 0 |
| `synthetic_data_passage` | 1 | 1 | 0 |
| `underspecified_split` | 2 | 2 | 0 |
| **total** | **14** | **14** | **0** |

Strict precision 1.00, recall 1.00, F1 1.00. Honouring the declared
`source_passage` gives the same 14/14 — it changes the passage link's *method*,
not its target.

### How to read this

**A consistency check, not a benchmark.** The locator conventions and the table
row rule were written with the two committed table fixtures in view. A 14/14 means
*"the linker reproduces the hand-authored provenance exactly, and invents
nothing"* — a real property, and the one M5 depends on. It does not mean retrieval
is solved.

The informative numbers are the passage overlap scores, since passages are the one
channel where the answer is not forced by an identifier:

| Task | Best passage | Overlap | Runner-up | Overlap |
| --- | --- | --- | --- | --- |
| `synthetic_data_passage` | `p_data` | **0.211** | `p_hardware` | **0.000** |
| `accuracy_improvement` | `p_results` | 0.824 (also verbatim) | `p_setup` | 0.308 |
| `underspecified_split` | `p_headline` | 1.000 (verbatim) | `p_detail` | 0.154 |

`synthetic_data_passage` is the **only** fixture where keyword overlap is
load-bearing: the claim *"The model is trained only on synthetic data"* appears
nowhere verbatim, so the linker must separate the passage that paraphrases it
(0.211, on the two shared tokens `synthetic` and `data`) from a distractor about
compute hardware (0.000). It does. But 0.211 is a low absolute score, and the
margin comes from the distractor being *completely* unrelated. A harder distractor
sharing vocabulary without asserting the claim would not be separated by a
bag-of-words baseline — which has no model of negation, morphology, or synonymy.
That is why `evidence_presence` is a separate check (M5).

### Worked example

```
$ claimverifier link-evidence --task tasks/ml_claims/underspecified_split.yaml --no-declared-source
(abridged)

Claim           : c_underspecified_split (numeric_claim)
Text            : The method reaches 90% accuracy.

Ranked passage candidates (retrieval, not support):
  -> 1. p_headline [Abstract] score=1.000 overlap=1.000 (exact_text)
     2. p_detail [Results] score=0.154 overlap=0.154 (token_overlap)

Evidence links:
  - passage: p_headline score=1  (match=exact_text; overlap=1.000; rank=1)
  - table: t_splits [col=accuracy] score=1  (match=table_column)

Gold comparison : strict 2/2 gold links recovered, 0 spurious (P=1.00 R=1.00)
```

The table link is the point. The value 90.0 matches exactly one cell (`dev`), so a
cell locator was available — but the claim never says "dev", and emitting
`row=dev,col=accuracy` would have buried the underspecification inside a
confident-looking locator. The linker emits `col=accuracy` instead, leaving the
claim visibly ambiguous over the column. That ambiguity is the signal M7 needs to
label the claim `underspecified` rather than `supported`.

## M5 — verification checks

```bash
python3 -m pytest tests/test_checks.py -q                # 112 tests
claimverifier run-checks --task <task.yaml>              # per-task check report
```

18 checks over the seven committed fixtures: **16 pass, 1 fail, 1 inconclusive**,
0 error, 0 skipped. No check assigns a support label — that inference is M7's.

| Task | Checks | Outcome |
| --- | --- | --- |
| `accuracy_improvement` | 4 | `evidence_presence` pass · `table_value` pass ×2 · `comparison` pass |
| `contradicted_f1` | 2 | `evidence_presence` **pass** · `table_value` **fail** |
| `dataset_mean` | 3 | `evidence_presence` pass · `dataset_statistic` pass ×2 |
| `gc_content` | 3 | `evidence_presence` pass · `code_execution` pass · `numeric_tolerance` pass |
| `recompute_accuracy` | 3 | `evidence_presence` pass · `code_execution` pass · `numeric_tolerance` pass |
| `synthetic_data_passage` | 1 | `evidence_presence` **inconclusive** |
| `underspecified_split` | 2 | `evidence_presence` pass · `table_value` pass (ambiguous over 2 rows) |

### The two rows that matter

**`contradicted_f1` — the fixture the project exists for.** The abstract states
*"Method B reaches an F1 score of 91.0 on MNLI"* verbatim, so `evidence_presence`
passes. The results table reports 86.0, so `table_value` fails. Both are correct,
and a system that collapsed them into one verdict would destroy the only
interesting fact about the claim: the paper contradicts its own table. This is why
the report shows *supporting text* and *computed check* as separate blocks.

**`synthetic_data_passage` — the check admitting it cannot decide.** Gold says
`supported`, and the passage really does support the claim. But *"The model is
trained **only** on synthetic data"* is asserted by *"All experiments use synthetic
data …; no real corpora were used at any stage of **training**"* — a paraphrase.
Token coverage is 40% (`model`, `only`, `trained` are missing: `trained` ≠
`training`, and `only` ≠ `no real corpora were used`). A bag-of-words rule cannot
bridge that, so the check returns **`inconclusive`**, not `fail`. Reporting `fail`
would manufacture a contradiction out of the checker's own ignorance; M7 must map
this to `unverifiable_from_artifacts`.

This is the honest cost of a transparent method, and it is the number to watch: a
stronger evidence checker is measured by whether it can move this claim from
`inconclusive` to `pass` **without** moving `contradicted_f1`'s passage check off
`pass`.

### Same locator, opposite verdict

`underspecified_split` and `contradicted_f1` both link a bare column (`col=accuracy`,
`col=f1`). Only the check's recorded `inputs` tell them apart:

| Fixture | Claimed | Column values | `matching_rows` | Status |
| --- | --- | --- | --- | --- |
| `underspecified_split` | 90.0 | `dev 90.0`, `test 82.0` | `["dev"]` | `pass` — value present, row not named |
| `contradicted_f1` | 91.0 | `baseline 84.0`, `B 86.0` | `[]` | `fail` — nearest 86.0 at row `B` |

### Worked example

```
$ claimverifier run-checks --task tasks/table_claims/contradicted_f1.yaml
(abridged)

Claim           : c_contradicted_f1 (numeric_claim)
Text            : Method B reaches an F1 score of 91.0 on MNLI.

Supporting text (retrieved evidence; whether it *asserts* the claim is checked below):
  "Method B reaches an F1 score of 91.0 on MNLI."

Computed checks (each reads an artifact; none of them decides the verdict):
  [pass] evidence_presence  p_claim         the passage states the claim verbatim
  [fail] table_value        t_mnli[col=f1]  claimed 91 is absent from column 'f1'
                                            (nearest 86 at row B; |difference| = 5 > tolerance 0.05)

Summary         : 2 check(s) — 1 pass, 1 fail

Inference       : NOT produced by this stage.
Task gold       : contradicted / not_applicable / table_cell_mismatch
```

The tolerance of `0.05` was not chosen: the claim wrote `91.0`, one decimal place,
so anything rounding to 91.0 would have matched. See `docs/CHECKS.md`.

## Test and lint status

```bash
python3 -m pytest -q     # 285 passed
ruff check .             # all checks passed
```

| Milestone | New tests | Total |
| --- | --- | --- |
| M0 | 13 | 13 |
| M1 | 25 | 38 |
| M2 | 28 | 66 |
| M3 | 36 | 102 |
| M4 | 69 | 171 |
| M5 | 114 | 285 |

All tests are CPU-only and offline; none touch the network, and no paid API is
used anywhere in the default path. M5's tests execute two committed, stdlib-only
fixture scripts as child processes — local, harmless, and offline.
