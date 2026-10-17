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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeGuard

from pydantic import ValidationError

from ripplerack.importers.base import ImportResult, IssueCode, is_identifier
from ripplerack.importers.common import (
    Reader,
    ReadError,
    child,
    describe,
    file_name,
    one_line,
    parse_json,
    slug,
    strip_suffixes,
    summarize,
    values_note,
    with_note,
)
from ripplerack.models import FieldType, Schema, SchemaField
from ripplerack.parser import ErrorCode, RippleRackError

__all__ = ["from_avro", "import_avro"]

_MAX_DEPTH = 32
_LISTED = 10  # how many names a message lists before it counts the rest
_PLAIN_TYPES = {
    "boolean": FieldType.BOOLEAN,
    "int": FieldType.INTEGER,
    "long": FieldType.INTEGER,
    "float": FieldType.FLOAT,
    "double": FieldType.FLOAT,
    "bytes": FieldType.STRING,
    "string": FieldType.STRING,
}
_RECORDS = ("record", "error")
_NAMED_KINDS = (*_RECORDS, "enum", "fixed")
_NEEDS_A_NAME = {
    "record": "a record",
    "error": "an error",
    "enum": "an enum",
    "fixed": "a fixed type",
}
# The logical types of the specification: the types each can sit on and what it makes of them.
# One that is unknown, or sits on a type it does not fit, is ignored, as the specification asks.
_LOGICAL_TYPES: dict[str, tuple[frozenset[str], FieldType]] = {
    "timestamp-millis": (frozenset({"long"}), FieldType.TIMESTAMP),
    "timestamp-micros": (frozenset({"long"}), FieldType.TIMESTAMP),
    "timestamp-nanos": (frozenset({"long"}), FieldType.TIMESTAMP),
    "local-timestamp-millis": (frozenset({"long"}), FieldType.TIMESTAMP),
    "local-timestamp-micros": (frozenset({"long"}), FieldType.TIMESTAMP),
    "local-timestamp-nanos": (frozenset({"long"}), FieldType.TIMESTAMP),
    "date": (frozenset({"int"}), FieldType.DATE),
    "time-millis": (frozenset({"int"}), FieldType.STRING),
    "time-micros": (frozenset({"long"}), FieldType.STRING),
    "uuid": (frozenset({"string", "fixed"}), FieldType.STRING),
    "duration": (frozenset({"fixed"}), FieldType.STRING),
    "decimal": (frozenset({"bytes", "fixed"}), FieldType.FLOAT),
    "big-decimal": (frozenset({"bytes"}), FieldType.FLOAT),
}


def _invalid(pointer: str, message: str) -> ReadError:
    """The file is not a well-formed Avro schema."""
    return ReadError(ErrorCode.INVALID_AVRO_SCHEMA, pointer, message)


def _unsupported(pointer: str, message: str, *, degradable: bool = True) -> ReadError:
    """The file is fine, but the construct has no RippleRack equivalent."""
    return ReadError(ErrorCode.UNSUPPORTED_AVRO_SCHEMA, pointer, message, degradable=degradable)


@dataclass(frozen=True)
class _Named:
    """A record, an enum or a fixed type defined somewhere in the file."""

    kind: str
    fullname: str
    schema: dict[str, Any]
    namespace: str | None  # the namespace its own members are read in
    pointer: str

    @property
    def name(self) -> str:
        return self.fullname.rpartition(".")[2]


@dataclass(frozen=True)
class _Translated:
    """What the type of a field says about the field."""

    type: FieldType
    nullable: bool = False
    note: str = ""  # the symbols of an enum, to be added to the description


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
    reader = _Reader(document, lenient=lenient)
    return reader.read(source=source, name=name, version=version, select=select)


