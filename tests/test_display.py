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
