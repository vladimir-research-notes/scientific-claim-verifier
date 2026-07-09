# Milestone 12 — Portfolio report

## Summary

README and docs brought to portfolio quality: problem, architecture, worked example,
smoke-suite results, reproduction commands, limitations, and the future research path.

Four documents that `docs/PLAN.md` §5 has named in its repository map **since bootstrap**
were written for the first time: `METHODOLOGY.md`, `LIMITATIONS.md`, `REPRODUCIBILITY.md`,
and `PAPER_PATH.md`. All four had been missing for twelve milestones. The website's
`roadmap.html` promised `docs/PAPER_PATH.md` *by name*, and `results.html` promised
`docs/REPRODUCIBILITY.md`, while neither file existed. Nothing caught it.

So the milestone's real deliverable is not the prose. It is `tests/test_docs.py`: the
portfolio claims are now artifacts the build checks, and a document that drifts from the
code fails `pytest`.

**Nothing on the default path changed.** No verdict, check, rule, fixture, schema, or
export moved. The smoke gate is unchanged, and it should be.

## Deliverables

- `docs/METHODOLOGY.md` (new) — the design commitments the per-stage docs assume: the five
  audit channels, the **stage contract** (each stage is structurally incapable of doing the
  next stage's job), status-vs-signal, rule-based inference, report-as-a-function-of-trace,
  the asymmetric gate, determinism as a precondition, and every method labelled a heuristic.
- `docs/LIMITATIONS.md` (new) — the canonical limitations list, consolidating what was
  scattered across the per-stage docs and `site/limitations.html`, plus three gaps that were
  documented nowhere central: `figure_recompute` is named but unimplemented, four vocabulary
  values are unreachable end to end, and a schema-1.3 trace records what the pipeline
  computed rather than how it was invoked.
- `docs/REPRODUCIBILITY.md` (new) — environment, the command for every number in
  `docs/RESULTS.md`, what is byte-reproducible and what is not, and a **machine-checked table
  of fifteen headline numbers**.
- `docs/PAPER_PATH.md` (new) — what would have to be true to publish any of this: the
  repository is a systems/auditability contribution, not an NLP result; three studies in
  dependency order (a real annotated claim set, baselines, and the ablation that could
  *falsify* the central design claim); the metric argument and its honest counterweight;
  threats to validity; permanent non-goals.
- `tests/test_docs.py` (new, 122 tests) — the documentation gate.
- `README.md` — restructured: problem → worked example → architecture → results → reproduction
  → CLI → limitations → research path → build/permissions/site/layout/doc index.
- `docs/RESULTS.md` — M12 section, status row, test table (878).
- Website: `index.html` (status), `milestones.html` (M12 done), `results.html` (the numbers
  cannot rot), `roadmap.html` (the research path, now written), `limitations.html` (canonical
  pointer, built-but-unexercised, adapters).

## Validation

- `python3 -m pytest -q` → **878 passed** (756 prior + 122 new).
- `python3 -m ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 12 ok / VALID (unchanged).
- `python3 scripts/05_run_smoke_suite.py --out results/runs/` → gate **PASS**, exit 0
  (unchanged; nothing on the default path changed).
- All 12 site pages + `style.css` fetched via `urllib` → 200, balanced tags, `<title>` present.
- The headline gate was checked for **sensitivity**, not just for passing: doctoring
  `wrong_verdicts` from `0` to `7` in the document makes the test compare 7 against a live 0,
  and garbling the table yields `{}`, which the completeness assertion rejects. A gate that
  cannot fail proves nothing when it passes — the same principle M8 applied to the suite gate
  and M11 to replay.

## What the documentation gate checks

| Check | How |
| --- | --- |
| Every document the plan promises exists | `docs/PLAN.md`'s repository map is **parsed**, not trusted |
| Every relative Markdown link resolves | 59 documents (README + `docs/**.md`) |
| Every relative website link and nav entry resolves | 12 pages |
| Every `claimverifier <verb>` the docs invoke is real | verbs read off `cli.build_parser()` |
| Every CLI command is documented somewhere | the converse direction |
| Every `scripts/*.py` the docs reference exists | |
| The 15 headline numbers in `REPRODUCIBILITY.md` | **re-derived from a live suite run** |
| Every milestone has its three notes, numbered without gaps | `milestones/`, `commits/`, `review_notes/` |
| No review note claims a review that has not happened | `CLAUDE.md`'s placeholder contract |

## Notes / decisions

- **A docs milestone whose only output is prose is unverifiable**, and `CLAUDE.md`'s quality
  bar forbids that: *every substantive claim must be backed by a test, an example, a trace, a
  result table, a documented limitation, or an explicit non-goal.* Documentation is where that
  bar is easiest to miss, because prose does not fail a build. Now it does.
- **The plan's map is parsed rather than mirrored into a hand-maintained list.** A list would
  have to be updated by the same person who forgot to write the document. Parsing means the
  next promise is checked the moment it is made.
- **The rule's direction is pinned by a test of its own.** Later milestones added docs the map
  never named (`EXTRACTION.md`, `SANDBOX.md`, `INTEGRATIONS.md`, …), so `promised ⊆ present`,
  not equality. `test_the_plan_promises_every_top_level_document_that_exists` asserts the
  inclusion is strict and says, in its own body, to delete itself if that ever stops holding —
  so a future reader does not "fix" it into a build break for no reason.
- **Two numbers are deliberately excluded from the machine-checked table.** The **test count**:
  a test asserting how many tests exist is self-referential and rots on contact with its own
  success. **Wall-clock timing**: ~1.5 s (suite) and ~23 s (tests) are reported as
  approximations everywhere and asserted nowhere, because a machine-dependent number that a
  test pins is a test that fails on a slower machine for no reason. Both exclusions are stated
  in the document itself, not just here.
- **`test_every_command_is_documented_somewhere` runs in the converse direction** on purpose. A
  verb no document mentions is a verb nobody knows about; the forward direction alone would let
  the CLI grow silently.
- **`PAPER_PATH.md` argues against the repository's own numbers.** It names the falsifying
  experiment — ablate the status/signal separation and measure the induced wrong verdicts — and
  states that if the predicted errors do not appear on a real corpus, the central design claim
  of this project is wrong and should be withdrawn. It also concedes the primary metric's flaw:
  `wrong_verdicts` alone is **gameable by silence**, since a system labelling everything
  `unverifiable_from_artifacts` scores zero. That is why the two numbers must always be reported
  together and never summed — and why §3 lists that degenerate baseline explicitly.
- **Three limitations were promoted from module docstrings to a canonical document**, where a
  reader looking for what the system cannot do will actually find them: `figure_recompute` named
  but unimplemented (no check, no fixture); `not_checked` / `failed_missing_data` /
  `failed_missing_code` / `not_attempted` unreachable end to end; the four controls absent from a
  schema-1.3 trace.
- **The site's two stale promises are now kept.** `roadmap.html` said the research path "will be
  maintained in `docs/PAPER_PATH.md`" and `results.html` said the commands "will live in
  `docs/REPRODUCIBILITY.md`". Both files exist, both pages now link to real content, and
  `test_every_relative_markdown_link_resolves` plus the website link test keep them honest.

## Status

Complete. Next: Milestone 13 — Final cleanup.