class _Reader(Reader):
    """Reads one document; collects every problem and warning before reporting."""

    def __init__(self, root: Any, *, lenient: bool) -> None:
        super().__init__(
            lenient=lenient,
            invalid=ErrorCode.INVALID_AVRO_SCHEMA,
            unsupported=ErrorCode.UNSUPPORTED_AVRO_SCHEMA,
            subject="Avro schema",
            unit="fields",
        )
        self._root = root
        self._named: dict[str, _Named] = {}  # by full name
        self._defined: dict[int, _Named] = {}  # by the identity of the object that defines it

    def read(
        self, *, source: str, name: str | None, version: str, select: str | None
    ) -> ImportResult:
        fields: list[SchemaField] = []
        record_name = ""
        try:
            self._register(self._root, None, "#", 0)
            record = self._select(select)
            record_name = record.name
            fields = self._fields(record)
        except ReadError as error:
            self._problems.append(error)
        if self._problems:
            self._fail(source)
        schema_name = name if name is not None else self._schema_name(record_name, source)
        try:
            schema = Schema(name=schema_name, version=version, fields=fields)
        except ValidationError as exc:
            raise RippleRackError(
                f"{source}: {summarize(exc)}", ErrorCode.VALIDATION_FAILED
            ) from exc
        return ImportResult(schema=schema, issues=tuple(self._issues))

    # -------------------------------------------------------------- the types of the file

    def _register(self, schema: Any, namespace: str | None, pointer: str, depth: int) -> None:
        """Note every record, enum and fixed type that a schema defines, wherever it is."""
        if depth > _MAX_DEPTH:
            raise _unsupported(pointer, "the schema is nested too deeply", degradable=False)
        if isinstance(schema, list):
            for index, branch in enumerate(schema):
                self._register(branch, namespace, child(pointer, index), depth + 1)
        elif isinstance(schema, dict):
            kind = schema.get("type")
            if kind in _NAMED_KINDS:
                namespace = self._define(kind, schema, namespace, pointer)
                if kind in _RECORDS:
                    for index, field in enumerate(schema["fields"]):
                        if isinstance(field, dict) and "type" in field:
                            where = child(pointer, "fields", index, "type")
                            self._register(field["type"], namespace, where, depth + 1)
            elif kind == "array":
                self._register(schema.get("items"), namespace, child(pointer, "items"), depth + 1)
            elif kind == "map":
                self._register(schema.get("values"), namespace, child(pointer, "values"), depth + 1)

    def _define(
        self, kind: str, schema: dict[str, Any], namespace: str | None, pointer: str
    ) -> str | None:
        """Register a named type; returns the namespace its own members are read in."""
        name = schema.get("name")
        if not isinstance(name, str) or not name:
            raise _invalid(child(pointer, "name"), f"{_NEEDS_A_NAME[kind]} needs a name")
        if "." in name:  # a full name: a namespace given next to it is ignored
            fullname = name
            own: str | None = name.rpartition(".")[0] or None
        else:
            declared = schema.get("namespace", namespace)
            if declared is not None and not isinstance(declared, str):
                raise _invalid(child(pointer, "namespace"), "namespace must be a string")
            own = declared or None  # the empty namespace is no namespace
            fullname = f"{own}.{name}" if own else name
        if fullname in self._named:
            raise _invalid(child(pointer, "name"), f"{fullname!r} is defined more than once")
        if kind in _RECORDS and not isinstance(schema.get("fields"), list):
            raise _invalid(child(pointer, "fields"), "the fields of a record must be a list")
        if kind == "enum":
            symbols = schema.get("symbols")
            if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
                raise _invalid(
                    child(pointer, "symbols"), "the symbols of an enum must be a list of strings"
                )
        named = _Named(kind, fullname, schema, own, pointer)
        self._named[fullname] = named
        self._defined[id(schema)] = named
        return own

    def _find(self, name: str, namespace: str | None) -> _Named | None:
        """The type a name refers to: one without a dot is looked up in the namespace first."""
        if "." not in name and namespace:
            found = self._named.get(f"{namespace}.{name}")
            if found is not None:
                return found
        return self._named.get(name)

    # ----------------------------------------------------------------- the record to import

    def _select(self, select: str | None) -> _Named:
        records = {full: named for full, named in self._named.items() if named.kind in _RECORDS}
        if select is not None:
            return self._chosen(select, records)
        branches = self._root if isinstance(self._root, list) else [self._root]
        top = [
            named
            for branch in branches
            if (named := self._defined.get(id(branch))) is not None and named.kind in _RECORDS
        ]
        if len(top) == 1:
            return top[0]
        if top:
            raise _unsupported(
                "#",
                f"the file holds several records ({_listing(sorted(n.fullname for n in top))}); "
                "choose one with --select",
                degradable=False,
            )
        hint = (
            f"; the file defines the records {_listing(sorted(records))}: choose one with --select"
            if records
            else ""
        )
        raise _unsupported(
            "#",
            f"the root is {_kind_of(self._root)}, but only a record can be imported: its fields "
            f"become the fields of the schema{hint}",
            degradable=False,
        )

    def _chosen(self, select: str, records: dict[str, _Named]) -> _Named:
        if select in records:
            return records[select]
        matches = sorted(full for full, named in records.items() if named.name == select)
        if len(matches) == 1:
            return records[matches[0]]
        if matches:
            raise _unsupported(
                "#",
                f"several records are called {select!r} ({_listing(matches)}); give the full name",
                degradable=False,
            )
        known = f"; its records are {_listing(sorted(records))}" if records else ""
        raise _unsupported(
            "#", f"the file defines no record called {select!r}{known}", degradable=False
        )

    # --------------------------------------------------------------------- the fields

    def _fields(self, record: _Named) -> list[SchemaField]:
        fields: list[SchemaField] = []
        seen: set[str] = set()
        for index, declared in enumerate(record.schema["fields"]):
            pointer = child(record.pointer, "fields", index)
            try:
                fields.append(self._field(declared, record, pointer, seen))
            except ReadError as error:
                self._problems.append(error)
        if not fields and not self._problems:
            self._problems.append(
                _unsupported(
                    record.pointer, "the record declares no fields to import", degradable=False
                )
            )
        return fields

    def _field(self, declared: Any, record: _Named, pointer: str, seen: set[str]) -> SchemaField:
        if not isinstance(declared, dict):
            raise _invalid(pointer, f"a field must be an object, found {describe(declared)}")
        name = declared.get("name")
        if not isinstance(name, str):
            raise _invalid(child(pointer, "name"), "a field needs a name")
        if not is_identifier(name):
            raise _unsupported(
                child(pointer, "name"),
                f"field name {name!r} is not a valid field name "
                "(letters, digits, '_', '.' and '-' only)",
                degradable=False,
            )
        if name in seen:
            raise _invalid(child(pointer, "name"), f"field {name!r} is declared more than once")
        seen.add(name)
        if "type" not in declared:
            raise _invalid(pointer, f"field {name!r} has no type")
        description = _doc(declared, pointer)
        try:
            translated = self._type(declared["type"], record.namespace, child(pointer, "type"))
        except ReadError as error:
            if not (self._lenient and error.degradable):
                raise
            self._warn(
                IssueCode.DEGRADED_TO_JSON,
                error.pointer,
                f"{error.message}; field {name!r} imported as json",
            )
            translated = _Translated(FieldType.JSON, _admits_null(declared["type"]))
        return SchemaField(
            name=name,
            type=translated.type,
            nullable=translated.nullable,
            description=with_note(description, translated.note),
        )

    # ------------------------------------------------------------------------ the types

    def _type(self, schema: Any, namespace: str | None, pointer: str) -> _Translated:
        """The type of a field, whether it admits null, and the values it lists."""
        if isinstance(schema, list):
            return self._union(schema, namespace, pointer)
        if _is_null(schema):
            raise _unsupported(pointer, "type 'null' on its own has no data type")
        if isinstance(schema, str):
            return self._by_name(schema, namespace, pointer)
        if isinstance(schema, dict):
            return self._object(schema, namespace, pointer)
        raise _invalid(
            pointer, f"a type must be a name, an object or a list, found {describe(schema)}"
        )

    def _union(self, branches: list[Any], namespace: str | None, pointer: str) -> _Translated:
        """A union of one type and ``null``, the way Avro writes an optional value."""
        for index, branch in enumerate(branches):
            if isinstance(branch, list):
                raise _invalid(child(pointer, index), "a union cannot contain another union")
        others = [(index, branch) for index, branch in enumerate(branches) if not _is_null(branch)]
        if not others:
            what = "type 'null' on its own" if branches else "an empty union"
            raise _unsupported(pointer, f"{what} has no data type")
        if len(others) > 1:
            shown = _listing([_label(branch) for _, branch in others])
            raise _unsupported(pointer, f"the union [{shown}] mixes several types in one field")
        index, branch = others[0]
        inner = self._type(branch, namespace, child(pointer, index))
        return _Translated(inner.type, len(others) < len(branches), inner.note)

    def _by_name(self, name: str, namespace: str | None, pointer: str) -> _Translated:
        if name in _PLAIN_TYPES:
            return _Translated(_PLAIN_TYPES[name])
        named = self._find(name, namespace)
        if named is None:
            raise _invalid(
                pointer,
                f"unknown type {name!r}: the file defines no record, enum or fixed with that name",
            )
        return self._object(named.schema, named.namespace, named.pointer)

    def _object(self, schema: dict[str, Any], namespace: str | None, pointer: str) -> _Translated:
        kind = schema.get("type")
        if not isinstance(kind, str):
            raise _invalid(child(pointer, "type"), "the type of a schema must be a name")
        if kind in _PLAIN_TYPES:
            return _Translated(_logical(kind, schema) or _PLAIN_TYPES[kind])
        if kind in _RECORDS:
            return _Translated(FieldType.JSON)
        if kind == "enum":
            return _Translated(FieldType.STRING, note=values_note(schema["symbols"], "One of"))
        if kind == "fixed":
            return _Translated(_logical(kind, schema) or FieldType.STRING)
        if kind == "array" and "items" not in schema:
            raise _invalid(pointer, "an array needs items")
        if kind == "map" and "values" not in schema:
            raise _invalid(pointer, "a map needs values")
        if kind in ("array", "map"):
            return _Translated(FieldType.JSON)
        return self._by_name(kind, namespace, pointer)  # {"type": "Name"} refers to a type too

    # ------------------------------------------------------------------------ the name

    def _schema_name(self, record_name: str, source: str) -> str:
        """The name of the record, else the file name, else ``schema``."""
        candidates = [record_name]
        if not source.startswith("<"):
            candidates.append(strip_suffixes(file_name(source)))
        return next((name for name in map(slug, candidates) if name), "schema")


