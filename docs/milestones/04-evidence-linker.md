# M4 — Evidence linker

## Summary

Introduces the `evidence/` package and `claims/linking.py`: given a **populated**
claim (the M3 extractor's output) and an `ArtifactBundle`, the linker emits scored
`EvidenceLink` provenance records naming exactly where in the bundle the claim's
evidence lives — one passage, plus any table cells/columns, dataset columns, code
files, and figure series it resolves to.

The organising principle is that **a link retrieves evidence; it does not judge
it.** A passage can be linked with a high score and contradict the claim; a table
column is linked *precisely because* no cell matches the claimed value, since
otherwise a `contradicted` verdict could never be reached. Deciding whether linked
evidence *asserts* a claim is the `evidence_presence` check (M5). Keeping the two
apart is what lets the report show *supporting text* and *computed check* as
separately auditable channels.

## Deliverables

- **`src/scientific_claim_verifier/evidence/`** (new package, per `docs/PLAN.md` §5):
  - `__init__.py` — the `MatchMethod` vocabulary (the named rule behind every link).
  - `passages.py` — tokenizer, stopwords, Dice overlap, exact lookup, sentence
    quoting, full passage ranking, and the selection floor.
  - `tables.py` — header→metric matching, label-column detection, the **row rule**,
    and cell/column/whole-table locators.
  - `datasets.py` — identifier-column rejection and measured-column selection.
  - `code_refs.py` — filename and sole-artifact resolution, stdout observable.
  - `figures.py` — series and sole-figure-mention resolution.
- **`src/scientific_claim_verifier/claims/linking.py`** — the `EvidenceLinker`, the
  `Linking` result (links + the *full* passage ranking + `rules_fired`), the
  strict/loose scorer against gold evidence, text/JSON rendering, and the CLI.
- **CLI:** `claimverifier link-evidence --task X [--out DIR] [--json]
  [--no-declared-source]`.
- **Tests:** `tests/test_linking.py` (69) — unit tests per channel on synthetic
  bundles, plus integration over all six fixtures scored against gold.
- **Docs:** `docs/EVIDENCE_LINKING.md` (new, channel-by-channel reference with
  limits); `docs/RESULTS.md` (M4 results); `docs/EXTRACTION.md` (cross-links).
- **Website:** `index.html`, `milestones.html`, `checks.html`, `results.html`.

## Design decisions

- **A cell link requires the claim to name the row.** Given *"The method reaches
  90% accuracy"* and a table of `dev 90.0` / `test 82.0`, the value matches exactly
  one cell — but linking `row=dev` would silently attribute the claim to a split it
  never mentioned, burying the underspecification inside a confident-looking
  locator. The linker emits `col=accuracy` instead, leaving the claim visibly
  ambiguous over the column. That ambiguity is the signal M7 needs to label it
  `underspecified`. Conversely *"Method A improves … over the baseline"* names both
  rows, so both cell locators are justified and emitted.
- **A metric column is linked even when no cell matches.** Otherwise a
  `contradicted` claim would have nothing to check against.
- **Dice, not containment, for passage overlap.** Containment (`|C∩P|/|C|`) rewards
  a passage merely for being long. Dice is symmetric, bounded, and penalizes
  padding; the case where a long passage really does state the claim is already
  covered by the verbatim channel.
- **Asserted provenance is labelled, not laundered.** A task's declared
  `claim.source_passage` makes passage linking trivially correct, so the link is
  tagged `match=declared_source_passage` and still carries the passage's *measured*
  overlap. `--no-declared-source` runs the linker blind; that is the setting the
  reported numbers use, because it is the only one that measures retrieval.
- **Exactly one passage is linked, but the whole ranking is kept.** The runners-up
  and their scores stay in the `Linking` result, the report, and the JSON artifact.
- **`score` is retrieval confidence, not a support probability.** `1.0` for any
  deterministic identifier match (declared source, verbatim text, resolved artifact
  id, located cell); the Dice value for a keyword-matched passage. Locator
  *granularity* is carried by the `locator`, not by an invented number.
- **The linker declines rather than guesses.** A dataset with several non-identifier
  columns and a claim naming none of them → dataset linked, no column locator. A
  reproduction claim with several scripts and no filename → **no** code link (that
  is `failed_missing_code`, a real reportable state). A passage below the 0.05 floor
  → no passage link.
- **`quote` is not scored against gold.** Gold quotes are hand-trimmed spans; the
  linker quotes the best-matching whole sentence. Same reasoning as M3's decision
  not to score `normalized_claim` — a rule-based system reproducing hand-authored
  phrasing would be overclaiming.
- **Reuse over duplication.** `evidence/tables.py` imports the extractor's
  `extract_metrics` so a table header and a claim metric canonicalize through one
  lexicon; `evidence/datasets.py` imports `resolve_dataset_reference` (promoted from
  M3's private `_resolve_dataset`) so a dataset mention resolves identically
  everywhere. Import direction is `evidence → claims.extraction` only; nothing in
  `claims.extraction` imports `evidence`, so the graph stays acyclic.
- **No new numbered script.** `docs/PLAN.md` §5 reserves `scripts/03_run_checks.py`
  for M5. `link-evidence` is a CLI subcommand only — an addition beyond the §10
  contract, which lists the end-to-end verbs.
- **`figures.py` ships without a fixture.** `EvidenceKind.FIGURE` and the
  extractor's "Figure N" detection already exist; a mention that silently resolved
  to nothing would be a hole in the audit trail. Unit-tested against synthetic
  figures, and labelled as such.

## Validation

Commands run (CPU-only, offline):

| Command | Result |
| --- | --- |
| `python3 -m pytest -q` | 171 passed (102 prior + 69 new) |
| `ruff check .` | All checks passed |
| `python3 scripts/01_validate_fixtures.py` | 6 ok, 0 failed, 0 warnings — VALID (exit 0) |
| `python3 scripts/00_check_environment.py` | exit 0 — `READY` |
| `claimverifier link-evidence --task <task>` | text/JSON report, exit 0 |

### Evidence linking vs. gold, blind, over the six committed fixtures

Strict keys — `(kind, target_id, locator)`, so the right *cell or column*, not just
the right table:

| Task | Gold links | Recovered | Spurious |
| --- | --- | --- | --- |
| `accuracy_improvement` | 3 | 3 | 0 |
| `dataset_mean` | 2 | 2 | 0 |
| `gc_content` | 2 | 2 | 0 |
| `recompute_accuracy` | 2 | 2 | 0 |
| `synthetic_data_passage` | 1 | 1 | 0 |
| `underspecified_split` | 2 | 2 | 0 |
| **total** | **12** | **12** | **0** |

Strict precision 1.00, recall 1.00. The declared-source setting gives the same
12/12 (it changes the passage link's method, not its target).

**Read this as a consistency check, not a benchmark.** The locator conventions and
the row rule were written with the two committed table fixtures in view. 12/12
means *the linker reproduces the hand-authored provenance exactly and invents
nothing* — a real property, and the one M5 depends on — not that retrieval is
solved.

The informative numbers are the passage overlaps, the only channel not forced by an
identifier:

| Task | Best | Overlap | Runner-up | Overlap |
| --- | --- | --- | --- | --- |
| `synthetic_data_passage` | `p_data` | **0.211** | `p_hardware` | **0.000** |
| `accuracy_improvement` | `p_results` | 0.824 (verbatim) | `p_setup` | 0.308 |
| `underspecified_split` | `p_headline` | 1.000 (verbatim) | `p_detail` | 0.154 |

`synthetic_data_passage` is the one fixture where overlap is load-bearing: the
claim appears nowhere verbatim, and the linker must separate a paraphrasing passage
(0.211, on two shared tokens) from a compute-hardware distractor (0.000). It does —
but 0.211 is a low absolute score, and the margin exists because the distractor is
*completely* unrelated. A distractor sharing vocabulary without asserting the claim
would not be separated by a bag-of-words baseline. That limit is documented, and it
is why `evidence_presence` is a separate check.

The tests also pin: tokenization of hyphenated names, decimals, and filenames;
stopword removal that *keeps* negation and quantifiers; Dice symmetry and bounds;
verbatim matching across YAML line-wrapping; exact-text outranking a rival with
perfect token overlap; the deterministic tie-break; the selection floor; the full
table row rule including its documented false positive; measured-column selection
and its refusal to guess; code resolution by filename, by sole artifact, and its
refusal when ambiguous; figure series matching; linker purity (the input claim is
never mutated) and determinism; strict-vs-loose scoring semantics; and all five CLI
paths.

## Status

**Complete.** Next: **M5 — Verification checks** (table value, dataset statistic
recomputation, numeric tolerance, comparison, evidence presence, and code execution
for tiny scripts), which consume exactly the locators this milestone emits.
