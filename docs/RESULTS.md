# RESULTS

Measured outcomes, updated by the milestone that produces them. Every number here
is reproducible offline on a single CPU with the command shown beside it. Numbers
that do not exist yet are marked pending, not estimated.

## Status

| Result | Milestone | State |
| --- | --- | --- |
| Fixture validation | M2 | 11/11 tasks + 1 suite valid |
| Claim extraction vs. gold | M3 | measured below |
| Evidence linking vs. gold | M4 | measured below |
| Verification checks | M5 | measured below |
| Sandbox reproduction | M6 | measured below |
| Support labels / failure modes | M7 | measured below |
| Smoke suite (8–15 tasks, end to end) | M8 | 11 tasks, gate PASS |
| Reports generated from traces | M9 | 11 reports + index, round trip exact |
| Integration exports | M11 | 5 formats, byte-stable, no external import |
| Episode replay | M11 | 11/11 reproduced, byte-identical traces (`--strict`) |

> **The fixture set grew in M8**, from seven tasks to eleven, so that the smoke suite
> could reach the labels and statuses the original seven never produced —
> `partially_supported`, `approximately_reproduced`, `failed_numeric_mismatch`,
> `failed_environment`, `statistic_mismatch`, `passage_does_not_assert`,
> `execution_error`. Every number below is measured over all eleven.

## M2 — fixture validation

```bash
python3 scripts/01_validate_fixtures.py
```

11 tasks ok, 1 suite ok, 0 failed, 0 warnings — `VALID`. The committed tasks span the
families in `docs/PLAN.md` §7: numeric table, dataset statistic, evidence passage,
underspecified, contradiction, code reproduction, and a bioinformatics GC toy. Six were
authored in M2; `contradicted_f1` was added in M5 to exercise the `fail` path of the
table check with a real task; four more in M8 (below). The suite file
`tasks/smoke_suite.yaml` is validated too: it is invalid if it names a `task_id` no task
declares.

### Fixtures added in M8

Each was authored to reach a verdict no existing fixture could, and each landed on its
hand-written gold outcome on the first run — extraction, linking, checks, and scoring all
unchanged.

| Task | Reaches | Gold outcome |
| --- | --- | --- |
| `dataset_std` | `approximately_reproduced` | supported / approximately_reproduced / none |
| `dataset_mean_overstated` | contradiction via **recomputation** | contradicted / failed_numeric_mismatch / statistic_mismatch |
| `unreproducible_accuracy` | a script that will not run | partially_supported / failed_environment / execution_error |
| `negated_training_data` | contradiction via **polarity** | contradicted / not_applicable / passage_does_not_assert |

## M3 — rule-based claim extraction

```bash
python3 -m pytest tests/test_extraction.py -q            # 36 tests
claimverifier extract-claims --task <task.yaml>          # per-task report vs. gold
```

Per-field recovery of the rule-based extractor against each task's gold
extraction target (`expected.claim`), over all eleven committed fixtures. List
fields compare as sets; floats with `math.isclose`. `normalized_claim` is not
scored — it is the extractor's own canonical notation, not a gold match target
(see `docs/EXTRACTION.md`).

| Field | Recovered | Channel |
| --- | --- | --- |
| `expected_value` | 11/11 | reliable |
| `baseline_value` | 11/11 | reliable |
| `comparison_operator` | 11/11 | reliable |
| `units` | 11/11 | reliable |
| `metrics` | 11/11 | reliable |
| `datasets` | 11/11 | best effort |
| `entities` | 11/11 | best effort |
| `conditions` | **10/11** | best effort |

Every fixture scores 8/8 on the eight scored fields except `synthetic_data_passage`,
which scores 7/8 (see below). The four fixtures added in M8 needed no extractor change:
`standard deviation` was already in the metric lexicon, and the failing script's claim
resolves its `.py` filename by basename like any other.

### How to read this

These eleven fixtures are a **sanity check, not a benchmark**. They are hand-authored,
and the extractor's lexicons (metrics, known dataset names, role entities) were
chosen with them in view. An `11/11` on `datasets` means "every dataset mention
present in these fixtures was found" — it does not mean dataset extraction is
solved. Extraction is a clearly-labelled heuristic (regexes plus small closed
lexicons); see `docs/EXTRACTION.md` for every rule and its known limits.

