"""What the tests of the SQL importer share: read a piece of SQL, and say what came out."""

from __future__ import annotations

from typing import Any

import pytest

from ripplerack.importers import ImportIssue
from ripplerack.importers.sql import import_sql
from ripplerack.parser import ErrorCode, RippleRackError


def fields(sql: str, **options: Any) -> list[tuple[str, str, bool, str]]:
    """``(name, type, nullable, description)`` of every imported field."""
    result = import_sql(sql, source="test.sql", **options)
    return [(f.name, str(f.type), f.nullable, f.description) for f in result.schema.fields]


def one(column: str, **options: Any) -> tuple[str, bool, str]:
    """``(type, nullable, description)`` of a single column called ``c``, written as ``column``."""
    [(name, field_type, nullable, description)] = fields(f"CREATE TABLE t (c {column});", **options)
    assert name == "c"
    return field_type, nullable, description


def issues(sql: str, **options: Any) -> list[ImportIssue]:
    return list(import_sql(sql, source="test.sql", **options).issues)


def fails(sql: str, code: ErrorCode, *fragments: str, **options: Any) -> str:
    """Import ``sql``, expect ``code`` and the given fragments in the message."""
    with pytest.raises(RippleRackError) as excinfo:
        import_sql(sql, source="test.sql", **options)
    message = str(excinfo.value)
    assert excinfo.value.code is code, message
    for fragment in fragments:
        assert fragment in message, message
    return message
