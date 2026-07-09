# SAFETY

The safety scope below is a **permanent contract**, established at project
bootstrap and binding on every milestone. These are non-goals by design, not
gaps to be filled later.

## Scientific scope

### In scope

- Machine-learning benchmark claims (accuracy/F1 deltas, ablation tables).
- Bioinformatics *toy* analyses over synthetic or open data.
- Statistical claims over small, committed CSVs.
- Simple ablation / results tables.
- Reproduction of tiny Python scripts computing a reported metric.

### Out of scope — always

- Clinical decision-making or patient-specific advice.
- Medical or treatment recommendations.
- Wet-lab protocol design or optimization.
- Dual-use biological instructions.
- Real patient data; private or real papers.
- Real credential handling.

If a task or fixture would require any out-of-scope capability, it does not
belong in this repository.

## Data policy

- All fixtures are **synthetic or open** and small enough to read by hand.
- Never commit: secrets, credentials, `.env`, keys, private/real papers, large
  datasets, model weights, caches, virtualenvs, or paid-API outputs. This is
  enforced by `.gitignore` and (from a later milestone) a repository-hygiene
  check.

## Execution safety

The code-execution layer runs **tiny, trusted fixture scripts** in a temporary
directory with a scrubbed environment, closed stdin, POSIX resource limits, a
timeout that kills the whole process group, captured stdout/stderr/exit-code, and
an in-process guard that denies and records `socket` calls.

It is **controlled fixture execution for reproducibility**, not a security
boundary. There is no process isolation, no namespace, no seccomp filter, and the
network guard runs inside the child's own interpreter, so code that means to bypass
it can. It provides no hard isolation against adversarial code and must never be
used to run untrusted code. This limitation is stated wherever execution is
described: `docs/SANDBOX.md` (what is and is not enforced), `docs/CHECKS.md`, the
module docstrings, and the website's Limitations page.

## Auditability, not authority

The system exists to make claim-checking transparent. Every result keeps these
separate and clearly labelled:

- the **extracted claim**,
- the **supporting text**,
- the **computed check**,
- the **inference** (support label / reproducibility status), and
- any **unverifiable statement**.

A verdict is **relative to the supplied artifacts only**. "Supported" means the
bundle backs the claim — not that the claim is true in the world. The system
does not present itself as an authority on scientific truth.

## Paid-API safety

The default path is fully deterministic, offline, and free. Optional LLM/API
adapters are disabled by default. Any paid-API mode must provide, before it can
run: a dry-run mode, a response cache, a token/cost estimator, a hard max-cost
guard, and explicit opt-in.
