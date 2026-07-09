"""Milestone 9 — reports rendered from traces.

The properties this milestone rests on, and the ones these tests are here to keep true:

- **A report is a function of the trace alone.** Nothing else is read: not the task, not
  the paper, not the CSV, not ``result.json``. The round-trip test scores every committed
  fixture, writes its trace, reads it back, and asserts the reconstructed Milestone 7
  ``ScoredClaim`` **equals** the original. If a later milestone records a fact in the
  result but not in the trace, that test fails — which is the only thing keeping
  ``docs/PLAN.md`` §11's "reports are generated from traces" from becoming a slogan.
- **A malformed trace is refused, not rendered.** Every object comes back through its
  pydantic model, and a trace that is truncated, reordered, duplicated, foreign, or
  written under an unreadable schema version raises :class:`ReportError` naming the file.
- **The five channels stay separate.** ``contradicted_f1`` prints the passage that
  asserts its claim *and* the table that refutes it, in different sections.
  ``synthetic_data_passage`` prints ``confidence 0.00`` and says what it could not decide,
  and nowhere claims a contradiction.
- **Markdown and HTML cannot disagree**, because both walk one ``Document``.
- **Output is deterministic and path-free.** Two renders are byte-identical, and a report
  written beside its trace carries no absolute path, so two run directories produce the
  same bytes.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from scientific_claim_verifier import cli, reports
from scientific_claim_verifier.reports import html as H
from scientific_claim_verifier.reports import markdown as M
from scientific_claim_verifier.reports import reader as R
from scientific_claim_verifier.reports import render as RN
from scientific_claim_verifier.schemas import SCHEMA_VERSION, FailureMode, SupportLabel
from scientific_claim_verifier.scoring import Rule
from scientific_claim_verifier.scoring import verdict as V
from scientific_claim_verifier.scoring.failure_modes import Cause

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "tasks"

# Every committed fixture, by the path `verify` takes — the same set as tests/test_scoring.py
# and `tasks/smoke_suite.yaml`.
FIXTURES = {
    "accuracy_improvement": "table_claims/accuracy_improvement.yaml",
    "contradicted_f1": "table_claims/contradicted_f1.yaml",
    "dataset_mean": "statistical_claims/dataset_mean.yaml",
    "dataset_mean_overstated": "statistical_claims/dataset_mean_overstated.yaml",
    "dataset_std": "statistical_claims/dataset_std.yaml",
    "gc_content": "bioinformatics_claims/gc_content.yaml",
    "negated_training_data": "ml_claims/negated_training_data.yaml",
    "recompute_accuracy": "code_reproduction/recompute_accuracy.yaml",
    "synthetic_data_passage": "ml_claims/synthetic_data_passage.yaml",
    "underspecified_split": "ml_claims/underspecified_split.yaml",
    "unreproducible_accuracy": "code_reproduction/unreproducible_accuracy.yaml",
}

SECTION_TITLES = (
    "1. Extracted claim",
    "2. Supporting text (retrieved evidence)",
    "3. Computed checks",
    "4. Inference",
    "5. Unverifiable from these artifacts",
    "6. Trace",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_fixture(name: str, out_dir: Path) -> tuple[V.ScoredClaim, Path]:
    """Score one committed fixture into ``out_dir`` and return it with its trace path."""
    _, _, scored = V.verify_task(
        TASKS_DIR / FIXTURES[name], out_dir=out_dir, repo_root=REPO_ROOT
    )
    return scored, out_dir / f"{name}.trace.jsonl"


def read_fixture(name: str, out_dir: Path) -> R.ReportInput:
    """Score a fixture, then read its report input back from the trace alone."""
    _, trace = run_fixture(name, out_dir)
    return R.read_report(trace)


def document_of(name: str, out_dir: Path) -> reports.Document:
    report = read_fixture(name, out_dir)
    return reports.build_document(report, trace_href=f"{name}.trace.jsonl")


def markdown_of(name: str, out_dir: Path) -> str:
    return M.render_markdown(document_of(name, out_dir))


def all_text(document: reports.Document) -> str:
    """Every string a document carries, without any format's punctuation."""
    return M.render_markdown(document)


