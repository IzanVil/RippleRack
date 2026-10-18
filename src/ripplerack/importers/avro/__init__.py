"""Read an Avro schema and translate one record of it into a RippleRack schema.

An ``.avsc`` file is JSON. The fields of the record become the fields of the schema, and a field
is ``nullable`` exactly when its type is a union with ``null``, which is how Avro says that a
value is optional. The ``doc`` of a field is its description. A record, an array or a map inside
a field is one ``json`` field, as a nested object is in a JSON Schema, and an enum keeps its
symbols in the description. A name that refers to a type defined elsewhere in the file is
resolved with the rules of Avro: one without a dot is looked up first in the namespace of the
record that uses it.

As with JSON Schema, what decides the type but has no equivalent is an error, so nothing is lost
without anyone noticing: a union of several types, for one. With ``lenient`` the field becomes a
``json`` one and a warning says so. ``docs/import-avro.md`` lists every rule.

The package has three parts: ``names`` knows what the file defines and which record to import,
``reader`` translates the fields of that record, and ``logical`` says what each logical type
makes of the type it sits on.
"""

from __future__ import annotations

from typing import Any

from ripplerack.importers.avro.reader import AvroReader
from ripplerack.importers.base import ImportResult
from ripplerack.importers.common import parse_json

__all__ = ["from_avro", "import_avro"]


def import_avro(
    text: str,
    *,
    source: str,
    name: str | None = None,
    version: str = "1.0.0",
    lenient: bool = False,
    select: str | None = None,
) -> ImportResult:
    """Parse the Avro schema in ``text`` and translate a record of it; ``source`` names it."""
    return from_avro(
        parse_json(text, source),
        source=source,
        name=name,
        version=version,
        lenient=lenient,
        select=select,
    )


def from_avro(
    document: Any,
    *,
    source: str,
    name: str | None = None,
    version: str = "1.0.0",
    lenient: bool = False,
    select: str | None = None,
) -> ImportResult:
    """Translate an already parsed Avro schema into a RippleRack schema.

    The record to import is the root of the file, the only record of a list of types, or the one
    ``select`` names: its full name, or its name alone when no other record has it. ``name``
    defaults to the name of the record, then the file name in ``source``. Raises
    :class:`RippleRackError` when the document cannot be imported.
    """
    reader = AvroReader(document, lenient=lenient)
    return reader.read(source=source, name=name, version=version, select=select)