The **`10/11` on `conditions` is the most informative number here.** The miss is
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
| `dataset_mean_overstated` | 2 | 2 | 0 |
| `dataset_std` | 2 | 2 | 0 |
| `gc_content` | 2 | 2 | 0 |
| `negated_training_data` | 1 | 1 | 0 |
| `recompute_accuracy` | 2 | 2 | 0 |
| `synthetic_data_passage` | 1 | 1 | 0 |
| `underspecified_split` | 2 | 2 | 0 |
| `unreproducible_accuracy` | 2 | 2 | 0 |
| **total** | **21** | **21** | **0** |

Strict precision 1.00, recall 1.00, F1 1.00. Honouring the declared
`source_passage` gives the same 21/21 — it changes the passage link's *method*,
not its target.

### How to read this

**A consistency check, not a benchmark.** The locator conventions and the table
row rule were written with the two committed table fixtures in view. A 21/21 means
*"the linker reproduces the hand-authored provenance exactly, and invents
nothing"* — a real property, and the one M5 depends on. It does not mean retrieval
is solved. The count moves whenever a fixture is added; the **zeros are the
invariant**, and they are what the test asserts.

The informative numbers are the passage overlap scores, since passages are the one
channel where the answer is not forced by an identifier:

| Task | Best passage | Overlap | Runner-up | Overlap |
| --- | --- | --- | --- | --- |
| `synthetic_data_passage` | `p_data` | **0.211** | `p_hardware` | **0.000** |
| `negated_training_data` | `p_corpora` | **0.571** | `p_eval_corpora` | **0.182** |
| `accuracy_improvement` | `p_results` | 0.824 (also verbatim) | `p_setup` | 0.308 |
| `underspecified_split` | `p_headline` | 1.000 (verbatim) | `p_detail` | 0.154 |

`synthetic_data_passage` is the fixture where keyword overlap is most load-bearing:
the claim *"The model is trained only on synthetic data"* appears nowhere verbatim, so
the linker must separate the passage that paraphrases it (0.211, on the two shared
tokens `synthetic` and `data`) from a distractor about compute hardware (0.000). It
does. But 0.211 is a low absolute score, and the margin comes from the distractor being
*completely* unrelated. A harder distractor sharing vocabulary without asserting the
claim would not be separated by a bag-of-words baseline — which has no model of
negation, morphology, or synonymy. That is why `evidence_presence` is a separate check
(M5).

`negated_training_data` (M8) shows both halves of that limitation at once. Its winning
passage **negates** the claim, and scores 0.571 anyway — the linker retrieves it and
says nothing about whether it supports anything, which is exactly the division of labour
intended. Meanwhile its distractor's strongest word never counts: `corpus` does not
match `corpora`, so morphology costs the runner-up most of its overlap.

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

26 checks over the eleven committed fixtures: **20 pass, 3 fail, 1 inconclusive,
1 error, 1 skipped** — every one of the five statuses now fires on a real task. No
check assigns a support label; that inference is M7's.

| Task | Checks | Outcome |
| --- | --- | --- |
| `accuracy_improvement` | 4 | `evidence_presence` pass · `table_value` pass ×2 · `comparison` pass |
| `contradicted_f1` | 2 | `evidence_presence` **pass** · `table_value` **fail** |
| `dataset_mean` | 3 | `evidence_presence` pass · `dataset_statistic` pass ×2 |
| `dataset_mean_overstated` | 2 | `evidence_presence` **pass** · `dataset_statistic` **fail** |
| `dataset_std` | 2 | `evidence_presence` pass · `dataset_statistic` pass (within tolerance, not exact) |
| `gc_content` | 3 | `evidence_presence` pass · `code_execution` pass · `numeric_tolerance` pass |
| `negated_training_data` | 1 | `evidence_presence` **fail** (polarity mismatch) |
| `recompute_accuracy` | 3 | `evidence_presence` pass · `code_execution` pass · `numeric_tolerance` pass |
| `synthetic_data_passage` | 1 | `evidence_presence` **inconclusive** |
| `underspecified_split` | 2 | `evidence_presence` pass · `table_value` pass (ambiguous over 2 rows) |
| `unreproducible_accuracy` | 3 | `evidence_presence` pass · `code_execution` **error** · `numeric_tolerance` **skipped** |