class _Balance(HTMLParser):
    """Asserts every non-void element opens and closes, in order."""

    VOID = frozenset({"meta", "br", "link", "img", "hr", "input"})

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            self.errors.append(tag)


# ---------------------------------------------------------------------------
# The round trip: the trace loses nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_a_trace_reconstructs_the_scored_claim_exactly(name: str, tmp_path: Path) -> None:
    # The whole milestone rests on this. `reader` never touches the task, the artifacts,
    # or `result.json` — only the JSONL bytes `verify --out` wrote.
    scored, trace = run_fixture(name, tmp_path)
    report = R.read_report(trace)

    assert report.result == scored.result
    assert report.support_rule == scored.support_rule
    assert report.reproduction_rule == scored.reproduction_rule
    assert report.failure_rule == scored.failure_rule
    assert report.signals == scored.signals


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_a_trace_reconstructs_the_extracted_claim_exactly(name: str, tmp_path: Path) -> None:
    _, claim, _ = V.verify_task(TASKS_DIR / FIXTURES[name], out_dir=tmp_path, repo_root=REPO_ROOT)
    assert R.read_report(tmp_path / f"{name}.trace.jsonl").claim == claim


def test_the_report_names_the_run_the_trace_records(tmp_path: Path) -> None:
    report = read_fixture("dataset_mean", tmp_path)
    assert report.run_id == "dataset_mean"
    assert report.task_id == "dataset_mean"
    assert report.bundle_id == "bundle_dataset_mean"
    assert report.schema_version == SCHEMA_VERSION
    # One event per check, plus the seven singletons that open and close the stream.
    assert len(R.REQUIRED_EVENT_KINDS) == 7
    assert report.n_events == len(report.result.computed_checks) + len(R.REQUIRED_EVENT_KINDS)


def test_a_report_needs_the_trace_and_nothing_else(tmp_path: Path) -> None:
    # `verify --out` writes a trace and a result.json. Delete everything but the trace,
    # and the paper, the CSV, and the task file with it — the report still renders.
    _, trace = run_fixture("contradicted_f1", tmp_path)
    (tmp_path / "contradicted_f1.result.json").unlink()

    lonely = tmp_path / "archived"
    lonely.mkdir()
    moved = lonely / trace.name
    moved.write_bytes(trace.read_bytes())
    trace.unlink()

    assert RN.report_and_write(lonely, out=lonely) == 0
    assert (lonely / "contradicted_f1.md").is_file()


# ---------------------------------------------------------------------------
# A malformed trace is refused, not rendered
# ---------------------------------------------------------------------------


def _events(trace: Path) -> list[dict]:
    return [json.loads(line) for line in trace.read_text().splitlines()]


def _rewrite(trace: Path, events: list[dict]) -> Path:
    trace.write_text("\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n")
    return trace


def test_a_missing_trace_is_reported_by_name(tmp_path: Path) -> None:
    with pytest.raises(R.ReportError, match="cannot read trace"):
        R.read_report(tmp_path / "nope.trace.jsonl")


def test_an_empty_trace_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty.trace.jsonl"
    empty.write_text("")
    with pytest.raises(R.ReportError, match="empty trace"):
        R.read_report(empty)


def test_a_non_jsonl_trace_is_refused(tmp_path: Path) -> None:
    junk = tmp_path / "junk.trace.jsonl"
    junk.write_text("not json at all\n")
    with pytest.raises(R.ReportError, match="not JSONL"):
        R.read_report(junk)


def test_a_trace_without_a_run_event_is_refused_with_an_instruction(tmp_path: Path) -> None:
    # Exactly what a schema-1.2 trace looks like: it cannot say which run it describes,
    # and inferring that from the filename is the guess this reader refuses to make.
    _, trace = run_fixture("dataset_mean", tmp_path)
    events = _events(trace)[1:]
    for index, event in enumerate(events):
        event["seq"] = index
    _rewrite(trace, events)
    with pytest.raises(R.ReportError, match="predates schema 1.3"):
        R.read_report(trace)


def test_a_trace_from_a_future_major_version_is_refused(tmp_path: Path) -> None:
    _, trace = run_fixture("dataset_mean", tmp_path)
    events = _events(trace)
    events[0]["data"]["schema_version"] = "2.0"
    _rewrite(trace, events)
    with pytest.raises(R.ReportError, match="not readable by this build"):
        R.read_report(trace)


