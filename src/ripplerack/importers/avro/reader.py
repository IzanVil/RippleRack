"""Translate the fields of one record of an Avro schema into the fields of a RippleRack schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ripplerack.importers.avro.logical import logical_type
from ripplerack.importers.avro.names import CALLED, HOLDS, RECORDS, Named, Types
from ripplerack.importers.avro.problems import invalid, listing, unsupported
from ripplerack.importers.base import ImportResult, IssueCode, is_identifier
from ripplerack.importers.common import (
    Reader,
    ReadError,
    child,
    describe,
    name_schema,
    one_line,
    values_note,
    with_note,
)
from ripplerack.models import FieldType, SchemaField
from ripplerack.parser import ErrorCode

_PLAIN_TYPES = {
    "boolean": FieldType.BOOLEAN,
    "int": FieldType.INTEGER,
    "long": FieldType.INTEGER,
    "float": FieldType.FLOAT,
    "double": FieldType.FLOAT,
    "bytes": FieldType.STRING,
    "string": FieldType.STRING,
}


@dataclass(frozen=True)
class _Translated:
    """What the type of a field says about the field."""

    type: FieldType
    nullable: bool = False
    note: str = ""  # the symbols of an enum, to be added to the description


class AvroReader(Reader):
    """Translates the fields of one record; collects every problem and warning before reporting."""

    def __init__(self, root: Any, *, lenient: bool) -> None:
        super().__init__(
            lenient=lenient,
            invalid=ErrorCode.INVALID_AVRO_SCHEMA,
            unsupported=ErrorCode.UNSUPPORTED_AVRO_SCHEMA,
            subject="Avro schema",
            unit="fields",
        )
        self._types = Types(root)

    def read(
        self, *, source: str, name: str | None, version: str, select: str | None
    ) -> ImportResult:
        """The schema of the record chosen, or the error listing all that is wrong."""
        fields: list[SchemaField] = []
        record_name = ""
        try:
            self._types.register()
            record = self._types.choose(select)
            record_name = record.name
            fields = self._fields(record)
        except ReadError as error:
            self._problems.append(error)
        schema_name = name if name is not None else name_schema([record_name], source)
        return self._finish(source=source, name=schema_name, version=version, fields=fields)

    def _fields(self, record: Named) -> list[SchemaField]:
        """The fields of a record; a problem is noted and the next field is read."""
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
                unsupported(
                    record.pointer, "the record declares no fields to import", degradable=False
                )
            )
        return fields

    def _field(self, declared: Any, record: Named, pointer: str, seen: set[str]) -> SchemaField:
        """One field of the record: its name, the type it gives and its ``doc``."""
        name = _field_name(declared, pointer, seen)
        if "type" not in declared:
            raise invalid(pointer, f"field {name!r} has no type")
        description = _doc(declared, pointer)
        translated = self._translated(name, declared["type"], record.namespace, pointer)
        return SchemaField(
            name=name,
            type=translated.type,
            nullable=translated.nullable,
            description=with_note(description, translated.note),
        )

    def _translated(
        self, name: str, schema: Any, namespace: str | None, pointer: str
    ) -> _Translated:
        """The type of the field ``name``.

        With ``lenient``, a type that has no equivalent gives a ``json`` field and a warning.
        """
        try:
            return self._type(schema, namespace, child(pointer, "type"))
        except ReadError as error:
            if not (self._lenient and error.degradable):
                raise
            self._warn(
                IssueCode.DEGRADED_TO_JSON,
                error.pointer,
                f"{error.message}; field {name!r} imported as json",
            )
            return _Translated(FieldType.JSON, _admits_null(schema))

    def _type(self, schema: Any, namespace: str | None, pointer: str) -> _Translated:
        """The type of a field, whether it admits null, and the values it lists."""
        if isinstance(schema, list):
            return self._union(schema, namespace, pointer)
        if _is_null(schema):
            raise unsupported(pointer, "type 'null' on its own has no data type")
        if isinstance(schema, str):
            return self._by_name(schema, namespace, pointer)
        if isinstance(schema, dict):
            return self._object(schema, namespace, pointer)
        raise invalid(
            pointer, f"a type must be a name, an object or a list, found {describe(schema)}"
        )

    def _union(self, branches: list[Any], namespace: str | None, pointer: str) -> _Translated:
        """A union of one type and ``null``, the way Avro writes an optional value."""
        _refuse_nested_unions(branches, pointer)
        others = [(index, branch) for index, branch in enumerate(branches) if not _is_null(branch)]
        if not others:
            what = "type 'null' on its own" if branches else "an empty union"
            raise unsupported(pointer, f"{what} has no data type")
        if len(others) > 1:
            shown = listing([_label(branch) for _, branch in others])
            raise unsupported(pointer, f"the union [{shown}] mixes several types in one field")
        index, branch = others[0]
        inner = self._type(branch, namespace, child(pointer, index))
        return _Translated(inner.type, len(others) < len(branches), inner.note)

    def _by_name(self, name: str, namespace: str | None, pointer: str) -> _Translated:
        """A type written as a name: a primitive, or a type that the file defines."""
        if name in _PLAIN_TYPES:
            return _Translated(_PLAIN_TYPES[name])
        named = self._types.find(name, namespace)
        if named is None:
            raise invalid(
                pointer,
                f"unknown type {name!r}: the file defines no record, enum or fixed with that name",
            )
        return self._object(named.schema, named.namespace, named.pointer)

    def _object(self, schema: dict[str, Any], namespace: str | None, pointer: str) -> _Translated:
        """A type written as an object: a logical type, an enum, a record or a container."""
        kind = schema.get("type")
        if not isinstance(kind, str):
            raise invalid(child(pointer, "type"), "the type of a schema must be a name")
        if kind in _PLAIN_TYPES:
            return _Translated(logical_type(kind, schema) or _PLAIN_TYPES[kind])
        if kind == "fixed":
            return _Translated(logical_type(kind, schema) or FieldType.STRING)
        if kind == "enum":
            return _Translated(FieldType.STRING, note=values_note(schema["symbols"], "One of"))
        if kind in RECORDS or kind in HOLDS:
            _check_holds(kind, schema, pointer)
            return _Translated(FieldType.JSON)
        return self._by_name(kind, namespace, pointer)  # {"type": "Name"} refers to a type too


def _refuse_nested_unions(branches: list[Any], pointer: str) -> None:
    """Refuse a union that holds another union, which Avro does not allow."""
    for index, branch in enumerate(branches):
        if isinstance(branch, list):
            raise invalid(child(pointer, index), "a union cannot contain another union")


def _check_holds(kind: str, schema: dict[str, Any], pointer: str) -> None:
    """An array needs its ``items`` and a map its ``values``; a record holds nothing here."""
    if kind in HOLDS and HOLDS[kind] not in schema:
        raise invalid(pointer, f"{CALLED[kind]} needs {HOLDS[kind]}")


def _field_name(declared: Any, pointer: str, seen: set[str]) -> str:
    """The name of a field, which must be there, usable, and not used by another field."""
    if not isinstance(declared, dict):
        raise invalid(pointer, f"a field must be an object, found {describe(declared)}")
    name = declared.get("name")
    if not isinstance(name, str):
        raise invalid(child(pointer, "name"), "a field needs a name")
    if not is_identifier(name):
        raise unsupported(
            child(pointer, "name"),
            f"field name {name!r} is not a valid field name "
            "(letters, digits, '_', '.' and '-' only)",
            degradable=False,
        )
    if name in seen:
        raise invalid(child(pointer, "name"), f"field {name!r} is declared more than once")
    seen.add(name)
    return name


def _is_null(schema: Any) -> bool:
    """Whether a type is ``null``, written as a name or as an object."""
    return schema == "null" or (isinstance(schema, dict) and schema.get("type") == "null")


def _admits_null(schema: Any) -> bool:
    """Whether a type, written as a field gives it, can be null."""
    if isinstance(schema, list):
        return any(_is_null(branch) for branch in schema)
    return _is_null(schema)


def _doc(field: dict[str, Any], pointer: str) -> str:
    """``doc`` on one line."""
    value = field.get("doc")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise invalid(child(pointer, "doc"), "doc must be a string")
    return one_line(value)


def _label(schema: Any) -> str:
    """A type as the file writes it, for a message."""
    if isinstance(schema, dict):
        kind, name = schema.get("type"), schema.get("name")
        if isinstance(kind, str) and isinstance(name, str):
            return f"{kind} {name}"
        schema = kind
    return schema if isinstance(schema, str) else describe(schema)