`evidence_presence` fails on `negated_training_data` and is `inconclusive` on
`synthetic_data_passage`, and the difference is the whole design: the first passage
contains every token of its claim *and a negation*, which refutes it; the second is a
paraphrase the rule cannot read, which refutes nothing.

`unreproducible_accuracy` is where `error` and `skipped` come from, and they are not the
same thing. The script exited 1, so `code_execution` **could not run the claim's
computation** (`error`, `nonzero_exit`). `numeric_tolerance` is then `skipped`, not
`fail`: no number disagreed with 0.95, because no number exists.

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

Three committed code fixtures execute under the recorded policy — offline, with the
network guard installed, in a temp directory they cannot escape upward from. Two
reproduce the metric their claim states. The third fails, on purpose.

| Task | Script | stdout | Exit | Network attempts | Files written |
| --- | --- | --- | --- | --- | --- |
| `recompute_accuracy` | `compute_accuracy.py` | `accuracy=0.80` | 0 | none | none |
| `gc_content` | `gc_content.py` | `gc_content=0.50` | 0 | none | none |
| `unreproducible_accuracy` | `reproduce_from_predictions.py` | *(empty)* | **1** | none | none |

`reproduce_from_predictions.py` (M8) is a complete, working script whose input
`predictions.csv` the paper never released — the most ordinary reproducibility failure
there is. It prints one line to stderr and exits 1. The sandbox reports that as
`exited 1`, `code_execution` records `error` / `nonzero_exit`, and the reproduction
status is `failed_environment` — never `failed_numeric_mismatch`, because a script that
will not run tells you nothing about the claim's number.

The M5 check table was **unchanged** by the new runner when M6 landed — the same 18
checks over the then-seven fixtures, 16 pass / 1 fail / 1 inconclusive — which is the
result worth reporting: swapping a bare `subprocess.run` for a policy-enforcing sandbox
moved no verdict. The `ScriptRunner` protocol M5 introduced held, and `code_execution`
changed only its default runner.

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

Three fixtures is not a reproducibility benchmark. The scripts are stdlib-only, embed
their own data (or, in the failing case, deliberately do not), take no arguments, and
were written by the same agent as the sandbox that runs them. What the table shows is
that the controls hold and cost nothing: the scripts still reproduce with the
environment scrubbed, the network denied, and the filesystem view emptied. The
interesting failures are the guard tests above, not the two passes.

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
| `dataset_mean_overstated` | `contradicted` | `failed_numeric_mismatch` | `statistic_mismatch` | ✓ ✓ ✓ |
| `dataset_std` | `supported` | `approximately_reproduced` | `none` | ✓ ✓ ✓ |
| `gc_content` | `supported` | `reproduced` | `none` | ✓ ✓ ✓ |
| `negated_training_data` | `contradicted` | `not_applicable` | `passage_does_not_assert` | ✓ ✓ ✓ |
| `recompute_accuracy` | `supported` | `reproduced` | `none` | ✓ ✓ ✓ |
| `underspecified_split` | `underspecified` | `not_applicable` | `underspecified` | ✓ ✓ ✓ |
| `unreproducible_accuracy` | `partially_supported` | `failed_environment` | `execution_error` | ✓ ✓ ✓ |
| `synthetic_data_passage` | **`unverifiable_from_artifacts`** | `not_applicable` | **`evidence_undecidable`** | ✗ ✓ ✗ |

| Agreement with gold | Score |
| --- | --- |
| `support_label` | **10/11** |
| `reproduction_status` | **11/11** |
| `failure_mode` | **10/11** |
| **Wrong verdicts** | **0/11** |
| Conservative misses | 1/11 (`synthetic_data_passage`) |

Five of the six support labels and six of the eight reproduction statuses now appear on a
committed fixture. What remains unexercised end to end: `not_checked` (unreachable — the
check runner always emits an `evidence_presence` check), `failed_missing_data` and
`failed_missing_code` (a task naming an absent fixture file fails to *load*, so it cannot
be expressed), and `not_attempted` (reachable only via `--no-execute`). All four are
pinned by unit tests instead.

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

**A regression harness, not a benchmark.** Eleven hand-authored synthetic fixtures, whose
gold outcomes were written alongside the rules that score them. 10/11 does not mean
scientific claim verification is 91% solved. What the table shows is that the rule table
is coherent (no fixture needs a special case), that it never asserts a verdict gold
contradicts, and that the one claim its methods cannot read is *reported as unread*
rather than guessed at.

