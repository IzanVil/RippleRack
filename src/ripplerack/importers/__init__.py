"""Import schemas from other formats into RippleRack's own.

Each importer reads the text of a file and returns an :class:`ImportResult`: the schema, plus
the warnings about whatever could not be carried over exactly. Anything that cannot be
imported at all is a :class:`~ripplerack.parser.RippleRackError`. What the formats share (reading
JSON, naming a schema, reporting problems) lives in :mod:`ripplerack.importers.common`.
"""

from __future__ import annotations

from ripplerack.importers.avro import import_avro
from ripplerack.importers.base import (
    STDIN,
    Importer,
    ImportIssue,
    ImportResult,
    IssueCode,
    SourceFormat,
    is_identifier,
    is_version,
    read_text,
    source_label,
)
from ripplerack.importers.json_schema import import_json_schema
from ripplerack.importers.render import render_schema_yaml
from ripplerack.importers.sql import import_sql, sql_dialects

IMPORTERS: dict[SourceFormat, Importer] = {
    SourceFormat.JSON_SCHEMA: import_json_schema,
    SourceFormat.AVRO: import_avro,
    SourceFormat.SQL: import_sql,
}
# The formats whose files can define several schemas, one of which ``--select`` picks.
SELECTABLE: frozenset[SourceFormat] = frozenset({SourceFormat.AVRO, SourceFormat.SQL})
# The formats that come in flavours, which ``--dialect`` names.
DIALECTABLE: frozenset[SourceFormat] = frozenset({SourceFormat.SQL})

__all__ = [
    "DIALECTABLE",
    "IMPORTERS",
    "SELECTABLE",
    "STDIN",
    "ImportIssue",
    "ImportResult",
    "Importer",
    "IssueCode",
    "SourceFormat",
    "is_identifier",
    "is_version",
    "read_text",
    "render_schema_yaml",
    "source_label",
    "sql_dialects",
]
