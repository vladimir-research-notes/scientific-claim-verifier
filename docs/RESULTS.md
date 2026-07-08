# RESULTS

Measured outcomes, updated by the milestone that produces them. Every number here
is reproducible offline on a single CPU with the command shown beside it. Numbers
that do not exist yet are marked pending, not estimated.

## Status

| Result | Milestone | State |
| --- | --- | --- |
| Fixture validation | M2 | 6/6 tasks valid |
| Claim extraction vs. gold | M3 | measured below |
| Evidence linking | M4 | pending |
| Verification checks | M5 | pending |
| Sandbox reproduction | M6 | pending |
| Support labels / failure modes | M7 | pending |
| Smoke suite (8–15 tasks, end to end) | M8 | pending |

## M2 — fixture validation

```bash
python3 scripts/01_validate_fixtures.py
```

6 tasks ok, 0 failed, 0 warnings — `VALID`. The six committed tasks span the
families in `docs/PLAN.md` §7: numeric table, dataset statistic, evidence passage,
underspecified, code reproduction, and a bioinformatics GC toy.

## M3 — rule-based claim extraction

```bash
python3 -m pytest tests/test_extraction.py -q            # 36 tests
claimverifier extract-claims --task <task.yaml>          # per-task report vs. gold
```

Per-field recovery of the rule-based extractor against each task's gold
extraction target (`expected.claim`), over all six committed fixtures. List
fields compare as sets; floats with `math.isclose`. `normalized_claim` is not
scored — it is the extractor's own canonical notation, not a gold match target
(see `docs/EXTRACTION.md`).

| Field | Recovered | Channel |
| --- | --- | --- |
| `expected_value` | 6/6 | reliable |
| `baseline_value` | 6/6 | reliable |
| `comparison_operator` | 6/6 | reliable |
| `units` | 6/6 | reliable |
| `metrics` | 6/6 | reliable |
| `datasets` | 6/6 | best effort |
| `entities` | 6/6 | best effort |
| `conditions` | **5/6** | best effort |

Per-task scored-field totals (8 fields each):

| Task | Claim type | Score |
| --- | --- | --- |
| `accuracy_improvement` | `comparison_claim` | 8/8 |
| `dataset_mean` | `dataset_claim` | 8/8 |
| `gc_content` | `code_reproduction_claim` | 8/8 |
| `recompute_accuracy` | `code_reproduction_claim` | 8/8 |
| `underspecified_split` | `numeric_claim` | 8/8 |
| `synthetic_data_passage` | `descriptive_claim` | 7/8 |

### How to read this

These six fixtures are a **sanity check, not a benchmark**. They are hand-authored,
and the extractor's lexicons (metrics, known dataset names, role entities) were
chosen with them in view. A `6/6` on `datasets` means "both dataset mentions
present in these fixtures were found" — it does not mean dataset extraction is
solved. Extraction is a clearly-labelled heuristic (regexes plus small closed
lexicons); see `docs/EXTRACTION.md` for every rule and its known limits.

The **`5/6` on `conditions` is the most informative number here.** The miss is
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

References (explicit in text; scored linking is M4):
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

## Test and lint status

```bash
python3 -m pytest -q     # 102 passed
ruff check .             # all checks passed
```

| Milestone | New tests | Total |
| --- | --- | --- |
| M0 | 13 | 13 |
| M1 | 25 | 38 |
| M2 | 28 | 66 |
| M3 | 36 | 102 |

All tests are CPU-only and offline; none touch the network, and no paid API is
used anywhere in the default path.