The four fixtures added in M8 are the closest thing here to a held-out test: they were
authored **after** the M7 rule table was frozen, to reach verdicts the original seven
never produced, and each landed on its hand-written gold outcome without a single change
to the extractor, the linker, the checks, or the rules. That is weak evidence — the same
agent wrote both, and the fixtures were designed with the rules in view — but it is
stronger than the seven that came before, where the rules were tuned as the fixtures were
written.

`reproduction_status` is 11/11 across all six statuses it can reach. Three fixtures
reproduce **exactly** (`mean(value) = 40.8/12 = 3.4`, `accuracy=0.80`,
`gc_content=0.50`); `dataset_std` reproduces *approximately* (pstdev = 1.1298967…, inside
the ±0.05 its one-decimal claim admits but not on it); `dataset_mean_overstated` fails
numerically; `unreproducible_accuracy` fails environmentally; and the five table and
passage claims correctly get `not_applicable` — reading a value out of a table cell is a
lookup, not a reproduction.

Traces are byte-identical across runs, including for the three fixtures whose scripts
actually execute. See `docs/SCORING.md` for every rule and its known limits.

## M8 — the offline smoke suite

```bash
python3 scripts/05_run_smoke_suite.py --out results/runs/     # 11 tasks, exit 0
claimverifier run-suite --out results/runs/                   # same
```

Eleven tasks, run end to end on a CPU with no network and no paid API, in ~1.5 s. The
suite writes a JSONL trace and a result JSON per task, plus `summary.csv`,
`summary.json`, and `summary.txt`, into `results/runs/smoke_suite/`.

| | |
| --- | --- |
| Tasks | 11 (`docs/PLAN.md` §11 asks for ≥ 8) |
| Checks run | 26 — 20 pass, 3 fail, 1 inconclusive, 1 error, 1 skipped |
| Scripts executed | 3, in the controlled sandbox |
| Support labels | 5 `supported`, 3 `contradicted`, 1 `partially_supported`, 1 `underspecified`, 1 `unverifiable_from_artifacts` |
| Gold agreement | support 10/11 · reproduction 11/11 · failure mode 10/11 |
| **Wrong verdicts** | **0** |
| Conservative misses | 1 (`synthetic_data_passage`), declared in the suite file |
| **Gate** | **PASS** (exit 0) |

### The suite is a gate, not a scoreboard

`run-suite` exits non-zero when the pipeline **regresses**, and the definition of
regression is deliberately asymmetric:

- Any **wrong verdict** — a committal support label the task's gold outcome disagrees
  with — fails the run. `tasks/smoke_suite.yaml` has no key that could declare one
  acceptable, so a suite file can never bless one. (A test asserts the schema rejects
  the field outright.)
- A **conservative miss** — the pipeline predicted `unverifiable_from_artifacts` or
  `not_checked` where gold commits — fails the run *only if the set of them changed*.
  The suite file names the standing misses; a new one is a regression, and a fixed one
  must be removed from the file rather than left to rot.

That asymmetry is the point. A change that raises label accuracy by turning a claim the
pipeline honestly declined to decide into one it decides *wrongly* has made the tool
worse, and a single accuracy number would have called it an improvement. The gate is
tested by injecting each failure in turn — a wrong verdict, a new miss, a stale declared
miss — and asserting it fails; a gate that never fails proves nothing when it passes.

A suite full of `contradicted` claims exits **0**. Finding a contradiction is the tool
working. And `--no-execute` does not gate at all: skipping the fixture scripts leaves
every code-reproduction claim undecided by its own artifacts, and the gold outcomes it
would be judged against assume the scripts ran. Reporting those label shifts as "wrong
verdicts" would blame the pipeline for the operator's flag.

### What is byte-reproducible, and what is not

Two runs of the suite into two different directories produce **byte-identical**
`*.trace.jsonl` (all 11), `summary.csv`, and `summary.json`. Exactly two artifacts
differ, in exactly one field each, and both are paths the caller chose:
`<task_id>.result.json` records its own trace's absolute `trace_path` (a Milestone 7
field), and `summary.txt` names the output directory. `summary.csv` refers to each trace
by filename alone, so it stays portable. This is asserted by a test that hashes every
artifact of two runs and diffs the two exceptions field by field.

