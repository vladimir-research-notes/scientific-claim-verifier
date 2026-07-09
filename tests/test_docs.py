"""Milestone 12 — the portfolio claims are checked, not asserted.

`CLAUDE.md` sets the quality bar: *every substantive claim in the repo must be backed
by at least one of: a test, a reproducible example task, a trace artifact, a result
table, a documented limitation, or an explicit non-goal.* Documentation is the one
place where that bar is easy to miss, because prose does not fail a build.

This module makes the portfolio documents into artifacts the build can check:

1. **Every document `docs/PLAN.md` promises exists.** The plan's repository map named
   `METHODOLOGY.md`, `LIMITATIONS.md`, `REPRODUCIBILITY.md`, and `PAPER_PATH.md` for
   twelve milestones before any of them was written; nothing noticed.
2. **Every relative link resolves** — in the Markdown docs and on the website. A README
   pointing at a doc that does not exist is worse than one that says nothing.
3. **Every CLI verb the docs invoke is a real verb**, taken from the parser itself, so a
   renamed command breaks the build rather than the reader.
4. **The headline numbers in `docs/REPRODUCIBILITY.md` are re-derived from a live suite
   run.** That table is the one place a number can rot silently, so it is the one table
   parsed and compared against the pipeline.
5. **Every milestone carries its three notes**, and no review note claims a review that
   has not happened.

The suite run here executes the three committed, stdlib-only fixture scripts as child
processes: local, harmless, and offline. Nothing in this module touches the network.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

import pytest

from scientific_claim_verifier import cli, final_check, suite
from scientific_claim_verifier.artifacts import loader
from scientific_claim_verifier.integrations import REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
SITE = REPO_ROOT / "site"
README = REPO_ROOT / "README.md"
REPRODUCIBILITY = DOCS / "REPRODUCIBILITY.md"

# The pages `CLAUDE.md` requires under site/. `integrations.html` arrived with M11.
REQUIRED_SITE_PAGES = (
    "index.html",
    "claim-schema.html",
    "artifact-bundles.html",
    "checks.html",
    "reproducibility.html",
    "example-report.html",
    "results.html",
    "limitations.html",
    "safety.html",
    "roadmap.html",
    "milestones.html",
)

# Link targets that are not files in this repository.
EXTERNAL = ("http://", "https://", "mailto:", "data:")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def markdown_files() -> list[Path]:
    """Every Markdown document a reader can reach: the README and all of docs/."""
    return [README, *sorted(DOCS.rglob("*.md"))]


def site_pages() -> list[Path]:
    return sorted(SITE.glob("*.html"))


def local_targets(text: str, pattern: str) -> list[str]:
    """Link targets from `text`, minus external URLs and bare anchors."""
    targets = []
    for raw in re.findall(pattern, text):
        target = raw.strip()
        if not target or target.startswith("#") or target.startswith(EXTERNAL):
            continue
        targets.append(target.split("#", 1)[0])
    return [t for t in targets if t]


def cli_verbs() -> set[str]:
    """The subcommands `claimverifier` actually exposes, read off its own parser."""
    parser = cli.build_parser()
    subparsers = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert len(subparsers) == 1, "the CLI grew a second subparser group"
    return set(subparsers[0].choices)


def headline_table() -> dict[str, int]:
    """Parse the `Key | Value | Reproduce with` table in REPRODUCIBILITY.md §2."""
    rows: dict[str, int] = {}
    for line in REPRODUCIBILITY.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*`([a-z_]+)`\s*\|\s*(\d+)\s*\|", line)
        if match:
            rows[match.group(1)] = int(match.group(2))
    return rows


@pytest.fixture(scope="module")
def suite_run() -> suite.SuiteRun:
    """One real end-to-end run of the committed suite; it executes three scripts."""
    loaded = loader.load_suite(REPO_ROOT / "tasks" / "smoke_suite.yaml")
    return suite.run_suite(loaded, repo_root=REPO_ROOT)


@pytest.fixture(scope="module")
def live_numbers(suite_run: suite.SuiteRun) -> dict[str, int]:
    """The headline numbers, computed from the pipeline rather than read from a doc."""
    checks = [c for r in suite_run.records for c in r.scored.result.computed_checks]
    statuses = Counter(c.status.value for c in checks)
    types = Counter(c.check_type.value for c in checks)
    summary = suite_run.summary
    return {
        "tasks": suite_run.n_tasks,
        "checks": len(checks),
        "checks_pass": statuses["pass"],
        "checks_fail": statuses["fail"],
        "checks_inconclusive": statuses["inconclusive"],
        "checks_error": statuses["error"],
        "checks_skipped": statuses["skipped"],
        "scripts_executed": types["code_execution"],
        "wrong_verdicts": len(summary.wrong_verdicts),
        "conservative_misses": len(summary.conservative_misses),
        "support_agreement": summary.support_agreement,
        "reproduction_agreement": summary.reproduction_agreement,
        "failure_agreement": summary.failure_agreement,
        "export_formats": len(REGISTRY),
        "cli_commands": len(cli_verbs()),
        "final_checks": len(final_check.CHECKS),
    }


# ---------------------------------------------------------------------------
# The plan's promises
# ---------------------------------------------------------------------------


def test_every_document_promised_by_the_plan_exists() -> None:
    """`docs/PLAN.md` §5 draws a repository map. Every doc it names must be real.

    Four of them (METHODOLOGY, LIMITATIONS, REPRODUCIBILITY, PAPER_PATH) went unwritten
    from bootstrap until Milestone 12, and nothing caught it. Now something does.
    """
    plan = (DOCS / "PLAN.md").read_text(encoding="utf-8")
    layout = plan.split("Repository layout:", 1)[1].split("```")[1]
    promised = sorted(set(re.findall(r"\b([A-Z][A-Z_]*\.md)\b", layout)))

    assert len(promised) >= 11, f"the plan's docs/ map looks unparsed: {promised}"
    missing = [name for name in promised if not (DOCS / name).is_file()]
    assert not missing, f"docs/PLAN.md promises documents that do not exist: {missing}"


def test_the_plan_promises_every_top_level_document_that_exists() -> None:
    """The converse is *not* required — later milestones added docs the map never named
    (EXTRACTION, SANDBOX, INTEGRATIONS, ...). This test pins the direction of the rule so
    a future reader does not tighten it by mistake and break the build for no reason."""
    present = {p.name for p in DOCS.glob("*.md")}
    plan = (DOCS / "PLAN.md").read_text(encoding="utf-8")
    layout = plan.split("Repository layout:", 1)[1].split("```")[1]
    promised = set(re.findall(r"\b([A-Z][A-Z_]*\.md)\b", layout))
    assert promised <= present
    assert present - promised, "if the map ever names every doc, delete this test"


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: str(p.name))
def test_every_relative_markdown_link_resolves(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    broken = [
        target
        for target in local_targets(text, r"\]\(([^)]+)\)")
        if not (path.parent / target).exists()
    ]
    assert not broken, f"{path.relative_to(REPO_ROOT)} links to missing paths: {broken}"


@pytest.mark.parametrize("name", REQUIRED_SITE_PAGES)
def test_every_website_page_required_by_claude_md_exists(name: str) -> None:
    assert (SITE / name).is_file()


@pytest.mark.parametrize("page", site_pages(), ids=lambda p: str(p.name))
def test_every_relative_website_link_resolves(page: Path) -> None:
    text = page.read_text(encoding="utf-8")
    broken = [
        target
        for target in local_targets(text, r'(?:href|src)="([^"]+)"')
        if not (page.parent / target).exists()
    ]
    assert not broken, f"site/{page.name} links to missing paths: {broken}"


def test_every_page_reaches_every_other_page_through_the_nav() -> None:
    """A page absent from the nav is a page nobody finds."""
    for page in site_pages():
        nav = page.read_text(encoding="utf-8").split("</nav>", 1)[0]
        linked = set(local_targets(nav, r'href="([^"]+)"'))
        missing = [name for name in REQUIRED_SITE_PAGES if name not in linked]
        assert not missing, f"site/{page.name} nav omits: {missing}"


# ---------------------------------------------------------------------------
# The documented interface is the real interface
# ---------------------------------------------------------------------------


def test_the_docs_invoke_only_real_cli_verbs() -> None:
    """Every `claimverifier <verb>` in the README, the docs, or the website exists."""
    verbs = cli_verbs()
    sources = [*markdown_files(), *site_pages()]
    invoked: dict[str, list[str]] = {}
    for path in sources:
        for verb in re.findall(r"claimverifier\s+([a-z][a-z-]*)", path.read_text("utf-8")):
            invoked.setdefault(verb, []).append(path.name)

    assert invoked, "no CLI invocation found in the docs — the regex has rotted"
    unknown = {verb: sorted(set(files)) for verb, files in invoked.items() if verb not in verbs}
    assert not unknown, f"the docs invoke commands the CLI does not have: {unknown}"


def test_every_command_is_documented_somewhere() -> None:
    """The converse: a verb no document mentions is a verb nobody knows about."""
    text = "\n".join(p.read_text("utf-8") for p in [*markdown_files(), *site_pages()])
    mentioned = set(re.findall(r"claimverifier\s+([a-z][a-z-]*)", text))
    assert cli_verbs() <= mentioned, f"undocumented commands: {sorted(cli_verbs() - mentioned)}"


def test_every_script_referenced_by_the_docs_exists() -> None:
    text = "\n".join(p.read_text("utf-8") for p in [*markdown_files(), *site_pages()])
    referenced = sorted(set(re.findall(r"scripts/([\w.]+\.(?:py|sh))", text)))
    assert len(referenced) >= 7, f"the script regex looks broken: {referenced}"
    missing = [name for name in referenced if not (REPO_ROOT / "scripts" / name).is_file()]
    assert not missing, f"the docs reference missing scripts: {missing}"


# ---------------------------------------------------------------------------
# The headline numbers
# ---------------------------------------------------------------------------


def test_the_headline_table_parses_and_is_complete(live_numbers: dict[str, int]) -> None:
    documented = headline_table()
    assert documented, "docs/REPRODUCIBILITY.md §2 table did not parse"
    assert set(documented) == set(live_numbers), (
        "the headline table and the numbers this test can derive have diverged: "
        f"table-only={sorted(set(documented) - set(live_numbers))}, "
        f"derivable-only={sorted(set(live_numbers) - set(documented))}"
    )


def test_reproducibility_headline_numbers_match_the_live_pipeline(
    live_numbers: dict[str, int],
) -> None:
    """Every number in `docs/REPRODUCIBILITY.md` §2, re-derived from a real run.

    This is the test that keeps the portfolio honest: a change to the pipeline that
    moves any of these numbers fails the build until the document is updated.
    """
    documented = headline_table()
    wrong = {
        key: (value, live_numbers[key])
        for key, value in documented.items()
        if value != live_numbers[key]
    }
    assert not wrong, f"docs/REPRODUCIBILITY.md is stale; (documented, actual) = {wrong}"


def test_the_two_numbers_that_matter_are_what_the_docs_say(live_numbers: dict[str, int]) -> None:
    """Pinned separately from the table, because these two carry the project's argument:
    the pipeline asserts nothing its fixtures deny, and it declines exactly one claim."""
    assert live_numbers["wrong_verdicts"] == 0
    assert live_numbers["conservative_misses"] == 1


def test_the_suite_gate_passes(suite_run: suite.SuiteRun) -> None:
    assert suite.gate(suite_run).ok


# ---------------------------------------------------------------------------
# Milestone bookkeeping (CLAUDE.md, "Required behavior after each milestone")
# ---------------------------------------------------------------------------


def milestone_slugs() -> list[str]:
    return sorted(p.stem for p in (DOCS / "milestones").glob("*.md") if p.stem != "README")


@pytest.mark.parametrize("slug", milestone_slugs())
def test_every_milestone_has_a_commit_note_and_a_review_placeholder(slug: str) -> None:
    assert (DOCS / "commits" / f"{slug}.md").is_file()
    assert (DOCS / "review_notes" / f"{slug}-human-review.md").is_file()


def test_the_milestones_are_numbered_without_gaps() -> None:
    numbers = sorted(int(slug.split("-", 1)[0]) for slug in milestone_slugs())
    assert numbers == list(range(len(numbers))), f"milestone notes skip a number: {numbers}"


@pytest.mark.parametrize("slug", milestone_slugs())
def test_no_review_note_claims_a_review_that_has_not_happened(slug: str) -> None:
    """`CLAUDE.md`: the review file is a placeholder — do not claim review happened."""
    text = (DOCS / "review_notes" / f"{slug}-human-review.md").read_text(encoding="utf-8")
    assert "Human feedback" in text
    assert "<!-- Human will fill this later. -->" in text
