"""The authored source of the committed LLM recordings, and the tool that regenerates them.

Milestone 10. ``data/fixtures/llm/extraction_recordings.json`` is a **derived** artifact:
every byte of it is produced from the constants in this module plus the current prompt
template in :mod:`scientific_claim_verifier.claims.llm_extraction`. The module holding the
source of a file it writes has precedent here —
:data:`scientific_claim_verifier.sandbox.policy.SITECUSTOMIZE_SOURCE` does the same.

Making the fixture derived rather than hand-maintained buys one thing, and it is the
thing that matters: ``--check`` regenerates the file in memory and compares **bytes**. So
a prompt-template edit that leaves the committed recordings answering a question nobody
asks any more fails the build (``tests/test_adapters.py`` runs the same check), with an
instruction, instead of silently turning every replay into a
:class:`~scientific_claim_verifier.adapters.recorded_llm.RecordingNotFound` at some later
milestone.

Provenance, stated plainly
--------------------------
**The responses below are hand-authored. No language model produced them, and no API was
called to obtain them.** They are what a competent model *would* plausibly return, written
in the response schema. They therefore measure exactly one thing — that a request is
fingerprinted, replayed, parsed, and scored faithfully — and they measure **nothing at all**
about any model's ability to extract a claim. Any accuracy computed over them is a fact
about this file. ``docs/RESULTS.md`` says so where the number appears, and the model they
name, ``recorded-fixture-v1``, is fictitious so that the file cannot imply otherwise.

``dataset_mean`` is deliberately **wrong in two fields**: it reports ``metrics: ["mean"]``
where the gold is ``["mean", "count"]``, and it omits the ``"n = 12"`` condition. Dropping
a secondary metric and its condition is a realistic omission, and without it every recorded
response would score a perfect 32/32 — a number that would look like evidence and be an
artifact of the author's generosity. The miss is what proves the scorer is connected.
``gc_content`` is wrapped in a Markdown code fence, because models emit them and
:func:`~scientific_claim_verifier.claims.llm_extraction.strip_code_fence` has to survive it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..artifacts import loader
from ..claims.llm_extraction import build_request
from . import cost
from .base import RECORDED_MODEL, TokenUsage
from .recorded_llm import (
    Recording,
    RecordingsError,
    default_recordings_path,
    render_recordings,
)

#: Written into the fixture file's ``notes`` key, so the provenance travels with the data.
FIXTURE_NOTES = (
    "Hand-authored synthetic responses in the shape a model would return. No language "
    "model produced them and no API was called. The model name 'recorded-fixture-v1' is "
    "fictitious. Token counts are estimates from adapters.cost, not vendor-reported. "
    "Regenerate with `python3 scripts/06_record_llm_fixtures.py --write`."
)

#: ``task_id -> (response text, why this recording exists)``. The response text is exactly
#: what the recorded adapter replays; the note travels into the fixture file.
AUTHORED_RESPONSES: dict[str, tuple[str, str]] = {
    "accuracy_improvement": (
        """{
  "expected_value": 78.0,
  "baseline_value": 72.0,
  "comparison_operator": ">",
  "units": "%",
  "metrics": ["accuracy"],
  "datasets": ["SST-2"],
  "entities": ["Method A", "baseline"],
  "conditions": []
}""",
        "A well-formed comparison claim, extracted correctly. Matches gold on all 8 fields.",
    ),
    "dataset_mean": (
        """{
  "expected_value": 3.4,
  "baseline_value": null,
  "comparison_operator": "~",
  "units": null,
  "metrics": ["mean"],
  "datasets": ["measurements"],
  "entities": [],
  "conditions": []
}""",
        "Deliberately imperfect: drops the 'count' metric and the 'n = 12' condition. "
        "Scores 6/8 against gold, which is the point — a fixture that always wins proves "
        "nothing about the scorer.",
    ),
    "underspecified_split": (
        """{
  "expected_value": 90.0,
  "baseline_value": null,
  "comparison_operator": "=",
  "units": "%",
  "metrics": ["accuracy"],
  "datasets": [],
  "entities": [],
  "conditions": []
}""",
        "A bare numeric claim. Extraction is complete and correct; the claim is still "
        "underspecified, which is a scoring verdict (M7), not an extraction failure.",
    ),
    "gc_content": (
        """```json
{
  "expected_value": 0.5,
  "baseline_value": null,
  "comparison_operator": "~",
  "units": null,
  "metrics": ["gc_content"],
  "datasets": [],
  "entities": [],
  "conditions": []
}
```""",
        "Wrapped in a Markdown code fence, as models habitually do. Exercises "
        "strip_code_fence; matches gold on all 8 fields once unwrapped.",
    ),
}


def build_recordings(tasks_dir: str | Path = "tasks") -> list[Recording]:
    """Build one recording per authored response, ordered by label.

    The request is rebuilt from the *current* prompt template and the *current* task
    fixture, so a change to either shows up as a byte difference in the rendered file.
    Token counts come from the same estimator a paid run would use.
    """
    index = loader.index_tasks(tasks_dir)
    recordings: list[Recording] = []
    for label in sorted(AUTHORED_RESPONSES):
        if label not in index:
            raise RecordingsError(
                f"recording {label!r} names no task under {tasks_dir}/; "
                f"remove it from AUTHORED_RESPONSES or restore the task"
            )
        task = loader.load_task(index[label])
        text, note = AUTHORED_RESPONSES[label]
        request = build_request(task.input_claim, task.bundle, model=RECORDED_MODEL)
        usage = TokenUsage(
            prompt_tokens=cost.estimate_request_tokens(request),
            completion_tokens=cost.estimate_tokens(text),
        )
        recordings.append(
            Recording(label=label, request=request, text=text, usage=usage, notes=note)
        )
    return recordings


def render(tasks_dir: str | Path = "tasks") -> str:
    """The exact bytes the committed fixture file should contain."""
    return render_recordings(build_recordings(tasks_dir), notes=FIXTURE_NOTES)


def check(path: str | Path | None = None, tasks_dir: str | Path = "tasks") -> list[str]:
    """Return the reasons the committed fixture is stale. Empty means it is current."""
    target = Path(path) if path is not None else default_recordings_path()
    expected = render(tasks_dir)
    if not target.is_file():
        return [f"{target} does not exist"]
    actual = target.read_text(encoding="utf-8")
    if actual != expected:
        return [
            f"{target} does not match what the current prompt template and tasks produce "
            f"({len(actual)} bytes committed, {len(expected)} bytes expected)"
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    """``--check`` (default) or ``--write`` the committed recordings. Offline; free."""
    parser = argparse.ArgumentParser(
        prog="06_record_llm_fixtures",
        description=(
            "Regenerate or verify the committed LLM recordings. These are hand-authored "
            "synthetic responses; no API is called and nothing costs money."
        ),
    )
    parser.add_argument(
        "--tasks-dir", default="tasks", metavar="DIR", help="Task directory (default: tasks/)."
    )
    parser.add_argument(
        "--out", default=None, metavar="PATH", help="Recordings file (default: the committed one)."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Rewrite the recordings file. Without this flag the file is only checked.",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    target = Path(args.out) if args.out else default_recordings_path()

    try:
        if args.write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render(args.tasks_dir), encoding="utf-8")
            print(f"wrote {len(AUTHORED_RESPONSES)} recordings to {target}")
            return 0

        problems = check(target, args.tasks_dir)
    except (RecordingsError, loader.TaskLoadError, loader.SuiteLoadError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if problems:
        for problem in problems:
            print(f"STALE: {problem}", file=sys.stderr)
        print(
            "\nThe prompt template or a task fixture changed, so every committed recording "
            "would now miss.\nRebuild them with: python3 scripts/06_record_llm_fixtures.py --write",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {target} is current ({len(AUTHORED_RESPONSES)} recordings)")
    return 0


__all__ = [
    "AUTHORED_RESPONSES",
    "FIXTURE_NOTES",
    "build_recordings",
    "check",
    "main",
    "render",
]
