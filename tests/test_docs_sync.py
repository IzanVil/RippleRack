"""The SemVer table in ``docs/concepts.md`` must describe what the engine really does.

The table is read from the documentation and every row is checked against
``diff_schemas``, so a rule cannot change in one place without the other noticing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ripplerack.models import Schema
from ripplerack.semver import diff_schemas

DOC = Path(__file__).resolve().parent.parent / "docs" / "concepts.md"
SECTION = "## Schema SemVer rules"


def schema(*fields: dict[str, object]) -> Schema:
    return Schema.model_validate({"name": "s", "version": "1.0.0", "fields": list(fields)})


def field(
    name: str, type_: str = "string", *, nullable: bool = False, **extra: object
) -> dict[str, object]:
    return {"name": name, "type": type_, "nullable": nullable, **extra}


# Each documented row, with the pairs of schemas (old, new) that exercise it.
CASES = [
    pytest.param(
        "field removed",
        [(schema(field("id"), field("email")), schema(field("id")))],
        id="removed",
    ),
    pytest.param(
        "field type changed",
        [(schema(field("id", "integer")), schema(field("id", "string")))],
        id="type-changed",
    ),
    pytest.param(
        "nullability widened (required → optional)",
        [(schema(field("email")), schema(field("email", nullable=True)))],
        id="widened",
    ),
    pytest.param(
        "required field added",
        [(schema(field("id")), schema(field("id"), field("extra")))],
        id="required-added",
    ),
    pytest.param(
        "optional field added",
        [(schema(field("id")), schema(field("id"), field("extra", nullable=True)))],
        id="optional-added",
    ),
    pytest.param(
        "nullability narrowed (optional → required)",
        [(schema(field("email", nullable=True)), schema(field("email")))],
        id="narrowed",
    ),
    pytest.param(
        "description changed or fields reordered",
        [
            (schema(field("id")), schema(field("id", description="primary key"))),
            (schema(field("a"), field("b")), schema(field("b"), field("a"))),
        ],
        id="patch",
    ),
]


def documented_rules() -> dict[str, tuple[str, str]]:
    """Rows of the table under the SemVer heading: ``change -> (level, breaks readers?)``."""
    lines = DOC.read_text(encoding="utf-8").splitlines()
    rules: dict[str, tuple[str, str]] = {}
    for line in lines[lines.index(SECTION) + 1 :]:
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] == "change" or set(cells[0]) <= {"-", ":"}:
            continue
        rules[cells[0]] = (cells[1], cells[2])
    return rules


def test_the_table_documents_exactly_the_rules_that_are_tested() -> None:
    tested = {case.values[0] for case in CASES}
    assert set(documented_rules()) == tested


@pytest.mark.parametrize(("row", "pairs"), CASES)
def test_the_engine_does_what_the_table_says(row: str, pairs: list[tuple[Schema, Schema]]) -> None:
    level, breaks_readers = documented_rules()[row]
    for old, new in pairs:
        diff = diff_schemas(old, new)
        assert diff.changes, f"{row}: the engine saw no change"
        assert str(diff.level) == level, f"{row}: documented as {level}, engine says {diff.level}"
        actual = "yes" if diff.reader_breaking_changes else "no"
        assert actual == breaks_readers, f"{row}: documented breaks-readers={breaks_readers}"