### Worked example

```
$ claimverifier run-suite --out results/runs/
(abridged: the aggregate summary block is omitted)

Suite           : smoke_suite (Offline smoke suite) v1
Tasks           : 11
Fixture scripts : executed in the controlled sandbox
Artifacts       : results/runs/smoke_suite

Per-task verdict (support / reproduction / failure_mode); gold shown where it differs:
  [shy ] synthetic_data_passage   unverifiable_from_artifacts / not_applicable / evidence_undecidable
         gold: supported / not_applicable / none
  [ok  ] negated_training_data    contradicted / not_applicable / passage_does_not_assert
  [ok  ] accuracy_improvement     supported / not_applicable / none
  [ok  ] contradicted_f1          contradicted / not_applicable / table_cell_mismatch
  [ok  ] underspecified_split     underspecified / not_applicable / underspecified
  [ok  ] dataset_mean             supported / reproduced / none
  [ok  ] dataset_std              supported / approximately_reproduced / none
  [ok  ] dataset_mean_overstated  contradicted / failed_numeric_mismatch / statistic_mismatch
  [ok  ] recompute_accuracy       supported / reproduced / none
  [ok  ] gc_content               supported / reproduced / none
  [ok  ] unreproducible_accuracy  partially_supported / failed_environment / execution_error

Gate            : PASS
  No wrong verdicts, and the claims the pipeline declined to decide are exactly
  the ones the suite file declares. It asserted nothing its fixtures deny.
```

The tasks are ordered by evidence channel — text, table, dataset, code — so a failure
reads as *"the dataset channel broke"* rather than *"task 7 broke"*. The single `shy`
marker is the standing conservative miss, and the report prints the gold outcome it
missed rather than quietly scoring itself.

### How to read this

**Still a regression harness.** Eleven tasks is not a benchmark, `summary.csv` is not a
leaderboard, and the gate passing means *"this commit did not make the pipeline assert
something its own fixtures deny"* — nothing more. The suite's value is that it makes a
specific class of change impossible to land quietly: one that trades honesty for
accuracy.

Markdown and HTML **reports** are Milestone 9's. M8 emits machine-readable artifacts and
one rendered text summary; nothing here formats a report.

## M9 — reports, rendered from traces

```bash
python3 -m pytest tests/test_reports.py -q                                    # 98 tests
claimverifier report --run results/runs/smoke_suite --out results/reports/    # 11 + index
python3 scripts/04_generate_report.py --run results/runs/smoke_suite --format both --out results/reports/
```

Eleven auditable reports and an index, rendered from the eleven JSONL traces the smoke
suite wrote — about 5 KB of Markdown per claim, in under a tenth of a second, reading
nothing but the traces.

| | |
| --- | --- |
| Reports rendered | 11 + index, from 11 traces |
| Pipeline stages the renderer imports | **0** |
| Artifacts re-opened · checks re-run | **0** · **0** |
| Round trip (trace → `ScoredClaim`) | **exact on 11/11** — result, rules, signals, claim |
| Two run directories, reports beside traces | **byte-identical**; no absolute path in either |
| Formats | Markdown, and standalone HTML (no stylesheet, no JS, no network fetch) |
| Refusal tests | 12 (truncated, reordered, duplicated, foreign, schema-violating, …) |

### The round trip is the result

`docs/PLAN.md` §11 requires that *reports are generated from traces*. The only thing
separating that requirement from a slogan is a test that fails when it stops being true.
So `tests/test_reports.py` scores every committed fixture, writes its trace, reads it back
through `reports.reader`, and asserts the reconstructed M7 `ScoredClaim` **equals** the
original — result, the three named rules, every per-check signal, and the extracted claim.
If a later milestone records a fact in a result but not in its trace, the build breaks.

The renderer imports no pipeline stage, opens no artifact, re-runs no check, and does not
read `result.json`. A test deletes `result.json`, moves the lone trace into an empty
directory, and renders from it. A run archived months ago, whose papers and CSVs are long
gone, still reports.

### What had to change, and it was not the reader

`RunTrace.to_jsonl()` serializes the event stream and nothing else. A trace's `run_id`,
`task_id`, and `bundle_id` are real fields on the model that survived on disk **only in
the filename**, and `scoring.claim` recorded five of the extracted claim's fields rather
than all of them. A generator that claimed to "read the trace" would have been reading the
trace plus a guess about the path.

