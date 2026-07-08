# Initial build prompt for Claude Code

You are working in the `scientific-claim-verifier` repository — a CPU-first
system for verifying scientific claims against papers, datasets, code artifacts,
and reproducibility evidence.

Read:

- `CLAUDE.md`
- `docs/PLAN.md`

Then execute the plan milestone by milestone (section 9), one milestone per run.

## Important instructions

- Do not push. Commit locally after each coherent milestone.
- Do not wait for human review; create a review placeholder and continue.
- Keep all default tests CPU-only, offline, and free. No paid API calls.
- Do not commit secrets, credentials, private/real papers, large datasets,
  caches, virtualenvs, `node_modules`, model weights, or paid-API outputs.
- Update the multi-page website at every milestone (including `milestones.html`).
- Keep documentation professional and precise. Avoid "learning project" tone.
- Be explicit about limitations and non-goals; label heuristics as heuristics.
- Keep the extracted claim, supporting text, computed check, inference, and
  unverifiable statement clearly separate in all outputs.

Start with Milestone 0 from `docs/PLAN.md`.

After each milestone, print: milestone title, commit hash, tests run, website
pages updated, review placeholder path, and the next milestone. Continue only if
doing so would not risk secrets, paid API spend, data loss, or repo corruption.
