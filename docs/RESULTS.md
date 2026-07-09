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
| Sandbox reproduction | M6 | measured below |
| Support labels / failure modes | M7 | measured below |
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
python3 -m pytest tests/test_checks.py -q                # 118 tests (6 added by M7)
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

## M6 — sandbox reproduction

```bash
python3 -m pytest tests/test_sandbox.py -q          # 61 tests
claimverifier run-sandbox --task <task.yaml> --out results/runs/
```

Both committed code fixtures execute under the recorded policy and reproduce the
metric their claim states — offline, with the network guard installed, in a temp
directory they cannot escape upward from.

| Task | Script | stdout | Exit | Network attempts | Files written |
| --- | --- | --- | --- | --- | --- |
| `recompute_accuracy` | `compute_accuracy.py` | `accuracy=0.80` | 0 | none | none |
| `gc_content` | `gc_content.py` | `gc_content=0.50` | 0 | none | none |

The M5 check table is **unchanged** under the new runner — 18 checks over 7 fixtures,
16 pass / 1 fail / 1 inconclusive — which is the result worth reporting: swapping a
bare `subprocess.run` for a policy-enforcing sandbox moved no verdict. The
`ScriptRunner` protocol M5 introduced held, and `code_execution` changed only its
default runner.

### What the sandbox actually enforces

Each row is a guard, and the test that fires it. These are **reproducibility**
controls; none of them is a security boundary (`docs/SANDBOX.md`).

| Guard | Demonstrated by |
| --- | --- |
| Fresh temp `cwd`, removed after | a script sees only itself; `pyproject.toml` is not reachable |
| Environment allowlist | a parent variable is `absent` in the child; `PYTHONHASHSEED=0`, `TZ=UTC` |
| Network guard denies + **records** | `socket.socket()` raises; the attempt survives a script that catches it |
| Guard integrity is verified | a `sitecustomize` that raises → `SandboxError`, not a silent open network |
| Timeout kills the process **group** | a grandchild spawned by the script is reaped with it |
| `RLIMIT_AS` | `bytearray(3 GiB)` → `MemoryError` |
| `RLIMIT_CPU` | `while True: pass` → killed by signal at 1 CPU-second, `timed_out=False` |
| Trace determinism | two runs of one script → byte-identical JSONL |

### The result that took two attempts

The first network guard replaced `socket.socket` with a *function*. `ssl.py` executes
`class SSLSocket(socket)` at import time, so `import urllib.request` died with
`TypeError: function() argument 'code' must be code, not str` — blocking the network
by accident, in a way that would have confused anyone whose script merely imported
`http.client`. The guard now installs a raising **subclass**, so the import succeeds
and the denial happens at `socket.create_connection`, where the connection is actually
attempted. Both behaviours are test-pinned.

### Worked example

```
$ claimverifier run-sandbox --task tasks/code_reproduction/recompute_accuracy.yaml

Task            : recompute_accuracy
Code artifact   : code_accuracy (data/fixtures/code/compute_accuracy.py)
Content hash    : sha256:9bc64b75db9d64c24eb78e3696cd5e1679771ac83a74062733d25f65800a3d9a
Command         : python compute_accuracy.py

Policy (recorded verbatim into the trace):
  timeout       : 10.0s
  network       : blocked — in-process socket guard; cooperative, bypassable, not a boundary
  working dir   : fresh temp dir, removed after the run
  stdin         : closed
  env allowlist : LANG, LC_ALL, LC_CTYPE, PATH, SYSTEMROOT
  env overrides : PYTHONDONTWRITEBYTECODE=1, PYTHONHASHSEED=0, PYTHONNOUSERSITE=1, TZ=UTC
  rlimits       : RLIMIT_AS=2147483648, RLIMIT_CPU=11, RLIMIT_FSIZE=8388608, RLIMIT_NOFILE=256
  isolation     : none — controlled fixture execution, not a security boundary

Outcome         : exited 0
Network attempts: none
Files written   : none

stdout:
  accuracy=0.80
stderr:
  (empty)
```

The policy is printed *before* the number, and recorded before it in the trace, for
the same reason: `accuracy=0.80` is not a result until you know what produced it.

### How to read this

Two fixtures is not a reproducibility benchmark. Both scripts are stdlib-only, embed
their own data, take no arguments, and were written by the same agent as the sandbox
that runs them. What the table shows is that the controls hold and cost nothing: the
scripts still reproduce with the environment scrubbed, the network denied, and the
filesystem view emptied. The interesting failures are the guard tests above, not the
two passes.

Wall-clock duration is measured (≈30 ms per script here) and deliberately kept out of
the trace unless `--with-timing` is passed. It is the only value in an execution record
that cannot be reproduced.

## M7 — support labels, reproduction status, failure modes

```bash
python3 -m pytest tests/test_scoring.py -q                # 100 tests
claimverifier verify --task <task.yaml>                   # per-task verdict + trace
claimverifier verify --task A.yaml --task B.yaml ...      # + aggregate summary
```

The verdict the pipeline draws for each committed fixture, beside the gold outcome the
task file declares. Nothing here is an LLM judgement: each label is assigned by a named
rule over the M5 checks, and the rule is recorded in the trace.

| Task | Support label | Reproduction | Failure mode | Gold |
| --- | --- | --- | --- | --- |
| `accuracy_improvement` | `supported` | `not_applicable` | `none` | ✓ ✓ ✓ |
| `contradicted_f1` | `contradicted` | `not_applicable` | `table_cell_mismatch` | ✓ ✓ ✓ |
| `dataset_mean` | `supported` | `reproduced` | `none` | ✓ ✓ ✓ |
| `gc_content` | `supported` | `reproduced` | `none` | ✓ ✓ ✓ |
| `recompute_accuracy` | `supported` | `reproduced` | `none` | ✓ ✓ ✓ |
| `underspecified_split` | `underspecified` | `not_applicable` | `underspecified` | ✓ ✓ ✓ |
| `synthetic_data_passage` | **`unverifiable_from_artifacts`** | `not_applicable` | **`evidence_undecidable`** | ✗ ✓ ✗ |