`SCHEMA_VERSION` moved `1.2` → `1.3`. **No model changed**; the event contract did. A
`scoring.run` event now opens every stream (`run_id`, `task_id`, `bundle_id`,
`schema_version`), `scoring.claim` carries the whole claim minus its evidence links (which
`scoring.evidence` already records — one fact, one place), and `scoring.result` no longer
repeats the version. The reader compares the **major** component: a `1.9` trace reads, a
`2.0` trace is refused, and a pre-`1.3` trace is refused *with an instruction* rather than
guessed at from its filename.

### Refusing to render is a feature

Twelve of the 98 tests assert that a bad trace produces a `ReportError` naming the file,
not a plausible-looking report: missing, empty, non-JSONL, truncated, reordered,
duplicated, foreign (a `sandbox.*` stream), schema-violating (`confidence: 7.0`), and
written under a future major version. Every object is re-validated through its pydantic
model on the way in, so the report cannot show a value the schema forbids.

`report` exits **0** on a `contradicted` claim, as `verify` does — reporting a
contradiction is the tool working.

### Worked example

The flagship fixture, abridged. `contradicted_f1`'s abstract asserts a number its own
results table denies, and the report keeps the two in **different sections**:

```markdown
## 2. Supporting text (retrieved evidence)

> Method B reaches an F1 score of 91.0 on MNLI.

- passage p_claim · score 1.000 · match=declared_source_passage; overlap=1.000; rank=1

## 3. Computed checks

| Status | Check | Target | Computed | Expected | Tolerance | Signal |
| --- | --- | --- | --- | --- | --- | --- |
| pass | evidence_presence | p_claim | verbatim | — | — | supports |
| fail | table_value | t_mnli[col=f1] | 86.0 | 91.0 | 0.05 | refutes |

## 4. Inference

- support_label: contradicted
  rule: artifacts_refute [c_contradicted_f1.table_value.1]
  because: the table does not hold the claimed value
```

Two columns that a lesser tool would make one: a check's **status** is a fact about the
check, its **signal** is what the check says about the *claim*, and one status maps to
more than one signal. An `evidence_presence` check that fails because the passage never
*mentions* the claim signals `undecided`, not `refutes` — silence is not refutation.

`synthetic_data_passage`'s report is the other one worth reading. It prints
`unverifiable_from_artifacts`, `confidence 0.00`, and the exact reason it could not decide
(`40% token coverage, missing ['model', 'only', 'trained']`). The word `contradicted`
appears nowhere in it, and a test asserts that.

### How to read this

**The measured facts here are structural, not scientific.** "11 reports rendered" says the
renderer runs; "round trip exact on 11/11" says the trace is a complete record of the
verdict. Neither says anything about whether the verdicts are correct — that is what
`summary.csv` is for, and a report deliberately never prints its task's gold outcome (see
`docs/REPORTS.md` §6). A report that scored itself would be answering a different
question.

## M10 — optional adapters (measuring the harness, not a model)

```bash
python3 -m pytest tests/test_adapters.py -q          # 70 tests
python3 scripts/06_record_llm_fixtures.py            # recordings are current
claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml --extractor recorded
```

The recorded adapter replays four committed, **hand-authored** synthetic responses and the
`LLMClaimExtractor` parses them through the same code the rule-based baseline is scored by:

| Fixture | Fields matched vs. gold |
| --- | --- |
| `accuracy_improvement` | 8 / 8 |
| `dataset_mean` | 6 / 8 (deliberately drops the `count` metric and the `n = 12` condition) |
| `underspecified_split` | 8 / 8 |
| `gc_content` | 8 / 8 (wrapped in a Markdown code fence, to exercise `strip_code_fence`) |
| **Total** | **30 / 32** |

That 30/32 measures exactly one thing — that a request is fingerprinted, replayed, parsed,
and scored faithfully — and **nothing at all** about any model's ability to extract a claim.
No API was called and no language model produced the responses; the model name
`recorded-fixture-v1` is fictitious so the fixture cannot imply otherwise (see
`data/fixtures/llm/README.md`). The one deliberate miss is what proves the scorer is
connected: a file of perfect answers would score 32/32 and demonstrate only the author's
generosity. The mock adapter returns an *empty* extraction on purpose (1/8, scored
`underspecified` downstream) — a mock that guessed would be a mock that lies.

