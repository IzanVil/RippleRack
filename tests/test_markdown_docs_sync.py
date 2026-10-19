"""The Markdown section of ``docs/output-formats.md`` must describe what the report really does.

The words and emoji of the severities and statuses, the options and their defaults and the limits
are read from the guide and compared with the code, so that none of them can change in one place
without the other noticing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ripplerack.cli import app
from ripplerack.markdown import (
    DEFAULT_MAX_ITEMS,
    MAX_CHARACTERS,
    MAX_VALUE,
    SEVERITY_LABELS,
    STATUS_LABELS,
)
from tests.markdown import anchors, links, table_under, unwrap

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "output-formats.md"
README = ROOT / "README.md"
TEXT = GUIDE.read_text(encoding="utf-8")
runner = CliRunner()
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_the_severities_and_statuses_are_written_as_the_guide_says() -> None:
    rows = table_under(TEXT, "### Severities and statuses")
    documented = {unwrap(word): label for word, label in rows}
    written = {
        **{str(severity): label for severity, label in SEVERITY_LABELS.items()},
        **{status.value: label for status, label in STATUS_LABELS.items()},
    }
    assert documented == written


def test_the_options_of_the_guide_are_the_ones_the_commands_have() -> None:
    rows = table_under(TEXT, "### Options")
    options = {option for cell, *_ in rows for option in re.findall(r"--[a-z-]+", cell)}
    assert options == {"--max-items", "--diagram", "--no-diagram"}
    for command in ("impact", "diff"):
        result = runner.invoke(app, [command, "--help"], env={"COLUMNS": "200"})
        help_text = ANSI.sub("", result.output)
        assert all(option in help_text for option in options), command


def test_the_default_of_max_items_is_the_one_the_guide_gives() -> None:
    rows = {cell: default for cell, default, _ in table_under(TEXT, "### Options")}
    assert rows["`--max-items N`"] == f"`{DEFAULT_MAX_ITEMS}`"


def test_the_limits_of_the_guide_are_the_real_ones() -> None:
    flat = " ".join(TEXT.split())
    assert "more than 65,536 characters" in flat  # what GitHub refuses
    assert f"longer than {MAX_CHARACTERS:,}" in flat
    assert f"more than {MAX_VALUE} characters" in flat


def test_the_markdown_report_has_its_section_and_its_table_of_contents_entry() -> None:
    assert "## Markdown" in TEXT.splitlines()
    assert "[Markdown report](#markdown)" in TEXT


@pytest.mark.parametrize("document", [GUIDE, README], ids=["output-formats.md", "README.md"])
def test_the_links_to_the_markdown_section_and_inside_the_guide_resolve(document: Path) -> None:
    checked = 0
    for file, anchor in links(document):
        target = (document.parent / file).resolve() if file else document
        if document is README and target != GUIDE:
            continue
        assert target.exists(), f"{document.name} links to {file}, which does not exist"
        if anchor and target.suffix == ".md":
            assert anchor in anchors(target), (
                f"{document.name}: no heading #{anchor} in {target.name}"
            )
        checked += 1
    assert checked
