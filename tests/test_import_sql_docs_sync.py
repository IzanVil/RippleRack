"""``docs/import-sql.md`` must describe what ``import --from sql`` really does.

The translation table and the table of what is refused are read from the guide and every row is
run through the importer. The files and the output the guide shows must be the fixtures and the
golden files, and the options, the codes and the warning of a SQL import must be written down,
so that a rule cannot change in one place without the other noticing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ripplerack.importers import IssueCode
from ripplerack.importers.sql import import_sql
from ripplerack.importers.sql.column_types import PLAIN_TYPES, REFUSED
from ripplerack.parser import ErrorCode, RippleRackError
from tests.helpers import GOLDEN, SCHEMAS
from tests.markdown import anchors, links, table_under, unwrap

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "import-sql.md"
IMPORT = ROOT / "docs" / "import.md"
README = ROOT / "README.md"
GUIDE_TEXT = GUIDE.read_text(encoding="utf-8")
NO_VALUE = "—"

TRANSLATION = table_under(GUIDE_TEXT, "## Translation")
REFUSALS = table_under(GUIDE_TEXT, "### What is refused")
ERRORS = {unwrap(row[0]) for row in table_under(GUIDE_TEXT, "## Errors")}


def test_the_tables_have_their_rows() -> None:
    assert len(TRANSLATION) >= 50
    assert all(len(row) == 5 for row in TRANSLATION)
    assert len(REFUSALS) >= 7
    assert all(len(row) == 4 for row in REFUSALS)


@pytest.mark.parametrize("row", TRANSLATION, ids=[f"{row[0]} {row[1]}" for row in TRANSLATION])
def test_the_importer_does_what_each_row_of_the_table_says(row: tuple[str, ...]) -> None:
    dialect, column, field_type, nullable, description = row
    sql = f"CREATE TABLE t (value {unwrap(column)});"
    [field] = import_sql(sql, source="docs.sql", dialect=unwrap(dialect)).schema.fields
    assert field.name == "value"
    assert str(field.type) == unwrap(field_type)
    assert field.nullable is (unwrap(nullable) == "true")
    assert field.description == ("" if description == NO_VALUE else unwrap(description))


@pytest.mark.parametrize("row", REFUSALS, ids=[f"{row[0]} {row[1]}" for row in REFUSALS])
def test_each_refusal_is_what_the_table_says(row: tuple[str, ...]) -> None:
    dialect, columns, strict, lenient = row
    sql = f"CREATE TABLE t ({unwrap(columns)});"
    with pytest.raises(RippleRackError) as refused:
        import_sql(sql, source="docs.sql", dialect=unwrap(dialect))
    assert refused.value.code is ErrorCode(unwrap(strict))

    if lenient.startswith("`json` field"):
        result = import_sql(sql, source="docs.sql", dialect=unwrap(dialect), lenient=True)
        [field] = (found for found in result.schema.fields if found.name == "c")
        assert str(field.type) == "json"
        [issue] = result.issues
        assert issue.code is IssueCode.DEGRADED_TO_JSON
    else:
        with pytest.raises(RippleRackError) as still_refused:
            import_sql(sql, source="docs.sql", dialect=unwrap(dialect), lenient=True)
        assert still_refused.value.code is ErrorCode(unwrap(lenient))


def test_the_known_limitations_come_before_the_translation_table() -> None:
    lines = GUIDE_TEXT.splitlines()
    assert lines.index("## Known limitations") < lines.index("## Translation")
    limits = GUIDE_TEXT[GUIDE_TEXT.index("## Known limitations") : GUIDE_TEXT.index("## Using it")]
    for title in (
        "**Numbers, sizes and bytes lose their exactness.**",
        "**Arrays and structures are mapped to `json`.**",
        "**Enum values are not modelled structurally.**",
        "**One table per import.**",
        "**The columns are the ones `CREATE TABLE` gives.**",
        "**The parser has its limits.**",
    ):
        assert title in limits


def test_the_number_of_types_the_guide_gives_is_the_real_one() -> None:
    assert f"There are {len(PLAIN_TYPES)} plain types" in GUIDE_TEXT
    assert f"They are {len(REFUSED)} in all" in GUIDE_TEXT


# ---------------------------------------------------------------- what the guide shows


def golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8")


def test_the_example_output_is_the_golden_file() -> None:
    assert golden("import_orders_v2.yaml") in GUIDE_TEXT


def test_the_file_with_several_tables_is_the_fixture_the_tests_use() -> None:
    fixture = (SCHEMAS / "shop.sql").read_text(encoding="utf-8")
    assert fixture.rstrip("\n") in GUIDE_TEXT


def test_what_the_guide_shows_for_the_file_with_several_tables_is_real() -> None:
    assert golden("import_sql_shop.yaml") in GUIDE_TEXT
    assert golden("import_sql_shop.error.txt").rstrip("\n") in GUIDE_TEXT


def test_the_error_for_a_file_in_another_dialect_is_real() -> None:
    assert golden("import_sql_mysqldump.error.txt").rstrip("\n") in GUIDE_TEXT


def test_the_error_and_the_warnings_shown_for_lenient_are_real() -> None:
    assert golden("import_sql_lenient.error.txt").rstrip("\n") in GUIDE_TEXT
    shown = [line for line in GUIDE_TEXT.splitlines() if line.startswith("warning[")]
    assert shown == golden("import_sql_lenient.warnings.txt").splitlines()


def test_the_error_shown_for_an_alter_table_is_real() -> None:
    sql = "CREATE TABLE t (a int);\nALTER TABLE t ADD COLUMN b int;"
    with pytest.raises(RippleRackError) as refused:
        import_sql(sql, source="t.sql")
    assert f"error: {refused.value}" in GUIDE_TEXT


# --------------------------------------------------------- everything is written down


@pytest.mark.parametrize("option", ["`--dialect`", "`--select`"])
def test_the_options_that_belong_to_sql_are_documented(option: str) -> None:
    assert option in GUIDE_TEXT


@pytest.mark.parametrize("code", [ErrorCode.INVALID_SQL, ErrorCode.UNSUPPORTED_SQL])
def test_the_errors_a_sql_import_can_give_are_explained_in_its_own_guide(code: ErrorCode) -> None:
    assert code.value in ERRORS


def test_the_warning_a_sql_import_gives_is_documented() -> None:
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