The paid path is inert by construction, not by configuration. The `ApiAdapterStub` is the
only adapter even *capable* of a paid call (a test enumerates the registry and asserts
exactly one), and `build_adapter("api")` returns it disabled, in dry-run, with a $0.00 cost
guard and no transport. A live call requires four independent acts — flip `enabled`, set
`SCV_ENABLE_PAID_API=1`, register a price for the model (the repo ships none), and inject an
HTTP transport (the repo ships none, and a test asserts no module under `adapters/` and no
declared dependency imports one). Each gate is tested with a counting fake transport that a
default build never reaches. See `docs/ADAPTERS.md`.

## M11 — integration contracts (five exports, and one that replays)

```bash
python3 -m pytest tests/test_integrations.py -q                                    # 86 tests
claimverifier export --list
claimverifier run-suite --out results/runs/
claimverifier export --format episodes --run results/runs/smoke_suite --out ep.json
claimverifier replay --episodes ep.json --strict
```

Five versioned export formats, one per consumer role named in `docs/PLAN.md` §9:

| `--format` | Document | Consumer role | Reads |
| --- | --- | --- | --- |
| `runnable-tasks` | `scv.runnable-tasks` | code-agent runtime | `tasks/` |
| `evidence-records` | `scv.evidence-records` | BioScientist OS | a run's traces |
| `benchmark` | `scv.benchmark` | BioAgentBench | a suite run (traces + gold) |
| `metrics` | `scv.metrics` | LLM regression / observability | a suite run (traces + gold) |
| `episodes` | `scv.episodes` | agent-control-bench | a suite run + `tasks/` |

**No external schema was consulted.** None of those five systems was read, imported, or
run, so nothing here is a measurement of compatibility with any of them, and the word is
not used. What is claimed — and checked — is containment: a test parses every module under
`integrations/` and fails if it imports anything but the standard library, `pydantic`, and
this project. If a named repo wants different keys, the change is one ~200-line module and
a `format_version` bump.

### The result is the round trip

The only number in this section that measures anything beyond a shape:

```
$ claimverifier replay --episodes ep.json --strict

Episodes        : 11
Gate            : verdict + trace bytes (--strict)

  [ok   ] synthetic_data_passage   reproduced
  ... (10 more)

Reproduced      : 11/11
Result          : PASS
```