def test_a_trace_from_a_later_minor_version_is_read(tmp_path: Path) -> None:
    # Within a major version, event data only grows. A 1.9 trace is a 1.3 trace plus keys.
    _, trace = run_fixture("dataset_mean", tmp_path)
    events = _events(trace)
    events[0]["data"]["schema_version"] = "1.9"
    _rewrite(trace, events)
    assert R.read_report(trace).schema_version == "1.9"


def test_a_truncated_trace_is_refused(tmp_path: Path) -> None:
    _, trace = run_fixture("dataset_mean", tmp_path)
    _rewrite(trace, _events(trace)[:-1])
    with pytest.raises(R.ReportError, match="missing event"):
        R.read_report(trace)


def test_a_reordered_trace_is_refused(tmp_path: Path) -> None:
    _, trace = run_fixture("dataset_mean", tmp_path)
    events = _events(trace)
    events[0], events[1] = events[1], events[0]
    _rewrite(trace, events)
    with pytest.raises(R.ReportError, match="out of order"):
        R.read_report(trace)


def test_a_duplicated_event_is_refused(tmp_path: Path) -> None:
    _, trace = run_fixture("dataset_mean", tmp_path)
    events = _events(trace)
    events.append({**events[-1], "seq": len(events)})
    _rewrite(trace, events)
    with pytest.raises(R.ReportError, match="duplicate"):
        R.read_report(trace)


def test_a_sandbox_trace_is_not_a_scoring_trace(tmp_path: Path) -> None:
    # `run-sandbox --out` writes `sandbox.*` events. It records an execution, not a verdict.
    foreign = tmp_path / "foreign.trace.jsonl"
    foreign.write_text(json.dumps({"seq": 0, "kind": "sandbox.policy", "data": {}}) + "\n")
    with pytest.raises(R.ReportError, match="not a scoring trace"):
        R.read_report(foreign)


def test_a_check_that_violates_the_schema_is_refused(tmp_path: Path) -> None:
    # `confidence` is bounded [0, 1] by the model. A trace claiming 7.0 does not render.
    _, trace = run_fixture("dataset_mean", tmp_path)
    events = _events(trace)
    events[-1]["data"]["confidence"] = 7.0
    _rewrite(trace, events)
    with pytest.raises(R.ReportError, match="malformed trace"):
        R.read_report(trace)


def test_discover_traces_ignores_sandbox_traces(tmp_path: Path) -> None:
    run_fixture("dataset_mean", tmp_path)
    (tmp_path / "dataset_mean.sandbox.jsonl").write_text("")
    assert [p.name for p in R.discover_traces(tmp_path)] == ["dataset_mean.trace.jsonl"]


# ---------------------------------------------------------------------------
# The document: the five channels, kept separate
# ---------------------------------------------------------------------------


def test_the_report_has_the_five_audit_channels_plus_the_trace(tmp_path: Path) -> None:
    document = document_of("dataset_mean", tmp_path)
    titles = tuple(section.title for section in document.sections if section.title)
    assert titles == SECTION_TITLES


def test_the_contradiction_report_keeps_both_channels_visible(tmp_path: Path) -> None:
    # The paper's own sentence asserts the claim; its table refutes it. A report that
    # showed only the verdict would destroy the only interesting fact about the claim.
    text = markdown_of("contradicted_f1", tmp_path)
    supporting, checks = text.split("## 3. Computed checks")
    assert "Method B reaches an F1 score of 91.0 on MNLI." in supporting  # §2 quotes it
    assert "| fail | table_value |" in checks  # §3 refutes it
    assert "support_label: contradicted" in checks
    assert "rule: artifacts_refute" in checks


def test_the_undecided_report_says_so_and_claims_no_contradiction(tmp_path: Path) -> None:
    text = markdown_of("synthetic_data_passage", tmp_path)
    assert "| support_label | unverifiable_from_artifacts |" in text
    assert "| confidence | 0.00 |" in text
    assert "a lexical check cannot decide whether the passage asserts the claim" in text
    assert SupportLabel.CONTRADICTED.value not in text
    assert FailureMode.PASSAGE_DOES_NOT_ASSERT.value not in text


