Human review: M4 — Evidence linker

TL;DR
Milestone 4 adds the `evidence/` package (passages, tables, datasets, code_refs,
figures) and `claims/linking.py`: given a populated `ScientificClaim` and an
`ArtifactBundle`, the `EvidenceLinker` emits scored `EvidenceLink` provenance
records naming exactly where the claim's evidence lives — one passage, plus any
table cells/columns, dataset columns, code files, and figure series. Passage
retrieval is exact verbatim lookup plus a Dice keyword-overlap baseline that ranks
every passage; tables use a "cell only if the claim names the row" rule so an
underspecified claim links a column rather than inventing a row. Every link carries
a retrieval score, a locator, and the named rule that produced it. Blind of the
task's declared `source_passage`, the linker recovers 12/12 gold links with 0
spurious across the six fixtures. 69 new tests (171 total). No new dependencies.
The linker retrieves; it never judges — whether a linked passage *asserts* the
claim is the `evidence_presence` check (M5).

What changed
- New package: src/scientific_claim_verifier/evidence/ (__init__.py with the
  MatchMethod vocabulary, passages.py, tables.py, datasets.py, code_refs.py,
  figures.py).
- New module: src/scientific_claim_verifier/claims/linking.py (EvidenceLinker, the
  Linking result, strict/loose scorer, rendering, CLI entry point).
- CLI: `link-evidence --task X [--out DIR] [--json] [--no-declared-source]`.
- claims/extraction.py: `_resolve_dataset` promoted to the public
  `resolve_dataset_reference` (the linker reuses it); the reference-report line now
  points at `claimverifier link-evidence` instead of "scored linking is M4".
- Tests: tests/test_linking.py (69 tests).
- Docs: docs/EVIDENCE_LINKING.md (new, channel-by-channel reference + limits),
  docs/RESULTS.md (M4 results), docs/EXTRACTION.md (cross-links), milestone and
  commit notes.
- Website: site/index.html, site/milestones.html, site/checks.html,
  site/results.html.

What should be checked later
- `EvidenceLink` has no typed field for the match method. The rule is written into
  the free-text `notes` as `match=table_cell; value=78`. M5 and M7 will want to
  branch on it (a declared-source passage is weaker evidence than a verbatim one;
  a column link means "ambiguous", a cell link means "located"). Confirm whether
  `MatchMethod` should be promoted to a typed `EvidenceLink.match_method` field in
  the schema rather than parsed back out of a string.
- The table **row rule** and the locator conventions (`row=…,col=…`, `col=…`,
  `column=…`, `stdout`) were written with the two committed table fixtures in view.
  The 12/12 is therefore a consistency check, not a benchmark. Confirm the rule
  generalizes, and consider adding held-out table fixtures the rule was *not*
  written against before trusting the number.