An episode pins the task file's hash, every artifact of its bundle by content hash, the
four controls, the recorded verdict, and the SHA-256 of the trace the run wrote. Replaying
it re-runs the whole pipeline — extraction, linking, checks, the three fixture scripts in
the sandbox — and compares. All eleven reproduce, and all eleven come back with a
**byte-identical trace**, which is what makes `trace_content_hash` a pin rather than a
courtesy. The property was established in M8 (`docs/RESULTS.md` §M8, "What is
byte-reproducible"); M11 is the first thing that depends on it.

### Four replay statuses, and only one of them blames the pipeline

| Status | Meaning | Injected in tests by |
| --- | --- | --- |
| `reproduced` | same inputs, same verdict | — |
| `drifted` | same inputs, **different verdict** | doctoring a recorded verdict |
| `inputs_changed` | a fixture, paper, or task file is not the recorded bytes | tampering with a content hash |
| `missing_task` | the task file is gone | pointing at a deleted path |

Collapsing the last three into "failed" would let an edited CSV read as a code regression,
which is precisely the mistake a replay harness exists to prevent. A gate that never fails
proves nothing when it passes, so each of the four is *injected* and shown to be caught.

`trace_digest_matches` is reported for every episode but gated only under `--strict`:
rewording one `because` string in the scoring rules changes every trace's bytes while every
verdict stands. That is the same asymmetry the smoke suite draws between a wrong verdict
and a conservative miss.

### The benchmark declares its metric, because the obvious one is wrong

`scv.benchmark` carries a `scoring` block naming `wrong_verdicts` (lower is better) as its
primary metric and `conservative_misses` as secondary, with a note that says **do not sum
them**. Label accuracy — the metric a harness reaches for by default — would score this
pipeline 10/11 and would score a version that guessed on its one honest refusal 11/11.

The export does not re-implement that judgement. It computes each task's bucket with the
same `TaskOutcome` object `suite.gate()` reads, so the exported `outcome` and the gate's
verdict cannot diverge. Over the eleven committed fixtures the export carries **0 wrong
verdicts and 1 conservative miss** (`synthetic_data_passage`), which is exactly what
`summary.txt` says.

Predicted verdicts come from the traces; gold comes from `summary.json`, because a trace
never carries gold — gold is never an input to the run that wrote it. The two are
cross-checked, and a run directory whose traces and summary disagree is **refused rather
than scored**: it holds artifacts from two different runs, and any number computed from it
is a fiction.

### A fixed key space is the whole of an observability contract

`scv.metrics` emits **40 metrics on every run**, covering every value of every closed
vocabulary — 6 support labels, 8 reproduction statuses, 13 failure modes, 5 check statuses
— zero-valued when unseen. A key that *appears* between two runs is a key a diff tool has
to guess about, and it will guess wrong in one of the two available directions.

| Metric | Value | Direction |
| --- | --- | --- |
| `tasks` | 11 | neutral |
| `checks_total` | 26 | neutral |
| `mean_confidence` | 0.848485 | neutral |
| `gold_support_agreement` | 10 | higher is better |
| `gold_reproduction_agreement` | 11 | higher is better |
| `conservative_misses` | 1 | **lower is better** |
| `wrong_verdicts` | **0** | **lower is better** |

Only six of the forty declare a direction. `checks_fail` is `neutral` on purpose: a suite
of contradicted claims *should* produce failing checks, and a regression tool that treated
that as a regression would punish the tool for working. The reference `compare()` refuses
two documents whose key sets differ rather than intersecting them, and a test drives the
scenario this project is arranged around — a conservative miss turning into a wrong
verdict, with gold agreement unchanged. Accuracy calls it a wash; `compare()` flags
`wrong_verdicts`.

### What the exports do not carry, and why

`evidence-records` keeps the five audit channels as five sibling keys (`claim`, `evidence`,
`checks`, `verdict`, `unverifiable`), plus the named rule behind each verdict field. It
deliberately omits `VerificationCheck.inputs` — the per-check debugging bag whose keys vary
by check type and which, for `code_execution`, holds captured stdout. A stable contract
cannot carry a field whose shape is decided by whichever check happened to write it, and an
evidence store is the last place that should start holding process output by accident. A
test asserts the string `accuracy=0.80` — real stdout from a fixture script, present in the
trace — appears in no exported record.

Every export is a function of committed artifacts: sorted-key JSON, no wall clock, no RNG,
byte-identical across two exports *and* across two run directories. A test walks every
string of every document and fails on an absolute path, because a document carrying
`/home/someone/checkout` is a document about one machine.

### The gap this milestone did not close

A schema-1.3 trace records what the pipeline **computed**, not how an operator **invoked**
it, so it carries none of the four controls (`execute`, `use_declared_source`, `abs_tol`,
`rel_tol`). `export --format episodes` recovers `execute` from the one artifact that does
record it — a suite `summary.json` — and *refuses* when the operator's declared
`--no-execute` disagrees with it. The other three are taken from the operator's flags.

A wrongly declared control does not silently lie: replaying the episode reports `drifted`
and names the field. But it is an assumption, and removing it means recording the controls
in the trace (a `scoring.controls` event, schema 1.4). That is a schema change, and it
belongs to the milestone that needs it. See `docs/INTEGRATIONS.md`.

## Test and lint status

```bash
python3 -m pytest -q     # 756 passed
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
| M8 | 48 | 500 |
| M9 | 100 | 600 |
| M10 | 70 | 670 |
| M11 | 86 | 756 |

All tests are CPU-only and offline; none touch the network, and no paid API is
used anywhere in the default path. M5's, M6's, M8's, M9's, and M11's tests execute
committed, stdlib-only fixture scripts (plus a few written by the tests themselves) as
child processes — local, harmless, and offline. M11's replay tests are the most expensive:
they drive the whole pipeline over the eleven fixtures once. The socket tests either construct a socket or
are refused before one exists; none of them connects to anything.

Two tests are load-bearing on the wall clock: the CPU-limit test burns ~1 CPU-second
and the process-group test waits ~1 s for its timeout. Both assert that something was
*killed*, so a slow machine makes them more likely to pass, not less.