| Agreement with gold | Score |
| --- | --- |
| `support_label` | **6/7** |
| `reproduction_status` | **7/7** |
| `failure_mode` | **6/7** |
| **Wrong verdicts** | **0/7** |
| Conservative misses | 1/7 (`synthetic_data_passage`) |

### The only number that matters here

**Wrong verdicts: 0.** A mismatch is bucketed by *kind*, because a single accuracy
number hides the difference between a system that says the wrong thing and one that
declines to say anything:

- a **conservative miss** predicts a non-committal label (`unverifiable_from_artifacts`,
  `not_checked`) where gold commits — the system declined to decide, and asserted
  nothing false;
- a **wrong verdict** asserts a committal label gold disagrees with.

The pipeline's single miss is `synthetic_data_passage`, and it is conservative. Gold
says `supported`; the passage really does support the claim. But *"The model is trained
**only** on synthetic data"* is asserted by *"All experiments use synthetic data …; no
real corpora were used at any stage of **training**"* — a paraphrase at 40% token
coverage. The lexical evidence check returns `inconclusive` (M5), scoring maps that to
`unverifiable_from_artifacts` with failure mode `evidence_undecidable`, and
`confidence` reads `0.00`: *nothing about this claim was decided, and the report says
so.*

This is the honest cost of a transparent method, and `wrong_verdicts` is the number to
watch: **a change to the extractor, the linker, or the checks that raises label accuracy
by turning a conservative miss into a wrong verdict has made the tool worse.**

### Where each verdict comes from

Two fixtures link the same locator shape and get opposite labels, from the same rule
table, on the strength of what the checks recorded in `inputs`:

| Fixture | `table_value` | `matching_rows` | Signal | Label |
| --- | --- | --- | --- | --- |
| `underspecified_split` | `pass` | `["dev"]` of 2 rows | `ambiguous` | `underspecified` |
| `contradicted_f1` | `fail` | `[]` of 2 rows | `refutes` | `contradicted` |

And `contradicted_f1` keeps both channels visible: its `evidence_presence` check
**passes** (the abstract asserts the claim verbatim) while its `table_value` check
**fails** (the table says 86.0). The support label is `contradicted`, and the report
still shows the passage that asserts it. Collapsing the two would destroy the only
interesting fact about the claim.

### Worked example

```
$ claimverifier verify --task tasks/ml_claims/synthetic_data_passage.yaml
(abridged)

Claim           : c_synthetic_data (descriptive_claim)
Text            : The model is trained only on synthetic data.

Supporting text (retrieved evidence):
  "All experiments use synthetic data generated by our pipeline; no real corpora
   were used at any stage of training."

Computed checks (what each artifact says about the claim):
  [inconclusive] evidence_presence  p_data  -> undecided

Inference (drawn from the checks above; each rule names the checks it read):
  support_label       : unverifiable_from_artifacts
    rule              : nothing_decided [c_synthetic_data.evidence_presence.1]
    because           : no check reached a verdict: a lexical check cannot decide
                        whether the passage asserts the claim (40% token coverage,
                        missing ['model', 'only', 'trained'])
  reproduction_status : not_applicable
    rule              : no_reproduction_channel
  failure_mode        : evidence_undecidable
  confidence          : 0.00 (share of checks that reached a verdict; not a probability)

Unverifiable from these artifacts (what this verdict does NOT settle):
  - evidence_presence: a lexical check cannot decide whether the passage asserts
    the claim (40% token coverage, missing ['model', 'only', 'trained'])

Task gold       : supported [MISS] / not_applicable [ok ] / none [MISS]
```

The report marks its own miss. `evidence_undecidable` is a new failure mode
(`SCHEMA_VERSION` 1.2): `inconclusive` arrived in M5 with nothing to map onto, and
recording `passage_does_not_assert` here would have published the checker's ignorance
as a fact about the paper.

### How to read this

**A regression harness, not a benchmark.** Seven hand-authored synthetic fixtures, whose
gold outcomes were written alongside the rules that score them. 6/7 does not mean
scientific claim verification is 86% solved. What the table shows is that the rule table
is coherent (no fixture needs a special case), that it never asserts a verdict gold
contradicts, and that the one claim its methods cannot read is *reported as unread*
rather than guessed at.

`reproduction_status` is 7/7 because the three reproducing fixtures reproduce **exactly**
— `mean(value) = 40.8/12 = 3.4`, `accuracy=0.80`, `gc_content=0.50` — and the four table
and passage claims correctly get `not_applicable`: reading a value out of a table cell is
a lookup, not a reproduction.

Traces are byte-identical across runs, including for the two fixtures whose scripts
actually execute. See `docs/SCORING.md` for every rule and its known limits.

## Test and lint status

```bash
python3 -m pytest -q     # 452 passed
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
| M6 | 61 | 346 |
| M7 | 106 | 452 |

All tests are CPU-only and offline; none touch the network, and no paid API is
used anywhere in the default path. M5's and M6's tests execute committed, stdlib-only
fixture scripts (plus a few written by the tests themselves) as child processes —
local, harmless, and offline. The socket tests either construct a socket or are
refused before one exists; none of them connects to anything.

Two tests are load-bearing on the wall clock: the CPU-limit test burns ~1 CPU-second
and the process-group test waits ~1 s for its timeout. Both assert that something was
*killed*, so a slow machine makes them more likely to pass, not less.