def test_a_clean_report_states_that_nothing_was_left_unsettled(tmp_path: Path) -> None:
    text = markdown_of("accuracy_improvement", tmp_path)
    assert "(none — every check reached a verdict)" in text


def test_a_sandboxed_report_repeats_the_sandbox_limitation(tmp_path: Path) -> None:
    # True of the verdict whether or not the verdict was favourable: `recompute_accuracy`
    # is `supported` and `reproduced`, and still says the sandbox is not a boundary.
    text = markdown_of("recompute_accuracy", tmp_path)
    assert "| support_label | supported |" in text
    assert "not a security boundary" in text


def test_every_check_and_its_signal_reach_the_report(tmp_path: Path) -> None:
    report = read_fixture("unreproducible_accuracy", tmp_path)
    text = M.render_markdown(reports.build_document(report, trace_href="t.jsonl"))
    for check, signal in zip(report.result.computed_checks, report.signals, strict=True):
        assert check.check_id in text
        assert signal.because in text
    assert "| error | code_execution |" in text
    assert "| skipped | numeric_tolerance |" in text


def test_the_rules_and_the_checks_they_read_reach_the_report(tmp_path: Path) -> None:
    report = read_fixture("dataset_mean_overstated", tmp_path)
    text = M.render_markdown(reports.build_document(report, trace_href="t.jsonl"))
    assert f"rule: {report.support_rule.name}" in text
    for check_id in report.support_rule.check_ids:
        assert check_id in text
    assert report.support_rule.because in text


def test_confidence_is_never_printed_without_its_caveat(tmp_path: Path) -> None:
    text = markdown_of("dataset_std", tmp_path)
    assert "not a probability that the label is correct" in text


def test_the_trace_section_links_the_trace_it_read(tmp_path: Path) -> None:
    document = document_of("gc_content", tmp_path)
    trace_section = document.sections[-1]
    links = [b for b in trace_section.blocks if isinstance(b, reports.Link)]
    assert links == [reports.Link("gc_content.trace.jsonl", "gc_content.trace.jsonl")]


def test_all_the_causes_are_listed_when_a_claim_fails_more_than_one_way(
    tmp_path: Path,
) -> None:
    # No committed fixture is refuted by its table *and* undecidable from its text, so the
    # multi-cause block is exercised here rather than by a run. The failure mode names one
    # cause; a claim that fails two ways is not described by either alone.
    base = read_fixture("contradicted_f1", tmp_path)
    both = R.ReportInput(
        run_id=base.run_id,
        task_id=base.task_id,
        bundle_id=base.bundle_id,
        schema_version=base.schema_version,
        claim=base.claim,
        scored=base.scored,
        causes=(
            Cause(FailureMode.TABLE_CELL_MISMATCH, "c.table_value.1", "the table disagrees"),
            Cause(FailureMode.EVIDENCE_UNDECIDABLE, "c.evidence_presence.1", "cannot tell"),
        ),
        trace_path=base.trace_path,
        n_events=base.n_events,
    )
    text = M.render_markdown(reports.build_document(both, trace_href="t.jsonl"))
    assert "Every reason this claim is not clean" in text
    assert "table_cell_mismatch (c.table_value.1): the table disagrees" in text
    assert "evidence_undecidable (c.evidence_presence.1): cannot tell" in text


def test_a_claim_with_no_linked_passage_says_so_rather_than_printing_nothing() -> None:
    document = reports.build_document(_bare_report(), trace_href="t.jsonl")
    text = M.render_markdown(document)
    assert "(no passage was linked to this claim)" in text
    assert "(no check ran against this claim)" in text


def _bare_report() -> R.ReportInput:
    """A synthetic report with no evidence and no checks — the degenerate rendering path."""
    from scientific_claim_verifier.schemas import (
        ClaimType,
        ReproductionStatus,
        ScientificClaim,
        VerificationResult,
    )

    result = VerificationResult(
        claim_id="c_bare",
        support_label=SupportLabel.NOT_CHECKED,
        reproduction_status=ReproductionStatus.NOT_ATTEMPTED,
        failure_mode=FailureMode.NONE,
        confidence=0.0,
        human_readable_summary="nothing was checked",
    )
    rule = Rule("none", "nothing ran")
    return R.ReportInput(
        run_id="bare",
        task_id=None,
        bundle_id=None,
        schema_version=SCHEMA_VERSION,
        claim=ScientificClaim(
            claim_id="c_bare", claim_text="A claim.", claim_type=ClaimType.DESCRIPTIVE
        ),
        scored=V.ScoredClaim(result, rule, rule, rule, ()),
        causes=(),
        trace_path=Path("bare.trace.jsonl"),
        n_events=6,
    )


