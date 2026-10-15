"""Import schemas from other formats into RippleRack's own.

Each importer reads the text of a file and returns an :class:`ImportResult`: the schema, plus
the warnings about whatever could not be carried over exactly. Anything that cannot be
imported at all is a :class:`~ripplerack.parser.RippleRackError`.
"""

from __future__ import annotations

from ripplerack.importers.base import (
    Importer,
    ImportIssue,
    ImportResult,
    IssueCode,
    SourceFormat,
)
from ripplerack.importers.json_schema import import_json_schema

IMPORTERS: dict[SourceFormat, Importer] = {SourceFormat.JSON_SCHEMA: import_json_schema}

__all__ = [
    "IMPORTERS",
    "ImportIssue",
    "ImportResult",
    "Importer",
    "IssueCode",
    "SourceFormat",
]
