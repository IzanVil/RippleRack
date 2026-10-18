"""What a property schema says about its field: the type, whether it allows null, the notes.

These functions read one property schema that has already been flattened (``$ref`` and
``allOf`` are gone) and know nothing about the rest of the document.
"""

from __future__ import annotations

from typing import Any

from ripplerack.importers.common import child, one_line, values_note
from ripplerack.importers.json_schema.problems import invalid, unsupported
from ripplerack.models import FieldType

_JSON_TYPES = frozenset({"string", "number", "integer", "boolean", "object", "array", "null"})
_PLAIN_TYPES = {
    "integer": FieldType.INTEGER,
    "number": FieldType.FLOAT,
    "boolean": FieldType.BOOLEAN,
}
_STRING_FORMATS = {"date-time": FieldType.TIMESTAMP, "date": FieldType.DATE}


def type_of(flat: dict[str, Any], pointer: str) -> tuple[FieldType, bool, str]:
    """The field type of a flat schema, whether it allows null, and the note on its values."""
    listed = listed_values(flat, pointer)
    if "type" in flat:
        names = type_names(flat["type"], pointer)
        kinds = set(names) - {"null"}
        if {"integer", "number"} <= kinds:
            kinds.discard("integer")  # every integer is a number
        if not kinds:
            raise unsupported(child(pointer, "type"), "type 'null' on its own has no data type")
        if len(kinds) > 1:
            raise unsupported(
                child(pointer, "type"), f"type {sorted(kinds)} mixes several types in one field"
            )
        (kind,) = kinds
        field_type = (
            string_type(flat, pointer)
            if kind == "string"
            else _PLAIN_TYPES.get(kind, FieldType.JSON)
        )
        nullable = "null" in names
    elif listed:
        field_type, nullable = infer(listed[0], flat, pointer)
    else:
        field_type, nullable = FieldType.JSON, False
    return field_type, nullable, values_note(*listed) if listed else ""


def listed_values(flat: dict[str, Any], pointer: str) -> tuple[list[Any], str] | tuple[()]:
    """The values ``enum`` or ``const`` allows, with the words that introduce them."""
    if "enum" in flat:
        values = flat["enum"]
        if not isinstance(values, list):
            raise invalid(child(pointer, "enum"), "enum must be a list")
        return (values, "One of") if values else ()
    if "const" in flat:
        return ([flat["const"]], "Always")
    return ()


def infer(values: list[Any], flat: dict[str, Any], pointer: str) -> tuple[FieldType, bool]:
    """The type of a field that lists its values but says no ``type``."""
    kinds = {value_kind(value) for value in values}
    nullable = "null" in kinds
    kinds.discard("null")
    if {"integer", "number"} <= kinds:
        kinds.discard("integer")
    if not kinds:
        raise unsupported(pointer, "a field whose only value is null has no data type")
    if len(kinds) > 1:
        return FieldType.JSON, nullable
    (kind,) = kinds
    if kind == "string":
        return string_type(flat, pointer), nullable
    return _PLAIN_TYPES.get(kind, FieldType.JSON), nullable


def string_type(flat: dict[str, Any], pointer: str) -> FieldType:
    """``timestamp`` or ``date`` for the strings with those formats, else ``string``."""
    fmt = flat.get("format")
    if fmt is not None and not isinstance(fmt, str):
        raise invalid(child(pointer, "format"), "format must be a string")
    return _STRING_FORMATS.get(fmt or "", FieldType.STRING)


def type_names(value: Any, pointer: str) -> list[str]:
    """The names in ``type``, one or a list, checked to be JSON Schema types."""
    where = child(pointer, "type")
    if isinstance(value, str):
        names = [value]
    elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        names = list(value)
    else:
        raise invalid(where, "type must be a string or a non-empty list of strings")
    for name in names:
        if name not in _JSON_TYPES:
            raise invalid(where, f"{name!r} is not a JSON Schema type")
    return names


def is_null_schema(schema: Any) -> bool:
    """Whether a schema accepts only null: ``type: null`` or ``const: null``."""
    if not isinstance(schema, dict):
        return False
    return schema.get("type") == "null" or (
        "type" not in schema and "const" in schema and schema["const"] is None
    )


def description_of(flat: dict[str, Any], pointer: str) -> str:
    """``description`` on one line.

    A ``title`` on a property is not used in its place: it mostly repeats the name of the field.
    """
    value = flat.get("description")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise invalid(child(pointer, "description"), "description must be a string")
    return one_line(value)


def own_description(schema: Any) -> str:
    """The same, for a schema that could not be read: keep the text if there is any."""
    value = schema.get("description") if isinstance(schema, dict) else None
    return one_line(value) if isinstance(value, str) else ""


def boolean_flag(flat: dict[str, Any], key: str, pointer: str) -> bool:
    """The value of a keyword that must be true or false; false when it is absent."""
    value = flat.get(key, False)
    if not isinstance(value, bool):
        raise invalid(child(pointer, key), f"{key} must be true or false")
    return value


def value_kind(value: Any) -> str:
    """The JSON Schema type of a value, or ``json`` for an array or an object."""
    if value is None:
        return "null"
    if isinstance(value, bool):  # before int: True is an int in Python
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "json"