# ---------------------------------------------------------------------------
# Blocks, escaping, and the two serializers
# ---------------------------------------------------------------------------


def test_a_table_row_must_be_as_wide_as_its_header() -> None:
    with pytest.raises(ValueError, match="row 0 has 1 cell"):
        reports.Table(columns=("a", "b"), rows=(("only",),))


def test_a_markdown_cell_cannot_smuggle_a_column_break() -> None:
    # An unescaped pipe eats a column; an unescaped newline ends the table. Either would
    # make the document say something false about the run.
    table = reports.Table(columns=("Field", "Value"), rows=(("metrics", "a | b\nc"),))
    rendered = M.render_block(table)
    assert "| metrics | a \\| b c |" in rendered
    assert len(rendered.splitlines()) == 3


def test_html_escapes_everything_including_hrefs() -> None:
    table = reports.Table(
        columns=("Field",), rows=((reports.Link('a"b', "x&y.md"),), ("<script>",))
    )
    rendered = H.render_block(table)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert 'href="x&amp;y.md"' in rendered


def test_a_multiline_bullet_survives_both_formats() -> None:
    bullets = reports.Bullets(("head\ntail",))
    assert M.render_block(bullets) == "- head\n  tail"
    assert H.render_block(bullets) == "<ul><li>head<br>tail</li></ul>"


def test_an_unknown_block_type_fails_loudly_in_both_formats() -> None:
    for module in (M, H):
        with pytest.raises(TypeError, match="unrenderable block"):
            module.render_block(object())  # type: ignore[arg-type]


def test_the_two_formats_report_the_same_run(tmp_path: Path) -> None:
    # They walk one Document, so they cannot disagree about what the pipeline concluded.
    document = document_of("dataset_mean_overstated", tmp_path)
    markdown, rendered_html = M.render_markdown(document), H.render_html(document)
    for fact in (
        "contradicted",
        "failed_numeric_mismatch",
        "statistic_mismatch",
        "c_dataset_mean_overstated.dataset_statistic.1",
    ):
        assert fact in markdown and fact in rendered_html
    for title in SECTION_TITLES:
        assert title in markdown and title in rendered_html


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_the_html_report_is_balanced_and_standalone(name: str, tmp_path: Path) -> None:
    rendered = H.render_html(document_of(name, tmp_path))
    balance = _Balance()
    balance.feed(rendered)
    assert not balance.errors and not balance.stack
    assert rendered.startswith("<!doctype html>")
    assert "<style>" in rendered  # no stylesheet to ship beside it
    assert "http://" not in rendered and "https://" not in rendered  # no network fetch


# ---------------------------------------------------------------------------
# Determinism and portability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_two_renders_of_one_trace_are_byte_identical(name: str, tmp_path: Path) -> None:
    first = markdown_of(name, tmp_path / "a")
    second = markdown_of(name, tmp_path / "b")
    assert first == second


def test_a_report_beside_its_trace_carries_no_absolute_path(tmp_path: Path) -> None:
    # So a run directory can be copied, archived, or served without a broken link, and
    # without leaking the absolute path of the machine that produced it.
    left, right = tmp_path / "left", tmp_path / "right"
    for out in (left, right):
        run_fixture("gc_content", out)
        assert RN.report_and_write(out, out=out, fmt=RN.BOTH) == 0

    for suffix in (".md", ".html"):
        body = (left / f"gc_content{suffix}").read_text()
        assert str(tmp_path) not in body
        assert body == (right / f"gc_content{suffix}").read_text()


