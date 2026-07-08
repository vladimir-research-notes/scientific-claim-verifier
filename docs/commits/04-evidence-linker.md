# Commit note — M4 Evidence linker

## Commit message

```
M4: evidence linker (exact lookup, overlap baseline, scored provenance)

Add the evidence/ package and claims/linking.py, which turn a populated
ScientificClaim plus an ArtifactBundle into scored EvidenceLink provenance
records naming exactly where the claim's evidence lives:
- evidence/passages.py: tokenizer + stopwords, Dice overlap, exact verbatim
  lookup, sentence quoting, full passage ranking, selection floor
- evidence/tables.py: header->metric matching via the extractor's lexicon,
  label-column detection, the row rule, cell/column/whole-table locators
- evidence/datasets.py: identifier-column rejection, measured-column choice
- evidence/code_refs.py: filename and sole-artifact resolution, stdout observable
- evidence/figures.py: series and sole-figure-mention resolution
- claims/linking.py: EvidenceLinker, the Linking result (links + the full
  passage ranking + rules_fired), and a strict/loose scorer against gold

Wire `claimverifier link-evidence --task X [--out DIR] [--json]
[--no-declared-source]`. Promote extraction._resolve_dataset to the public
resolve_dataset_reference so the linker resolves dataset mentions through the
same function. Add tests/test_linking.py (69 new, 171 total) and
docs/EVIDENCE_LINKING.md; update RESULTS, EXTRACTION, README, website
(index, milestones, checks, results), and milestone/commit/review notes.

A link retrieves evidence; it does not judge it. A cell locator is emitted only
when the claim NAMES the row - "the method reaches 90% accuracy" against a
dev/test table links col=accuracy, not row=dev, so the underspecification stays
visible instead of hiding inside a confident locator. A metric column is linked
even when no cell matches, so a contradiction stays checkable. Blind of the
declared source_passage, the linker recovers 12/12 gold links with 0 spurious
across the six fixtures; the declared-source setting is labelled as asserted
provenance, not laundered into a retrieval result. Whether a linked passage
ASSERTS a claim is the evidence_presence check (M5).
```

## What this commit adds

- Five independently-testable evidence channels, each returning matches tagged
  with the named `MatchMethod` rule that produced them.
- A linker whose emitted links carry a retrieval score, a locator precise enough
  for M5 to read the value back, and an audit note naming the rule.
- The complete ranked passage list — not just the winner — in the result, the
  report, and the JSON artifact.
- A strict/loose scorer against the gold `expected.evidence` introduced in M2,
  plus the second measured results table in the repo.
- `claimverifier link-evidence`, offline, with a `--no-declared-source` mode that
  makes the retrieval measurable rather than trivially correct.

## Deliberately excluded (per the operating principles)

- **Judging support.** No link asserts that the claim is true. `evidence_presence`,
  the value checks, and the support label are M5 and M7. A high-scoring passage may
  contradict the claim; the linker cannot tell, and does not pretend to.
- **Smarter retrieval.** No stemming, no embeddings, no synonymy. `trained` does
  not match `training`. The bag-of-words limits are documented and pinned rather
  than papered over; a stronger retriever drops in behind the same interface.
- **Guessing a row, a column, or a script.** Where the claim does not justify a
  choice, the linker emits the coarser locator, or no link at all. `failed_missing_code`
  is a real reportable state.
- **Scoring `quote` against gold.** Gold quotes are hand-trimmed spans; the linker
  quotes whole sentences. Same call as M3 made for `normalized_claim`.
- **A numbered script.** `docs/PLAN.md` §5 reserves `scripts/03_run_checks.py` for
  M5; `link-evidence` is a CLI subcommand only.
- **New dependencies.** Pure stdlib `re`/`math` on top of the existing
  pydantic/PyYAML. numpy/pandas still arrive with M5.

## Verification performed at commit time

- `python3 -m pytest -q` → 171 passed (102 prior + 69 new).
- `ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 6 ok, 0 failed, 0 warnings (exit 0).
- `python3 scripts/00_check_environment.py` → exit 0 (`READY`).
- `claimverifier link-evidence` on all six tasks, blind and with the declared
  source → 12/12 gold links, 0 spurious, exit 0; `--out` writes
  `<task_id>.linking.json` under the gitignored `results/runs/`.
- `claimverifier extract-claims` re-run after the `resolve_dataset_reference`
  rename → unchanged output, 8/8 scored fields.
- Static site served locally on port 9002; pages fetched via Python's `urllib`
  (no `curl`/`wget`, per the permission policy).
- `git status` clean after commit.
