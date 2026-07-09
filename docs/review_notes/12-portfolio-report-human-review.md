Human review: Milestone 12 — Portfolio report

TL;DR
README and docs brought to portfolio quality. Four documents that `docs/PLAN.md` §5 has named in
its repository map since bootstrap — `METHODOLOGY.md`, `LIMITATIONS.md`, `REPRODUCIBILITY.md`,
`PAPER_PATH.md` — were written for the first time. All four had been missing for twelve
milestones; `site/roadmap.html` promised `docs/PAPER_PATH.md` by name and `site/results.html`
promised `docs/REPRODUCIBILITY.md`, while neither file existed, and nothing caught it.

Because a docs milestone whose only output is prose is unverifiable, the real deliverable is
`tests/test_docs.py` (122 tests): the plan's map is *parsed* and every document it promises must
exist; every relative link in 59 Markdown docs and 12 website pages must resolve; the docs may
invoke only real `claimverifier` verbs, and every verb must be documented somewhere; and the
fifteen headline numbers in `docs/REPRODUCIBILITY.md` are **re-derived from a live suite run**, so
a document that drifts from the code fails `pytest`.

878 tests total; ruff clean; fixtures valid; smoke gate PASS and unchanged. **Nothing under
`src/` changed** — no verdict, check, rule, fixture, schema, or export moved.

What changed
- New: `docs/METHODOLOGY.md`, `docs/LIMITATIONS.md`, `docs/REPRODUCIBILITY.md`,
  `docs/PAPER_PATH.md`, `tests/test_docs.py`.
- Rewritten: `README.md` (problem → worked example → architecture → results → reproduction → CLI
  → limitations → research path → build/permissions/site/layout/doc index).
- Updated: `docs/RESULTS.md` (M12 section, status row, test table), `site/index.html`,
  `site/milestones.html`, `site/results.html`, `site/roadmap.html`, `site/limitations.html`.
- Promoted to a canonical document three limitations previously living only in module docstrings:
  `figure_recompute` is a named `CheckType` with no implementation and no fixture; four vocabulary
  values (`not_checked`, `failed_missing_data`, `failed_missing_code`, `not_attempted`) are
  unreachable end to end and pinned by unit tests instead; a schema-1.3 trace records what the
  pipeline computed, not how an operator invoked it.

What should be checked later
- **Is `docs/PAPER_PATH.md` honest enough, or still too flattering?** It claims the repo is a
  systems/auditability contribution rather than an NLP result, concedes that `10/11` is unanchored
  by any baseline, and concedes that the declared primary metric (`wrong_verdicts`) is **gameable
  by silence** — a system labelling everything `unverifiable_from_artifacts` scores zero. It names
  the experiment that could *falsify* the project's central design claim (ablate the status/signal
  separation; measure induced wrong verdicts) and says the claim should be withdrawn if the
  predicted errors do not appear. Please push on whether that framing is still too generous.
- **Is the headline table the right set of fifteen numbers?** It excludes the test count
  (self-referential) and wall-clock timing (machine-dependent). Both exclusions are argued in the
  document. A reviewer may think `mean_confidence` or the per-label distribution belongs there too.
- **Is parsing `docs/PLAN.md`'s ASCII repository map too clever?** The alternative is a
  hand-maintained list in the test, which would have to be updated by the same person who forgot to
  write the document. The parse is guarded: it asserts it found ≥ 11 names before concluding
  anything, so a reformatted map fails loudly rather than vacuously passing.
- **`test_the_plan_promises_every_top_level_document_that_exists`** asserts `promised ⊂ present`
  strictly, and instructs its own deletion if the map ever names every doc. That is unusual; a
  reviewer may prefer it simply be removed now.
- The README quotes CLI output. Each block was re-run and matched against real output at commit
  time, but the blocks are abridged by hand and nothing tests them. This is a deliberate gap —
  pinning terminal output in a test makes every cosmetic change a build break — but it is a gap.

Technical risks
- **The docs gate makes documentation a build dependency.** A future milestone that changes a
  headline number now *must* update `docs/REPRODUCIBILITY.md` in the same commit or the build goes
  red. That is the intent, but it is friction, and the failure message must be good enough to make
  the fix obvious. It prints `(documented, actual)` pairs.
- **`cli_verbs()` reads `parser._actions`**, a private argparse attribute. It is asserted to find
  exactly one subparser group, so a structural change fails loudly rather than silently returning
  an empty verb set — but it will need updating if the CLI grows a second group.
- **The link checker resolves paths, not anchors.** A link written as `CLAIM_SCHEMA.md` plus an
  `#artifactbundle` fragment is checked for the file only; a dangling fragment passes. It is also
  literal-minded: writing a Markdown link *as an example* inside prose makes it a real link to
  check, which is how the first draft of this very note failed the build.
- **`tests/test_docs.py` runs the full suite once** (executing three fixture scripts), adding ~1.5 s
  to the test run. It is offline and harmless, but it does mean a docs test depends on the sandbox.
- No source code changed, so the risk of behavioural regression is nil; the risk is that the new
  documents *overclaim*. That is exactly what the review above is for.

Commands to verify
- `python3 -m pytest -q`                                  # 878 passed
- `python3 -m pytest tests/test_docs.py -q`               # 122, the documentation gate
- `python3 -m ruff check .`
- `python3 scripts/01_validate_fixtures.py`               # 12 ok / VALID
- `python3 scripts/05_run_smoke_suite.py --out results/runs/`   # gate PASS, exit 0
- `./scripts/serve_site.sh`                               # then read Roadmap and Limitations
- Sensitivity check: edit any value in `docs/REPRODUCIBILITY.md` §2 and re-run
  `python3 -m pytest tests/test_docs.py -q` — it must fail, naming the (documented, actual) pair.

Human feedback
<!-- Human will fill this later. -->
