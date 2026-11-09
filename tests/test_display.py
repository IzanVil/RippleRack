"""What the commands print for people, pinned with golden files.

Each scenario (see ``tests/scenarios.py``) writes its files in a folder, runs one command and
compares what it prints (a terminal of 110 columns, without colours) with a file in
``tests/golden/``. Together the scenarios draw every table, line and branch of ``display.py``,
which the JSON and Mermaid tests do not reach. Run the tests with ``RIPPLERACK_UPDATE_GOLDEN=1``
to rewrite the files, and read the diff.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ripplerack.cli import app
from ripplerack.diff import AttributeChange
from ripplerack.display import _describe_change
from tests.helpers import assert_text_golden
from tests.scenarios import SCENARIOS, write_files

runner = CliRunner()
ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.mark.parametrize("name", SCENARIOS)
def test_what_the_command_prints(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files, args = SCENARIOS[name]()
    write_files(files, tmp_path)
    monkeypatch.chdir(tmp_path)  # so that the file names in the output are the same everywhere
    result = runner.invoke(app, args, env={"COLUMNS": "110"})
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert_text_golden(f"display_{name}.txt", ANSI.sub("", result.stdout))


def printed(name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    files, args = SCENARIOS[name]()
    write_files(files, tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, args, env={"COLUMNS": "110"})
    assert result.exit_code == 0, result.output
    return ANSI.sub("", result.stdout)


@pytest.mark.parametrize(
    ("name", "lines"),
    [
        (
            "simulate_default",
            [
                "Pipelines",
                "Bottleneck: orders-enriched at 89% (400 of 450 records/s)",
                "Slowest path: orders-ingest → orders-enriched → revenue-daily, 332 s",
            ],
        ),
        ("simulate_flow_light_load", ["No bottleneck (busiest: orders-enriched at 44%)"]),
        (
            "simulate_flow_surge",
            [
                "Bottleneck: orders-ingest at 120% (600 of 500 records/s)",
                "✗ Overloaded: rack-a, srv-a2, orders-ingest, orders-enriched",
            ],
        ),
        ("simulate_flow_failure", ["Slowest path: orders-ingest → customer-360, 7 s"]),
        ("simulate_flow_without_arrival", ["Pipelines", "Slowest path:"]),
    ],
)
def test_the_simulation_says_where_the_data_piles_up_and_how_slow_it_is(
    name: str, lines: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = printed(name, tmp_path, monkeypatch)
    for line in lines:
        assert line in text


@pytest.mark.parametrize(
    ("name", "missing"),
    [
        ("simulate_flow_everything_down", ["Bottleneck", "Slowest path"]),
        ("simulate_flow_without_arrival", ["Bottleneck"]),
        ("simulate_without_flow_numbers", ["Pipelines", "Bottleneck", "Slowest path"]),
    ],
)
def test_what_cannot_be_known_or_is_not_declared_is_not_printed(
    name: str, missing: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = printed(name, tmp_path, monkeypatch)
    for line in missing:
        assert line not in text


def test_an_infinite_load_prints_no_nan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = printed("simulate_flow_infinite_load_on_an_idle_source", tmp_path, monkeypatch)
    assert "nan" not in text.lower()


@pytest.mark.parametrize(
    ("attribute", "before", "after", "expected"),
    [
        ("cpu_cores", 32, 48, "cpu_cores: 32 → 48"),
        ("power_capacity_kw", 2.8, 3.0, "power_capacity_kw: 2.8 → 3"),
        ("description", "", "Event broker", "description: (empty) → Event broker"),
        ("description", "Event broker", "", "description: Event broker → (empty)"),
        ("name", "mini", "mini-2", "name: mini → mini-2"),
        ("tags", ["a", "b"], [], "tags: a, b → (none)"),
        ("note", "[bold]x[/]", "y", "note: \\[bold]x\\[/] → y"),  # markup is printed as it is
        ("schema.fields", [{"name": "a"}], [], "schema.fields: changed (see below)"),
        ("inputs", "old", "new", "inputs: old → new"),
        (
            "inputs",
            [{"pipeline": "p", "fields": ["a"]}],
            [{"pipeline": "p", "fields": None}],
            "inputs: p: a → all fields",
        ),
        (
            "inputs",
            [{"pipeline": "p", "fields": ["a"]}],
            [{"pipeline": "p", "fields": ["a"]}, {"pipeline": "q", "fields": None}],
            "inputs: +q",
        ),
        (
            "inputs",
            [{"pipeline": "p", "fields": ["a", "a"]}],
            [{"pipeline": "p", "fields": ["a"]}],
            "inputs: p: ",
        ),
    ],
)
def test_one_changed_attribute_is_described_in_a_line(
    attribute: str, before: object, after: object, expected: str
) -> None:
    assert _describe_change(AttributeChange(attribute, before, after)) == expected