def test_a_report_written_elsewhere_links_its_trace_relatively(tmp_path: Path) -> None:
    run_fixture("gc_content", tmp_path / "runs")
    assert RN.report_and_write(tmp_path / "runs", out=tmp_path / "reports") == 0
    body = (tmp_path / "reports" / "gc_content.md").read_text()
    assert "(../runs/gc_content.trace.jsonl)" in body
    assert str(tmp_path) not in body


def test_href_is_the_path_as_given_when_there_is_nowhere_to_be_relative_to() -> None:
    assert RN.href(Path("/x/y.trace.jsonl"), relative_to=None) == "/x/y.trace.jsonl"
    assert RN.href(Path("/x/y.trace.jsonl"), relative_to=Path("/x")) == "y.trace.jsonl"
    assert RN.href(Path("/x/y.trace.jsonl"), relative_to=Path("/x/z")) == "../y.trace.jsonl"


# ---------------------------------------------------------------------------
# The index over a run directory
# ---------------------------------------------------------------------------


def _suite_run(tmp_path: Path) -> Path:
    from scientific_claim_verifier import suite

    out = tmp_path / "runs"
    assert suite.run_and_report(REPO_ROOT / "tasks" / "smoke_suite.yaml", out_dir=out) == 0
    return out / "smoke_suite"


def test_the_index_lists_every_claim_in_the_suites_declared_order(tmp_path: Path) -> None:
    run_dir = _suite_run(tmp_path)
    assert RN.report_and_write(run_dir, out=run_dir) == 0
    index = (run_dir / "index.md").read_text()

    order = R.order_of(run_dir, R.read_summary(run_dir))
    assert len(order) == 11
    positions = [index.index(f"[{task_id}]({task_id}.md)") for task_id in order]
    assert positions == sorted(positions)  # evidence-channel order, not alphabetical


def test_the_index_reports_the_suite_gate_and_refuses_to_be_a_scoreboard(
    tmp_path: Path,
) -> None:
    run_dir = _suite_run(tmp_path)
    assert RN.report_and_write(run_dir, out=run_dir) == 0
    index = (run_dir / "index.md").read_text()
    assert "Suite smoke_suite (Offline smoke suite) v1 — gate PASS." in index
    assert "5 supported" in index and "3 contradicted" in index
    assert "this index is not a scoreboard" in index
    assert "summary.csv" in index  # gold agreement lives there, not here


def test_the_index_says_nothing_about_a_gate_it_has_no_summary_for(tmp_path: Path) -> None:
    run_fixture("dataset_mean", tmp_path)
    assert RN.report_and_write(tmp_path, out=tmp_path) == 0
    index = (tmp_path / "index.md").read_text()
    assert "gate" not in index.lower()
    assert "[dataset_mean](dataset_mean.md)" in index


def test_an_unreadable_summary_does_not_fail_the_reports_it_would_decorate(
    tmp_path: Path,
) -> None:
    run_fixture("dataset_mean", tmp_path)
    (tmp_path / "summary.json").write_text("{ not json")
    assert R.read_summary(tmp_path) is None
    assert RN.report_and_write(tmp_path, out=tmp_path) == 0


def test_the_index_can_be_suppressed(tmp_path: Path) -> None:
    run_fixture("dataset_mean", tmp_path)
    assert RN.report_and_write(tmp_path, out=tmp_path / "out", index=False) == 0
    assert not (tmp_path / "out" / "index.md").exists()
    assert (tmp_path / "out" / "dataset_mean.md").is_file()


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------


def test_report_writes_one_file_per_claim_per_format(tmp_path: Path) -> None:
    run_dir = _suite_run(tmp_path)
    out = tmp_path / "reports"
    assert cli.main(["report", "--run", str(run_dir), "--out", str(out), "--format", "both"]) == 0
    assert len(sorted(out.glob("*.md"))) == 12  # 11 claims + index
    assert len(sorted(out.glob("*.html"))) == 12


def test_report_writes_a_single_named_file_for_a_single_trace(tmp_path: Path) -> None:
    _, trace = run_fixture("dataset_mean", tmp_path)
    target = tmp_path / "out" / "dataset_mean.md"
    assert cli.main(["report", "--run", str(trace), "--out", str(target)]) == 0
    assert target.read_text().startswith("# Verification report — dataset_mean")