- `claim_names_row` has a known false positive, test-pinned: case-sensitivity
  cannot separate the row label `A` from a sentence-initial article ("A method
  reaches 90% accuracy" names row `A`). Confirm whether one-character labels should
  require an entity match rather than falling back to the claim text.
- Cell matching uses `math.isclose(rel_tol=1e-9)`. A claim of 78.0 against a cell
  of 78.04 therefore links the *column*, not the cell. That is arguably right (the
  linker should not decide what "close enough" means — M5 owns tolerance), but it
  means a rounding difference in a fixture silently coarsens the locator. Confirm.
- Exactly one passage is linked. Every gold fixture has exactly one, so this is
  untested against a claim that genuinely needs two. Confirm whether multi-passage
  support (all candidates above a threshold?) is wanted, and if so what the
  threshold means.
- `MIN_PASSAGE_SCORE = 0.05` is a floor, not a support threshold. The lowest true
  positive on the fixtures scores 0.211, so the margin is ~4x, but the value is
  otherwise unmotivated. Confirm the floor should exist at all, given that a passage
  clearing it can still contradict the claim.
- Dice (`2|C∩P|/(|C|+|P|)`) was chosen over containment (`|C∩P|/|C|`) because
  containment rewards long passages. Confirm — containment is arguably the more
  semantically apt score for "does this passage contain what the claim says", and
  the verbatim channel may not fully cover the long-passage case.
- `EvidenceLinker(use_declared_source=True)` is the **default**. The M8 smoke suite
  must decide which setting it runs under: with the declared source, passage linking
  is trivially correct and end-to-end numbers will look better than the system
  deserves. Recommend the suite runs blind, or reports both. Confirm.
- `label_column_index` takes the *first* all-string column as the row label. A
  table whose first column is a free-text note would mislabel every row. No fixture
  has this. Confirm whether the label column should be declared in the schema.
- `resolve_dataset_reference` is an unanchored substring match against
  `"<artifact_id> <description>"` (flagged in the M3 review, unchanged here, now
  used by two callers). A short dataset name could match an unrelated description.
- Import direction: `evidence/tables.py` and `evidence/datasets.py` import from
  `claims/extraction.py` (to share the metric lexicon and the dataset resolver),
  while `claims/linking.py` imports `evidence/*`. The graph is acyclic and this was
  chosen over duplicating the lexicons, but it inverts the `claims -> evidence`
  arrow in the PLAN §5 diagram. Confirm the layering, or move the shared lexicons
  into a neutral module.
- `evidence/figures.py` has **no committed fixture** — it is unit-tested against
  synthetic figures only. It exists so an extractor-detected "Figure N" mention does
  not silently resolve to nothing. Confirm whether a figure fixture should be added
  in M5 (which owns `figure_recompute`) or the module deferred.
- The sentence splitter breaks on terminal punctuation followed by whitespace, so
  an abbreviation ("Fig. 1") splits a sentence. It only affects the `quote` shown in
  reports, never a link target. Confirm the quote strategy (best-matching whole
  sentence) is what reports should show.
- Loose scoring keys on `(kind, target_id)` and compares as **sets**, so predicting
  one cell where gold has two cells of the same table scores loose-exact. The strict
  score is the one to read. Confirm both are worth keeping.

Technical risks
- Low. The linker is pure, deterministic, offline, and stdlib-only (`re`, `math`).
  It reads no artifact files beyond what the M2 loader already read, and it executes
  nothing.
- The linker never mutates its input claim (test-pinned) and produces identical
  links, rankings, and `rules_fired` across runs (test-pinned).
- The main risk is not correctness but **overfitting to six hand-authored
  fixtures**, called out in docs/EVIDENCE_LINKING.md, docs/RESULTS.md, and the
  milestone note rather than hidden. Only one fixture (`synthetic_data_passage`)
  exercises the overlap baseline with a distractor present, and it wins by 0.211 vs
  0.000 — a wide margin only because the distractor shares no vocabulary at all.
- The keyword baseline has no model of negation: a passage stating the *opposite* of
  the claim scores identically to one asserting it. This is by design (retrieval is
  not judgement) but is load-bearing — if M5's `evidence_presence` check is weak, a
  contradicting passage could be reported as supporting text.
- `--out` writes under `results/runs/`, which is gitignored; nothing generated is
  committed.

Commands to verify
- python3 -m pytest -q
- python3 -m pytest tests/test_linking.py -q
- ruff check .
- python3 scripts/01_validate_fixtures.py
- claimverifier link-evidence --task tasks/table_claims/accuracy_improvement.yaml   (after `pip install -e .`)
- claimverifier link-evidence --task tasks/ml_claims/synthetic_data_passage.yaml --no-declared-source
- claimverifier link-evidence --task tasks/ml_claims/underspecified_split.yaml --no-declared-source
- claimverifier link-evidence --task tasks/statistical_claims/dataset_mean.yaml --json
- ./scripts/serve_site.sh   then load http://localhost:9002/checks.html and results.html

Human feedback
<!-- Human will fill this later. -->
