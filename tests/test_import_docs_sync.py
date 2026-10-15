"""``docs/import.md`` must describe what ``ripplerack import`` really does.

The translation table is read from the documentation and every row is run through the
importer. The output the documentation shows must be the golden files, and every option and
every code the importer has must be written down, so that a rule cannot change in one place
without the other noticing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.main import get_command

from ripplerack.cli import app
from ripplerack.importers import IssueCode
from ripplerack.importers.json_schema import from_json_schema
from ripplerack.parser import ErrorCode
from tests.helpers import GOLDEN

ROOT = Path(__file__).resolve().parent.parent
IMPORT = ROOT / "docs" / "import.md"
OUTPUT_FORMATS = ROOT / "docs" / "output-formats.md"
README = ROOT / "README.md"
SECTION = "## Translation"
NO_DESCRIPTION = "—"


def unwrap(cell: str) -> str:
    return cell.strip("`")


def translation_rows() -> list[tuple[str, ...]]:
    """The rows of the first table under the Translation heading, as lists of cells."""
    lines = IMPORT.read_text(encoding="utf-8").splitlines()
    rows: list[tuple[str, ...]] = []
    for line in lines[lines.index(SECTION) + 1 :]:
        if line.startswith("#"):
            break
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if cells[0] == "Property schema" or set(cells[0]) <= {"-", " "}:
            continue
        rows.append(cells)
    return rows


ROWS = translation_rows()


def test_the_table_has_its_rows() -> None:
    assert len(ROWS) >= 20
    assert all(len(row) == 5 for row in ROWS)


@pytest.mark.parametrize("row", ROWS, ids=[row[0] for row in ROWS])
def test_the_importer_does_what_each_row_of_the_table_says(row: tuple[str, ...]) -> None:
    schema, in_required, field_type, nullable, description = row
    document: dict[str, Any] = {
        "type": "object",
        "properties": {"value": json.loads(unwrap(schema))},
    }
    if in_required == "yes":
        document["required"] = ["value"]
    [field] = from_json_schema(document, source="docs.json").schema.fields
    assert str(field.type) == unwrap(field_type)
    assert field.nullable is (unwrap(nullable) == "true")
    assert field.description == ("" if description == NO_DESCRIPTION else unwrap(description))


def test_the_known_limitations_come_before_the_translation_table() -> None:
    text = IMPORT.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines.index("## Known limitations") < lines.index(SECTION)
    limits = text[text.index("## Known limitations") : text.index("## Using it")]
    assert "**Enum values are not modelled structurally.**" in limits
    assert "**Nested objects and arrays are mapped to `json`.**" in limits
    assert "**A JSON Schema without `required` produces all fields nullable.**" in limits
    assert "**A schema that is a family of variants cannot be imported as one schema.**" in limits


# ---------------------------------------------------------------- what the docs show


def test_the_example_output_is_the_golden_file() -> None:
    golden = (GOLDEN / "import_orders_v2.yaml").read_text(encoding="utf-8")
    assert golden in IMPORT.read_text(encoding="utf-8")
    assert golden in README.read_text(encoding="utf-8")


def test_the_warnings_shown_are_real_ones() -> None:
    real = "".join(
        (GOLDEN / name).read_text(encoding="utf-8")
        for name in ("import_kitchen_sink.warnings.txt", "import_lenient.warnings.txt")
    ).splitlines()
    shown = [
        line
        for line in IMPORT.read_text(encoding="utf-8").splitlines()
        if line.startswith("warning[")
    ]
    assert shown
    for line in shown:
        assert line in real


def test_the_error_shown_is_the_real_one() -> None:
    golden = (GOLDEN / "import_lenient.error.txt").read_text(encoding="utf-8").rstrip("\n")
    assert golden in IMPORT.read_text(encoding="utf-8")


# --------------------------------------------------------- everything is written down


def test_every_option_of_the_command_is_documented() -> None:
    group: Any = get_command(app)
    options = {
        option
        for parameter in group.commands["import"].params
        for option in parameter.opts
        if option.startswith("-")
    }
    assert {"--from", "--output", "-o", "--name", "--version", "--lenient", "--force"} <= options
    documented = IMPORT.read_text(encoding="utf-8")
    for option in options:
        assert f"`{option}`" in documented, f"{option} is not documented"


@pytest.mark.parametrize("code", list(IssueCode))
def test_every_warning_code_is_documented(code: IssueCode) -> None:
    assert f"`{code.value}`" in IMPORT.read_text(encoding="utf-8")


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_error_code_is_documented_with_the_others(code: ErrorCode) -> None:
    assert f"`{code.value}`" in OUTPUT_FORMATS.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "code",
    [
        ErrorCode.FILE_NOT_FOUND,
        ErrorCode.IO_ERROR,
        ErrorCode.INVALID_JSON,
        ErrorCode.INVALID_JSON_SCHEMA,
        ErrorCode.UNSUPPORTED_JSON_SCHEMA,
        ErrorCode.OUTPUT_EXISTS,
    ],
)
def test_the_errors_import_can_give_are_explained_in_its_own_guide(code: ErrorCode) -> None:
    assert f"`{code.value}`" in IMPORT.read_text(encoding="utf-8")


# ------------------------------------------------------------------------------ links


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower().replace("`", ""))
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    found: set[str] = set()
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and (match := re.match(r"#{1,6}\s+(.*?)\s*$", line)):
            found.add(slug(match.group(1)))
    return found


def links(path: Path) -> list[tuple[str, str]]:
    """The ``(file, anchor)`` of every relative link outside code blocks."""
    found: list[tuple[str, str]] = []
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code:
            for target in re.findall(r"\]\(([^)\s]+)\)", line):
                if not re.match(r"[a-z]+:", target):
                    file, _, anchor = target.partition("#")
                    found.append((file, anchor))
    return found


@pytest.mark.parametrize("document", [IMPORT, README], ids=["import.md", "README.md"])
def test_the_links_to_the_import_guide_and_inside_it_resolve(document: Path) -> None:
    checked = 0
    for file, anchor in links(document):
        target = (document.parent / file).resolve() if file else document
        if document is README and target != IMPORT:
            continue
        assert target.exists(), f"{document.name} links to {file}, which does not exist"
        if anchor and target.suffix == ".md":
            assert anchor in anchors(target), (
                f"{document.name}: no heading #{anchor} in {target.name}"
            )
        checked += 1
    assert checked
