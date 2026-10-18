"""The registry of importers: one importer for each format, all of them called in the same way."""

from __future__ import annotations

import json

import pytest

from ripplerack.importers import DIALECTABLE, IMPORTERS, SELECTABLE, SourceFormat
from ripplerack.importers.json_schema import import_json_schema

# A document of each format that imports without a word: when a format is added, so is its sample.
SAMPLES = {
    SourceFormat.JSON_SCHEMA: '{"properties": {"a": {"type": "string"}}}',
    SourceFormat.AVRO: json.dumps(
        {"type": "record", "name": "Row", "fields": [{"name": "a", "type": "long"}]}
    ),
    SourceFormat.SQL: "CREATE TABLE s (a BIGINT NOT NULL);",
}


def test_every_format_has_an_importer_and_a_sample() -> None:
    assert set(IMPORTERS) == set(SourceFormat)
    assert set(SAMPLES) == set(SourceFormat)


@pytest.mark.parametrize("source_format", list(SourceFormat))
def test_the_importer_of_each_format_is_called_with_the_same_arguments(
    source_format: SourceFormat,
) -> None:
    result = IMPORTERS[source_format](
        SAMPLES[source_format],
        source="<stdin>",
        name="s",
        version="1.0.0",
        lenient=False,
        select=None,
        dialect=None,
    )
    assert result.schema.name == "s"
    assert result.issues == ()


def test_the_formats_that_define_several_schemas_can_select() -> None:
    assert set(SELECTABLE) == {SourceFormat.AVRO, SourceFormat.SQL}


def test_sql_is_the_only_format_that_has_a_dialect() -> None:
    assert set(DIALECTABLE) == {SourceFormat.SQL}


def test_a_json_schema_has_nothing_to_select() -> None:
    with pytest.raises(ValueError, match="select does not apply to JSON Schema"):
        import_json_schema('{"properties": {"a": {}}}', source="x.json", select="Order")
