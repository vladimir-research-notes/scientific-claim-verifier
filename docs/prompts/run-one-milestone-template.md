Read `CLAUDE.md` and `docs/PLAN.md`. Inspect `git status`, `git log --oneline -8`, `docs/milestones/`, `docs/commits/`, and `docs/review_notes/`. Determine the next incomplete milestone unless a specific milestone number is provided.

Implement **exactly one** milestone from `docs/PLAN.md` section 9. Do not implement later milestones. Keep everything CPU-only, offline, and free — no paid API calls, no network in tests.

Then:

1. Run that milestone's validation commands (at minimum `python3 -m pytest -q`; also `python3 scripts/01_validate_fixtures.py` and the smoke suite once those exist).
2. Update the multi-page website under `site/` (statuses, new sections, and `milestones.html`).
3. Update `docs/RESULTS.md` or the relevant docs if results changed.
4. Create/update `docs/milestones/NN-<slug>.md`, `docs/commits/NN-<slug>.md`, and `docs/review_notes/NN-<slug>-human-review.md` (review file is a placeholder — do not claim review happened).
5. Commit locally with a meaningful message. **Do not push.**

Do not commit secrets, credentials, private/real papers, large datasets, caches, virtualenvs, model weights, or paid-API outputs. Confirm the working tree is clean before finishing.

Stop after exactly one milestone and print: milestone title, commit hash, tests run, website pages updated, review placeholder path, and the next milestone.
