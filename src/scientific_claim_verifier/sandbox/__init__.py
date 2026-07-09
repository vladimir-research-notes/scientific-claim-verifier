"""Controlled fixture execution: the reproducibility sandbox.

Milestone 6. The code-reproduction channel needs to *run* a script and record what
happened. This package is where that runs, and where the honest description of what
"sandbox" means in this repository lives:

- :mod:`scientific_claim_verifier.sandbox.policy` — what is enforced (fresh temp
  working directory, scrubbed environment, wall-clock timeout, POSIX resource
  limits, an in-process network guard) and what is not.
- :mod:`scientific_claim_verifier.sandbox.runner` — :class:`~.runner.ExecutionResult`,
  the :class:`~.runner.ScriptRunner` protocol that Milestone 5's checks already call
  through, and :class:`~.runner.SandboxScriptRunner`, which implements it.
- :mod:`scientific_claim_verifier.sandbox.trace` — the JSONL trace record of one
  execution: policy, command, captured output, outcome.

**This is not an untrusted-code sandbox.** It runs tiny, trusted, committed,
stdlib-only fixture scripts. The temp directory, the scrubbed environment, and the
socket guard exist so that a *reproduction result* means what it says — that the
script computed its number from its own contents, not from the machine it happened
to run on. They are reproducibility controls, not a security boundary, and a script
that wants to escape them can. See ``docs/SANDBOX.md``.

Nothing here decides anything about a claim. The sandbox reports what a process did;
the check reads that report (Milestone 5) and scoring draws the inference (M7).
"""

from __future__ import annotations

__all__: list[str] = []
