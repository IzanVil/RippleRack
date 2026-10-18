"""The logical types of Avro: what each one makes of the type it sits on."""

from __future__ import annotations

from typing import Any, TypeGuard

from ripplerack.models import FieldType

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


def logical_type(kind: str, schema: dict[str, Any]) -> FieldType | None:
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
