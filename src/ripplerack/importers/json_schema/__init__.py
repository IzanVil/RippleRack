"""Read a JSON Schema and translate it into a RippleRack schema.

A RippleRack schema is flat and small: a list of fields, each with one of seven types and a
``nullable`` flag. A JSON Schema can say far more, so the reader only looks at the keywords
that decide which fields exist, what type they have and whether they are optional. Every
other keyword (value constraints such as ``minimum`` or ``pattern``, annotations, vendor
extensions) is ignored.

A construct that does decide the type but has no equivalent is an error, so nothing is lost
without anyone noticing. With ``lenient`` the property becomes a ``json`` field and a
warning says so. ``docs/import.md`` lists every rule.

The package has four parts: ``walker`` moves through the document (``$ref``, ``allOf``),
``field_types`` says what one property schema means, ``reader`` builds the fields of the root
object from both, and ``problems`` makes the two kinds of problem.
"""

from __future__ import annotations

from typing import Any

from ripplerack.importers.base import ImportResult
from ripplerack.importers.common import parse_json
from ripplerack.importers.json_schema.reader import JsonSchemaReader
from ripplerack.parser import ErrorCode, RippleRackError

__all__ = ["from_json_schema", "import_json_schema", "parse_json"]


def import_json_schema(
    text: str,
    *,
    source: str,
    name: str | None = None,
    version: str = "1.0.0",
    lenient: bool = False,
    select: str | None = None,
    dialect: str | None = None,
) -> ImportResult:
    """Parse the JSON Schema in ``text`` and translate it; ``source`` names it in messages.

    A JSON Schema file describes one schema, so there is nothing to ``select``, and it is not SQL,
    so it has no ``dialect``.
    """
    if select is not None:
        raise ValueError("select does not apply to JSON Schema: a file describes one schema")
    if dialect is not None:
        raise ValueError("dialect does not apply to JSON Schema: it is not SQL")
    return from_json_schema(
        parse_json(text, source), source=source, name=name, version=version, lenient=lenient
    )


def from_json_schema(
    document: Any,
    *,
    source: str,
    name: str | None = None,
    version: str = "1.0.0",
    lenient: bool = False,
) -> ImportResult:
    """Translate an already parsed JSON Schema into a RippleRack schema.

    ``name`` defaults to the root ``title``, then the last part of ``$id``, then the file
    name in ``source``. Raises :class:`RippleRackError` when the document cannot be imported.
    """
    try:
        return JsonSchemaReader(document, lenient=lenient).read(
            source=source, name=name, version=version
        )
    except RecursionError as exc:  # a document nested beyond what Python can compare or print
        raise RippleRackError(
            f"{source}: cannot import this JSON Schema: it is nested too deeply",
            ErrorCode.INVALID_JSON_SCHEMA,
        ) from exc
