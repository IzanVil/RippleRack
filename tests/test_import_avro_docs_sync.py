"""``docs/import-avro.md`` must describe what ``import --from avro`` really does.

The translation table and the table of what is refused are read from the guide and every row is
run through the importer. The files and the output the guide shows must be the fixtures and the
golden files, and the option, the codes and the warning of an Avro import must be written down,
so that a rule cannot change in one place without the other noticing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ripplerack.importers import IssueCode
from ripplerack.importers.avro import from_avro
from ripplerack.parser import ErrorCode, RippleRackError
from tests.helpers import GOLDEN, SCHEMAS
from tests.markdown import anchors, links, table_under, unwrap

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "import-avro.md"
IMPORT = ROOT / "docs" / "import.md"
README = ROOT / "README.md"
GUIDE_TEXT = GUIDE.read_text(encoding="utf-8")
NO_VALUE = "—"


def one_field(type_cell: str, doc_cell: str = NO_VALUE) -> dict[str, Any]:
    """A record whose only field has the type, and the ``doc``, that a row of a table gives."""
    field: dict[str, Any] = {"name": "value", "type": json.loads(unwrap(type_cell))}
    if doc_cell != NO_VALUE:
        field["doc"] = unwrap(doc_cell)
    return {"type": "record", "name": "Row", "fields": [field]}


TRANSLATION = table_under(GUIDE_TEXT, "## Translation")
REFUSALS = table_under(GUIDE_TEXT, "### Unions and what is refused")
ERRORS = {unwrap(row[0]) for row in table_under(GUIDE_TEXT, "## Errors")}


def test_the_tables_have_their_rows() -> None:
    assert len(TRANSLATION) >= 25
    assert all(len(row) == 5 for row in TRANSLATION)
    assert len(REFUSALS) >= 8
    assert all(len(row) == 3 for row in REFUSALS)


@pytest.mark.parametrize("row", TRANSLATION, ids=[row[0] for row in TRANSLATION])
def test_the_importer_does_what_each_row_of_the_table_says(row: tuple[str, ...]) -> None:
    type_cell, doc, field_type, nullable, description = row
    [field] = from_avro(one_field(type_cell, doc), source="docs.avsc").schema.fields
    assert str(field.type) == unwrap(field_type)
    assert field.nullable is (unwrap(nullable) == "true")
    assert field.description == ("" if description == NO_VALUE else unwrap(description))


@pytest.mark.parametrize("row", REFUSALS, ids=[row[0] for row in REFUSALS])
def test_each_refusal_is_what_the_table_says(row: tuple[str, ...]) -> None:
    type_cell, strict, lenient = row
    document = one_field(type_cell)
    with pytest.raises(RippleRackError) as refused:
        from_avro(document, source="docs.avsc")
    assert refused.value.code is ErrorCode(unwrap(strict))

    if lenient.startswith("`json` field"):
        result = from_avro(document, source="docs.avsc", lenient=True)
        [field] = result.schema.fields
        assert str(field.type) == "json"
        assert field.nullable is ("nullable" in lenient)
        [issue] = result.issues
        assert issue.code is IssueCode.DEGRADED_TO_JSON
    else:
        with pytest.raises(RippleRackError) as still_refused:
            from_avro(document, source="docs.avsc", lenient=True)
        assert still_refused.value.code is ErrorCode(unwrap(lenient))


def test_the_known_limitations_come_before_the_translation_table() -> None:
    lines = GUIDE_TEXT.splitlines()
    assert lines.index("## Known limitations") < lines.index("## Translation")
    limits = GUIDE_TEXT[GUIDE_TEXT.index("## Known limitations") : GUIDE_TEXT.index("## Using it")]
    for title in (
        "**Decimals and bytes lose their exactness.**",
        "**Nested records, arrays and maps are mapped to `json`.**",
        "**Enum symbols are not modelled structurally.**",
        "**The namespace is not kept.**",
        "**One record per import.**",
    ):
        assert title in limits


# ---------------------------------------------------------------- what the guide shows


def golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8")


def test_the_example_output_is_the_golden_file() -> None:
    assert golden("import_orders_v2.yaml") in GUIDE_TEXT


def test_the_file_with_several_records_is_the_fixture_the_tests_use() -> None:
    fixture = (SCHEMAS / "shop.avsc").read_text(encoding="utf-8")
    assert fixture.rstrip("\n") in GUIDE_TEXT


def test_what_the_guide_shows_for_the_file_with_several_records_is_real() -> None:
    assert golden("import_avro_shop.yaml") in GUIDE_TEXT
    assert golden("import_avro_shop.error.txt").rstrip("\n") in GUIDE_TEXT


def test_the_error_and_the_warnings_shown_for_lenient_are_real() -> None:
    assert golden("import_avro_lenient.error.txt").rstrip("\n") in GUIDE_TEXT
    shown = [line for line in GUIDE_TEXT.splitlines() if line.startswith("warning[")]
    assert shown == golden("import_avro_lenient.warnings.txt").splitlines()


# --------------------------------------------------------- everything is written down


def test_the_option_that_belongs_to_avro_is_documented() -> None:
    assert "`--select`" in GUIDE_TEXT


@pytest.mark.parametrize(
    "code",
    [ErrorCode.INVALID_JSON, ErrorCode.INVALID_AVRO_SCHEMA, ErrorCode.UNSUPPORTED_AVRO_SCHEMA],
)
def test_the_errors_an_avro_import_can_give_are_explained_in_its_own_guide(
    code: ErrorCode,
) -> None:
    assert code.value in ERRORS


def test_the_warning_an_avro_import_gives_is_documented() -> None:
    assert f"`{IssueCode.DEGRADED_TO_JSON.value}`" in GUIDE_TEXT


# ------------------------------------------------------------------------------ links


def test_the_links_in_the_guide_resolve() -> None:
    checked = 0
    for file, anchor in links(GUIDE):
        target = (GUIDE.parent / file).resolve() if file else GUIDE
        assert target.exists(), f"the guide links to {file}, which does not exist"
        if anchor and target.suffix == ".md":
            assert anchor in anchors(target), f"no heading #{anchor} in {target.name}"
        checked += 1
    assert checked


@pytest.mark.parametrize("document", [IMPORT, README], ids=["import.md", "README.md"])
def test_the_links_to_the_guide_from_the_other_documents_resolve(document: Path) -> None:
    checked = 0
    for file, anchor in links(document):
        if file and (document.parent / file).resolve() == GUIDE:
            assert not anchor or anchor in anchors(GUIDE), f"no heading #{anchor} in the guide"
            checked += 1
    assert checked