# ---------------------------------------------------------------------- pure helpers


def _is_null(schema: Any) -> bool:
    return schema == "null" or (isinstance(schema, dict) and schema.get("type") == "null")


def _admits_null(schema: Any) -> bool:
    """Whether a type, written as a field gives it, can be null."""
    if isinstance(schema, list):
        return any(_is_null(branch) for branch in schema)
    return _is_null(schema)


def _logical(kind: str, schema: dict[str, Any]) -> FieldType | None:
    """The type a logical type makes of ``kind``, when it is a known one that fits."""
    logical = schema.get("logicalType")
    if not isinstance(logical, str) or logical not in _LOGICAL_TYPES:
        return None
    bases, field_type = _LOGICAL_TYPES[logical]
    if kind not in bases or (logical == "decimal" and not _valid_decimal(schema)):
        return None
    return field_type


def _valid_decimal(schema: dict[str, Any]) -> bool:
    """A decimal needs a positive ``precision`` and a ``scale`` from 0 up to the precision."""
    precision, scale = schema.get("precision"), schema.get("scale", 0)
    return (
        _is_integer(precision) and _is_integer(scale) and precision > 0 and 0 <= scale <= precision
    )


def _is_integer(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _doc(field: dict[str, Any], pointer: str) -> str:
    """``doc`` on one line."""
    value = field.get("doc")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid(child(pointer, "doc"), "doc must be a string")
    return one_line(value)


def _label(schema: Any) -> str:
    """A type as the file writes it, for a message."""
    if isinstance(schema, dict):
        kind, name = schema.get("type"), schema.get("name")
        if isinstance(kind, str) and isinstance(name, str):
            return f"{kind} {name}"
        schema = kind
    return schema if isinstance(schema, str) else describe(schema)


def _kind_of(schema: Any) -> str:
    """What a schema is, for a message about the root."""
    if isinstance(schema, list):
        return "a list of types that holds no record"
    if isinstance(schema, dict):
        schema = schema.get("type")
        if not isinstance(schema, str):
            return "an object without a type"
    return f"the type {schema!r}" if isinstance(schema, str) else describe(schema)


def _listing(items: list[str]) -> str:
    """The first few names, quoted, and how many more there are."""
    text = ", ".join(repr(item) for item in items[:_LISTED])
    return f"{text}, … ({len(items)} in all)" if len(items) > _LISTED else text