def test_report_names_its_output_from_the_run_not_from_the_filename(tmp_path: Path) -> None:
    # The run id is a fact recorded *in* the trace. A renamed trace file does not rename
    # the run it describes, and the report says what the trace says.
    _, trace = run_fixture("dataset_mean", tmp_path)
    renamed = tmp_path / "whatever.trace.jsonl"
    renamed.write_bytes(trace.read_bytes())
    trace.unlink()
    assert cli.main(["report", "--run", str(tmp_path), "--out", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "dataset_mean.md").is_file()


def test_report_prints_to_stdout_without_out(tmp_path: Path, capsys) -> None:
    _, trace = run_fixture("contradicted_f1", tmp_path)
    assert cli.main(["report", "--run", str(trace)]) == 0
    printed = capsys.readouterr().out
    assert "# Verification report — contradicted_f1" in printed
    assert "## 4. Inference" in printed
    assert not sorted(tmp_path.glob("*.md"))  # nothing written


def test_report_prints_html_to_stdout(tmp_path: Path, capsys) -> None:
    _, trace = run_fixture("gc_content", tmp_path)
    assert cli.main(["report", "--run", str(trace), "--format", "html"]) == 0
    assert capsys.readouterr().out.startswith("<!doctype html>")


def test_report_refuses_both_formats_without_a_destination(tmp_path: Path, capsys) -> None:
    _, trace = run_fixture("gc_content", tmp_path)
    assert cli.main(["report", "--run", str(trace), "--format", "both"]) == 1
    assert "--format both requires --out" in capsys.readouterr().err


def test_report_refuses_to_write_many_claims_to_one_file(tmp_path: Path, capsys) -> None:
    run_dir = _suite_run(tmp_path)
    code = cli.main(["report", "--run", str(run_dir), "--out", str(tmp_path / "one.md")])
    assert code == 1
    assert "give --out a directory" in capsys.readouterr().err


def test_report_refuses_a_format_its_extension_denies(tmp_path: Path, capsys) -> None:
    _, trace = run_fixture("gc_content", tmp_path)
    args = ["report", "--run", str(trace), "--out", str(tmp_path / "r.md"), "--format", "html"]
    assert cli.main(args) == 1
    assert "does not match extension" in capsys.readouterr().err


def test_report_refuses_an_unknown_extension(tmp_path: Path, capsys) -> None:
    run_fixture("gc_content", tmp_path)
    out = tmp_path / "r.pdf"
    # `.pdf` is not a directory name we would fill, and not a format we render.
    assert RN.is_file_target(out) is False  # so it is treated as a directory, and works
    assert cli.main(["report", "--run", str(tmp_path), "--out", str(out)]) == 0
    assert (out / "gc_content.md").is_file()


def test_report_reports_a_missing_run_rather_than_raising(tmp_path: Path, capsys) -> None:
    assert cli.main(["report", "--run", str(tmp_path / "nowhere")]) == 1
    assert "no such trace or run directory" in capsys.readouterr().err


def test_report_reports_an_empty_run_directory(tmp_path: Path, capsys) -> None:
    assert cli.main(["report", "--run", str(tmp_path)]) == 1
    assert "no *.trace.jsonl" in capsys.readouterr().err


def test_report_reports_a_malformed_trace_without_a_traceback(tmp_path: Path, capsys) -> None:
    (tmp_path / "broken.trace.jsonl").write_text("{}\n")
    assert cli.main(["report", "--run", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "error:" in err and "Traceback" not in err


def test_report_exits_zero_on_a_contradicted_claim(tmp_path: Path) -> None:
    # Reporting a contradiction is the tool working, not failing — as with `verify`.
    _, trace = run_fixture("contradicted_f1", tmp_path)
    assert cli.main(["report", "--run", str(trace), "--out", str(tmp_path / "r.md")]) == 0


def test_the_report_command_is_registered_and_documented() -> None:
    parser = cli.build_parser()
    assert "report" in (parser.format_help() + (parser.epilog or ""))


def test_the_script_runs_without_an_install(tmp_path: Path) -> None:
    import subprocess
    import sys

    run_fixture("dataset_mean", tmp_path)
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "04_generate_report.py"),
         "--run", str(tmp_path), "--out", str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out" / "dataset_mean.md").is_file()
