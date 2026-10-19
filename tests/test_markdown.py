"""The Markdown report: what it says, that it is safe in a comment and that it fits in one.

The scenarios of ``tests/scenarios.py`` are run with ``--format markdown`` and compared with golden
files (``RIPPLERACK_UPDATE_GOLDEN=1`` rewrites them: read the diff). The same scenarios run with
``--format json`` must say the same things. The text that comes from a file is the part to be
careful about, so it is tested with the characters that mean something in Markdown.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import assume, given
from hypothesis import strategies as st
from typer.testing import CliRunner

from ripplerack.cli import app
from ripplerack.diff import diff_datacenters
from ripplerack.markdown import (
    DEFAULT_MAX_ITEMS,
    MAX_CHARACTERS,
    MAX_VALUE,
    _code,
    _fence,
    _fit,
    _Style,
    diff_to_markdown,
)
from ripplerack.parser import parse_datacenter
from tests.helpers import (
    EXAMPLES,
    assert_text_golden,
    pipeline_of,
    raw_datacenter,
    server_of,
    set_orders_schema,
)
from tests.scenarios import SCENARIOS, Files, write_files

runner = CliRunner()
SCENARIO_NAMES = [name for name in SCENARIOS if name.startswith(("impact_", "diff_"))]
ORDERS_V2 = EXAMPLES / "changes" / "orders_v2.yaml"
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)
OPENING_FENCE = re.compile(r"^(`{3,})\w*$")


# ----------------------------------------------------------------------------- the scenarios


def with_readers(count: int, *, broken_in_head: bool = False) -> dict[str, Any]:
    """The mini datacenter and ``count`` pipelines that read every field of orders-ingest."""
    data = raw_datacenter()
    for number in range(count):
        data["pipelines"].append(
            {
                "id": f"reader-{number:04d}",
                "runs_on": "spark",
                "inputs": ["orders-ingest"],
                "schema": {
                    "name": f"reader_{number:04d}",
                    "version": "1.0.0",
                    "fields": [{"name": "x", "type": "string"}],
                },
            }
        )
    if broken_in_head:
        rename_amount(data)
    return data


def rename_amount(data: dict[str, Any]) -> None:
    """orders-ingest swaps ``amount`` for ``amount_cents``; orders-enriched follows, others not."""
    set_orders_schema(data, "2.0.0", drop="amount", name="amount_cents", type="integer")
    pipeline_of(data, "orders-enriched")["inputs"] = [
        {
            "pipeline": "orders-ingest",
            "fields": ["order_id", "customer_id", "amount_cents", "currency", "created_at"],
        }
    ]


def many_consumers_impact() -> tuple[Files, list[str]]:
    files = {"base.yaml": with_readers(40), "schema.yaml": yaml_of(ORDERS_V2)}
    return files, ["impact", "base.yaml", "-p", "orders-ingest", "-s", "schema.yaml"]


def many_broken_in_a_diff() -> tuple[Files, list[str]]:
    files = {"base.yaml": with_readers(40), "head.yaml": with_readers(40, broken_in_head=True)}
    return files, ["diff", "base.yaml", "head.yaml"]


def many_added_in_a_diff() -> tuple[Files, list[str]]:
    return {"base.yaml": raw_datacenter(), "head.yaml": with_readers(40)}, [
        "diff",
        "base.yaml",
        "head.yaml",
    ]


def yaml_of(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document


EXTRA_SCENARIOS: dict[str, Callable[[], tuple[Files, list[str]]]] = {
    "impact_many_consumers": many_consumers_impact,
    "diff_many_broken": many_broken_in_a_diff,
    "diff_many_added": many_added_in_a_diff,
}


def run(
    scenario: Callable[[], tuple[Files, list[str]]],
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    *options: str,
) -> Any:
    """Run the command of a scenario with some more options; the files are written in ``folder``."""
    files, args = scenario()
    write_files(files, folder)
    monkeypatch.chdir(folder)
    return runner.invoke(app, [*args, *options])


def markdown_of(
    scenario: Callable[[], tuple[Files, list[str]]],
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    *options: str,
) -> str:
    result = run(scenario, folder, monkeypatch, "-F", "markdown", *options)
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    text: str = result.stdout
    return text


# ------------------------------------------------------------------------ reading a report


def outside_code(text: str) -> list[str]:
    """The lines of a report without its fenced blocks, each code span reduced to ``¤``."""
    lines: list[str] = []
    fence = ""
    for line in text.split("\n"):
        if fence:
            if line.startswith(fence) and set(line) == {"`"}:
                fence = ""
            continue
        if opening := OPENING_FENCE.match(line):
            fence = opening.group(1)
            continue
        lines.append(CODE_SPAN.sub("¤", line))
    assert not fence, "a fenced block is never closed"
    return lines


def rows_after(text: str, label: str) -> list[list[str]]:
    """The rows of every table that follows a line that says ``label``, as lists of cells."""
    lines = text.split("\n")
    rows: list[list[str]] = []
    for index, line in enumerate(lines):
        if line != label:
            continue
        for row in lines[index + 4 :]:  # after the empty line, the header and its divider
            if not row.startswith("|"):
                break
            rows.append([cell.strip() for cell in UNESCAPED_PIPE.split(row.strip()[1:-1])])
    return rows


def unwrap(cell: str) -> str:
    return cell.strip("`")


def flat(error: str) -> str:
    """The message of a usage error: no colours, no frame, the lines of the panel joined."""
    return " ".join(re.sub(r"[│╭╮╰╯─]", " ", re.sub(r"\x1b\[[0-9;]*m", "", error)).split())


# ------------------------------------------------------------------------- golden files


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_what_the_markdown_report_says(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = markdown_of(SCENARIOS[name], tmp_path, monkeypatch)
    assert_text_golden(f"markdown_{name}.md", text)


@pytest.mark.parametrize("name", EXTRA_SCENARIOS)
def test_what_the_markdown_report_says_of_a_large_change(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = markdown_of(EXTRA_SCENARIOS[name], tmp_path, monkeypatch)
    assert_text_golden(f"markdown_{name}.md", text)


@pytest.mark.parametrize("name", [*SCENARIO_NAMES, *EXTRA_SCENARIOS])
def test_every_report_is_well_formed(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = SCENARIOS.get(name) or EXTRA_SCENARIOS[name]
    assert_well_formed(markdown_of(scenario, tmp_path, monkeypatch))


def assert_well_formed(text: str) -> None:
    """What every report must be: it ends in a line, fits in a comment, closes what it opens."""
    assert text.endswith("\n")
    assert len(text) <= MAX_CHARACTERS
    lines = outside_code(text)  # fails on a fence that is not closed
    assert lines.count("<details>") == lines.count("</details>")
    assert lines[0].startswith("## RippleRack · ")
    width: int | None = None
    for line in [*lines, ""]:
        if not line.startswith("|"):
            width = None
            continue
        cells = len(UNESCAPED_PIPE.findall(line))
        assert width in (None, cells), f"a row of another width in a table: {line}"
        width = cells


# ---------------------------------------------------------------------- the same as the JSON


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_the_report_and_the_json_document_say_the_same(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = markdown_of(SCENARIOS[name], tmp_path, monkeypatch, "--max-items", "0")
    result = run(SCENARIOS[name], tmp_path, monkeypatch, "-F", "json")
    document = json.loads(result.stdout)

    assert outside_code(report)[0].endswith(document["severity"].upper())
    if document["command"] == "impact":
        assert_same_impact(report, document)
    else:
        assert_same_diff(report, document)


def assert_same_impact(report: str, document: dict[str, Any]) -> None:
    summary = document["summary"]
    broken = [unwrap(row[0]) for row in rows_after(report, "**Broken consumers**")]
    assert broken == [c["pipeline"] for c in document["brokenConsumers"]]
    assert len(broken) == summary["broken"]
    at_risk = re.search(r"^At risk \((\d+)\):", report, re.MULTILINE)
    assert (int(at_risk.group(1)) if at_risk else 0) == summary["atRisk"]
    downstream = rows_after(report, "**Downstream components**")
    if downstream:
        assert [unwrap(row[1]) for row in downstream] == [n["id"] for n in document["affected"]]


def assert_same_diff(report: str, document: dict[str, Any]) -> None:
    broken = {unwrap(row[0]) for row in rows_after(report, "**Broken consumers**")}
    in_json = {c["pipeline"] for s in document["schemaChanges"] for c in s["brokenConsumers"]}
    assert broken == in_json
    assert len(broken) == document["summary"]["brokenConsumers"]
    assert report.count("\n### ") == document["summary"]["schemaChanges"]
    components = document["components"]
    changes = Counter(row[0] for row in component_rows(report))
    assert changes["added"] == len(components["added"])
    assert changes["removed"] == len(components["removed"])
    assert changes["modified"] == len(components["modified"])
    dependencies = Counter(row[0] for row in dependency_rows(report))
    assert dependencies["added"] == document["summary"]["dependenciesAdded"]
    assert dependencies["removed"] == document["summary"]["dependenciesRemoved"]
    assert dependencies["modified"] == document["summary"]["dependenciesModified"]


def component_rows(report: str) -> list[list[str]]:
    return folded_rows(report, "<summary>Components")


def dependency_rows(report: str) -> list[list[str]]:
    return folded_rows(report, "<summary>Dependencies")


def folded_rows(report: str, summary: str) -> list[list[str]]:
    """The rows of the table in the folded section whose summary starts with ``summary``."""
    lines = report.split("\n")
    rows: list[list[str]] = []
    for index, line in enumerate(lines):
        if line.startswith(summary):
            for row in lines[index + 4 :]:  # after the empty line, the header and its divider
                if not row.startswith("|"):
                    break
                rows.append([cell.strip() for cell in UNESCAPED_PIPE.split(row.strip()[1:-1])])
    return rows


# ------------------------------------------------------------------------------- the limits


def test_a_table_shows_max_items_rows_and_counts_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = markdown_of(many_consumers_impact, tmp_path, monkeypatch)
    broken = rows_after(text, "**Broken consumers**")
    assert len(broken) == DEFAULT_MAX_ITEMS
    assert f"_… and {42 - DEFAULT_MAX_ITEMS} more (use --max-items 0 to list all)_" in text
    assert "❌ broken 42" in text  # the counts at the top are the real ones


def test_max_items_chooses_how_many_rows_are_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = markdown_of(many_consumers_impact, tmp_path, monkeypatch, "--max-items", "3")
    assert len(rows_after(text, "**Broken consumers**")) == 3
    assert "_… and 39 more" in text


def test_zero_max_items_shows_every_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = markdown_of(many_consumers_impact, tmp_path, monkeypatch, "--max-items", "0")
    assert len(rows_after(text, "**Broken consumers**")) == 42
    assert "more (use --max-items" not in text


def test_the_diagram_is_left_out_when_the_change_reaches_more_than_max_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = markdown_of(many_consumers_impact, tmp_path, monkeypatch)
    assert "```mermaid" not in text
    assert "_Diagram left out: the change reaches 45 components" in text


def test_no_diagram_leaves_the_diagram_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with_diagram = markdown_of(SCENARIOS["diff_example_v2"], tmp_path, monkeypatch)
    without = markdown_of(SCENARIOS["diff_example_v2"], tmp_path, monkeypatch, "--no-diagram")
    assert "```mermaid" in with_diagram
    assert "mermaid" not in without
    assert "Diagram" not in without


def test_a_report_that_is_too_long_loses_its_diagrams_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def scenario() -> tuple[Files, list[str]]:
        files = {"base.yaml": with_readers(330), "schema.yaml": yaml_of(ORDERS_V2)}
        return files, ["impact", "base.yaml", "-p", "orders-ingest", "-s", "schema.yaml"]

    text = markdown_of(scenario, tmp_path, monkeypatch, "--max-items", "0")
    assert len(text) <= MAX_CHARACTERS
    assert "```mermaid" not in text
    assert "_This report was shortened to fit in a comment._" in text
    assert_well_formed(text)


def test_a_report_that_is_still_too_long_is_cut_at_a_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def scenario() -> tuple[Files, list[str]]:
        files = {"base.yaml": with_readers(900), "schema.yaml": yaml_of(ORDERS_V2)}
        return files, ["impact", "base.yaml", "-p", "orders-ingest", "-s", "schema.yaml"]

    text = markdown_of(scenario, tmp_path, monkeypatch, "--max-items", "0")
    assert len(text) <= MAX_CHARACTERS
    assert text.endswith("_… the rest of the report does not fit in a comment._\n")
    assert text.startswith("## RippleRack · 🔴 CRITICAL\n")
    assert_well_formed(text)


class Sized:
    """A report builder whose size depends on what the style includes; it notes what was tried."""

    def __init__(self, length: Callable[[_Style], int]) -> None:
        self.length = length
        self.tried: list[tuple[bool, bool]] = []

    def __call__(self, style: _Style) -> list[list[str]]:
        self.tried.append((style.diagram, style.details))
        return [["a" * self.length(style)]]


def test_a_report_loses_its_diagrams_before_anything_else() -> None:
    build = Sized(lambda style: MAX_CHARACTERS - 100 if not style.diagram else MAX_CHARACTERS + 1)
    text = _fit(build, 25, True)
    assert build.tried == [(True, True), (False, True)]
    assert text.endswith("_This report was shortened to fit in a comment._\n")


def test_a_report_loses_its_lists_of_components_only_after_its_diagrams() -> None:
    build = Sized(lambda style: MAX_CHARACTERS - 100 if not style.details else MAX_CHARACTERS + 1)
    text = _fit(build, 25, True)
    assert build.tried == [(True, True), (False, True), (False, False)]
    assert len(text) <= MAX_CHARACTERS


def test_a_report_that_fits_is_not_changed_and_says_nothing() -> None:
    build = Sized(lambda style: 100)
    text = _fit(build, 25, False)
    assert build.tried == [(False, True)]
    assert text == "a" * 100 + "\n"


def test_a_long_text_from_a_file_is_shortened() -> None:
    span = _code("x" * 1000)
    assert len(span) == MAX_VALUE + 2
    assert span.endswith("…`")


# ------------------------------------------------------------------------------- the command


@pytest.mark.parametrize("name", ["diff_example_v2", "impact_breaking_change"])
def test_fail_on_breaking_prints_the_report_and_exits_with_2(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run(SCENARIOS[name], tmp_path, monkeypatch, "-F", "markdown", "--fail-on-breaking")
    assert result.exit_code == 2
    assert result.stdout.startswith("## RippleRack · ")


@pytest.mark.parametrize("command", ["impact", "diff"])
@pytest.mark.parametrize("option", [["--max-items", "5"], ["--diagram"], ["--no-diagram"]])
@pytest.mark.parametrize("fmt", ["text", "json"])
def test_the_options_of_the_report_are_a_usage_error_with_another_format(
    command: str, option: list[str], fmt: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "impact_breaking_change" if command == "impact" else "diff_example_v2"
    result = run(SCENARIOS[name], tmp_path, monkeypatch, "-F", fmt, *option)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "only applies to --format markdown" in flat(result.stderr)


def test_a_negative_max_items_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run(
        SCENARIOS["diff_example_v2"], tmp_path, monkeypatch, "-F", "markdown", "--max-items", "-1"
    )
    assert result.exit_code == 2


@pytest.mark.parametrize("command", ["impact", "diff"])
def test_an_error_is_plain_text_and_leaves_the_output_empty(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    args = (
        ["impact", "x.yaml", "-p", "p", "-s", "y.yaml"]
        if command == "impact"
        else ["diff", "x.yaml", "y.yaml"]
    )
    result = runner.invoke(app, [*args, "-F", "markdown"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert flat(result.stderr).startswith("error: file not found")


def test_the_unknown_pipeline_of_an_impact_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_files({"dc.yaml": raw_datacenter(), "s.yaml": yaml_of(ORDERS_V2)}, tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["impact", "dc.yaml", "-p", "ghost", "-s", "s.yaml", "-F", "markdown"]
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "unknown pipeline 'ghost'" in flat(result.stderr)


def test_the_report_is_the_same_in_every_run(tmp_path: Path) -> None:
    """The diagram follows the order of the graph, not the order of a set, which changes."""
    data = raw_datacenter()
    server_of(data, "srv-a1")["services"] += [
        {"id": f"filler-{n:02d}", "cpu_cores": 0, "memory_gb": 0} for n in range(40)
    ]
    write_files({"dc.yaml": data, "schema.yaml": yaml_of(ORDERS_V2)}, tmp_path)
    command = [
        "from ripplerack.cli import app; app()",
        "impact",
        "dc.yaml",
        "-p",
        "orders-ingest",
        "-s",
        "schema.yaml",
        "-F",
        "markdown",
    ]
    outputs = {
        seed: subprocess.run(
            [sys.executable, "-c", *command],
            cwd=tmp_path,
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("1", "2", "3")
    }
    assert "```mermaid" in outputs["1"]
    assert "pl_customer_360" in outputs["1"]  # the zone has several pipelines to put in an order
    assert len(set(outputs.values())) == 1


# -------------------------------------------------------------------------- text from a file

DANGEROUS = [
    "|", ">", "<", "&", "#", "**", "_", "__", "@", "@team", "#12", "`", "``", "```", "\\", "\\|",
    "[", "]", "(", ")", "!", "~", "$", '"', "'", ":", "-", "+", "=", "</details>", "<details>",
    "<script>", "<br>", "&amp;", "|---|", "\n", "\r\n", "\t", "\u2028", "\x85", "\u200b", "\u202e",
]  # fmt: skip
TEXT = st.lists(
    st.sampled_from([*DANGEROUS, "a", "Z", "7", " ", "é", "😀"]), min_size=1, max_size=8
).map("".join)
BENIGN = ("a", "b", "c", "d", "e", "f")


MINI = raw_datacenter()


def reports_of(texts: tuple[str, str, str, str, str, str]) -> str:
    """The report of a comparison where the name, the description and a service use these texts."""
    base, head = copy.deepcopy(MINI), copy.deepcopy(MINI)
    for data, (name, description, service) in ((base, texts[0::2]), (head, texts[1::2])):
        data["name"], data["description"] = name, description
        server_of(data, "srv-a1")["services"][1]["description"] = service
    rename_amount(head)
    loaded_head = parse_datacenter(head)
    result = diff_datacenters(parse_datacenter(base), loaded_head)
    return diff_to_markdown(result, loaded_head.graph)


def skeleton(text: str) -> Counter[str]:
    """Every line of a report that is not code, once the text of a file has become ``¤``."""
    return Counter(outside_code(text))


@given(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT)
def test_the_text_of_a_file_never_changes_the_structure_of_a_report(
    name_a: str, name_b: str, desc_a: str, desc_b: str, service_a: str, service_b: str
) -> None:
    assume(name_a != name_b and desc_a != desc_b and service_a != service_b)
    hostile = reports_of((name_a, name_b, desc_a, desc_b, service_a, service_b))
    # the same comparison with tame names: the only difference is what the files say
    assert skeleton(hostile) == skeleton(reports_of(BENIGN))
    assert_well_formed(hostile)


@pytest.mark.parametrize("character", DANGEROUS)
def test_each_character_that_means_something_is_shown_as_code(character: str) -> None:
    name = f"x{character}y"
    report = reports_of((name, name + "2", "d1", "d2", "s1", "s2"))
    assert skeleton(report) == skeleton(reports_of(BENIGN))
    assert_well_formed(report)
    assert _code(name) in report  # the character is shown, as code


@given(st.text(max_size=300))
def test_any_text_is_one_code_span(text: str) -> None:
    span = _code(text)
    assert CODE_SPAN.fullmatch(span), span
    assert "\n" not in span
    assert "\r" not in span
    opening = re.match(r"`+", span)
    assert opening is not None
    ticks = opening.group(0)
    content = span[len(ticks) : -len(ticks)]
    if content.startswith(" ") and content.endswith(" ") and content.strip():
        content = content[1:-1]  # what CommonMark does with a space on each side
    flat = " ".join(text.split()) or " "
    expected = flat if len(flat) <= MAX_VALUE else flat[: MAX_VALUE - 1].rstrip() + "…"
    assert content == expected


@given(st.text(max_size=100))
def test_in_a_table_cell_every_pipe_is_escaped(text: str) -> None:
    span = _code(text, cell=True)
    assert not UNESCAPED_PIPE.search(span)


@given(st.text(alphabet="`ab\n", max_size=60))
def test_no_line_of_a_text_closes_its_fence(text: str) -> None:
    lines = _fence(text, "mermaid")
    inside = lines[1:-1]
    closing = lines[-1]
    assert all(not (line.startswith(closing) and set(line) == {"`"}) for line in inside)
    assert len(closing) >= 3
