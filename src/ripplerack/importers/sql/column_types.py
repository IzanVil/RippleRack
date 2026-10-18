"""What each SQL data type makes of a column: a RippleRack type, and a note for the description.

The tables below are the heart of the importer. A type is in one of three places: the plain
table, when the type alone decides; the special cases, when its parameters, its dialect or the
file decide (``DECIMAL(12, 2)`` is a float and ``DECIMAL(12)`` an integer); or neither, when no
RippleRack type stands for it (a geometry, a range, a vector). ``REFUSED`` lists those on purpose:
a test fails when the parser learns a type that is in none of the three, so that someone decides.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from sqlglot import exp

from ripplerack.importers.common import values_note
from ripplerack.models import FieldType

T = exp.DType

_PLAIN_GROUPS: dict[FieldType, tuple[T, ...]] = {
    FieldType.INTEGER: (
        *(T.SMALLINT, T.MEDIUMINT, T.INT, T.BIGINT, T.INT128, T.INT256, T.BIGNUM, T.YEAR),
        *(T.UTINYINT, T.USMALLINT, T.UMEDIUMINT, T.UINT, T.UBIGINT, T.UINT128, T.UINT256),
        *(T.SERIAL, T.SMALLSERIAL, T.BIGSERIAL),
    ),
    FieldType.FLOAT: (
        *(T.FLOAT, T.DOUBLE, T.UDOUBLE, T.BIGDECIMAL, T.DECFLOAT, T.MONEY, T.SMALLMONEY),
        *(T.DECIMAL32, T.DECIMAL64, T.DECIMAL128, T.DECIMAL256),
    ),
    FieldType.BOOLEAN: (T.BOOLEAN,),
    FieldType.STRING: (
        *(T.CHAR, T.NCHAR, T.VARCHAR, T.NVARCHAR, T.BPCHAR, T.NAME, T.FIXEDSTRING, T.UUID, T.XML),
        *(T.TEXT, T.TINYTEXT, T.MEDIUMTEXT, T.LONGTEXT),
        *(T.BINARY, T.VARBINARY, T.IMAGE, T.ROWVERSION),
        *(T.BLOB, T.TINYBLOB, T.MEDIUMBLOB, T.LONGBLOB),
        *(T.TIME, T.TIMETZ, T.TIME_NS, T.INTERVAL),
        *(T.INET, T.IPADDRESS, T.IPPREFIX, T.IPV4, T.IPV6),
        *(T.ENUM8, T.ENUM16, T.SET),
    ),
    FieldType.DATE: (T.DATE, T.DATE32),
    FieldType.TIMESTAMP: (
        *(T.TIMESTAMP, T.TIMESTAMPTZ, T.TIMESTAMPLTZ, T.TIMESTAMPNTZ),
        *(T.TIMESTAMP_S, T.TIMESTAMP_MS, T.TIMESTAMP_NS),
        *(T.DATETIME, T.DATETIME2, T.DATETIME64, T.SMALLDATETIME),
    ),
    FieldType.JSON: (
        *(T.JSON, T.JSONB, T.VARIANT, T.OBJECT, T.SUPER),
        *(T.STRUCT, T.NESTED, T.MAP, T.UNION, T.LIST, T.ARRAY),
    ),
}
PLAIN_TYPES: dict[T, FieldType] = {
    sql_type: field_type for field_type, group in _PLAIN_GROUPS.items() for sql_type in group
}

# Types with no equivalent: a column of one is an error, or a ``json`` field with ``--lenient``.
REFUSED: frozenset[T] = frozenset(
    {
        *(T.GEOMETRY, T.GEOGRAPHY, T.GEOGRAPHYPOINT, T.POINT, T.RING, T.LINESTRING),
        *(T.MULTILINESTRING, T.POLYGON, T.MULTIPOLYGON),
        *(T.RANGE, T.INT4RANGE, T.INT8RANGE, T.NUMRANGE, T.DATERANGE, T.TSRANGE, T.TSTZRANGE),
        *(T.INT4MULTIRANGE, T.INT8MULTIRANGE, T.NUMMULTIRANGE, T.DATEMULTIRANGE),
        *(T.TSMULTIRANGE, T.TSTZMULTIRANGE),
        *(T.HSTORE, T.VECTOR, T.HLLSKETCH, T.TDIGEST, T.DYNAMIC, T.FILE),
        *(T.AGGREGATEFUNCTION, T.SIMPLEAGGREGATEFUNCTION, T.CHARACTER_SET),
        *(T.NOTHING, T.NULL, T.UNKNOWN),
    }
)

# Postgres types that the parser does not know and that are text for all that a schema cares.
_TEXT_TYPES = {"citext": FieldType.STRING, "cidr": FieldType.STRING}
_TEXT_TYPES |= {"macaddr": FieldType.STRING, "macaddr8": FieldType.STRING}

_NUMBER = re.compile(r"\d+")

EnumValues = Callable[[tuple[str, ...]], list[str] | None]


class NoEquivalentError(Exception):
    """A type that no RippleRack type stands for."""


@dataclass(frozen=True)
class ColumnType:
    """What the type of a column says about the field."""

    type: FieldType
    note: str = ""  # the values of an enum, to be added to the description


def column_type(kind: exp.DataType, dialect: str | None, enums: EnumValues) -> ColumnType:
    """The type of a column of this SQL type; ``enums`` finds the values of an enum by name."""
    plain = PLAIN_TYPES.get(kind.this)
    if plain is not None:
        return ColumnType(plain)
    handler = _SPECIAL_CASES.get(kind.this)
    if handler is None:
        raise NoEquivalentError(f"the type {kind.sql(dialect)} has no equivalent")
    return handler(kind, dialect, enums)


def _numbers(kind: exp.DataType) -> list[int | None]:
    """The parameters of a type, such as ``(12, 2)``, as numbers; ``None`` for what is not one."""
    numbers: list[int | None] = []
    for param in kind.expressions:
        literal = param.this if isinstance(param, exp.DataTypeParam) else param
        is_number = isinstance(literal, exp.Literal) and _NUMBER.fullmatch(literal.name)
        numbers.append(int(literal.name) if is_number else None)
    return numbers


def _decimal(kind: exp.DataType, dialect: str | None, enums: EnumValues) -> ColumnType:
    """An integer when the scale is 0, whether it is written or not; else a float."""
    numbers = _numbers(kind)
    whole = bool(numbers) and None not in numbers and (len(numbers) == 1 or numbers[1] == 0)
    return ColumnType(FieldType.INTEGER if whole else FieldType.FLOAT)


def _bit(kind: exp.DataType, dialect: str | None, enums: EnumValues) -> ColumnType:
    """A single bit is a flag; a string of several is text."""
    flag = _numbers(kind) in ([], [1])
    return ColumnType(FieldType.BOOLEAN if flag else FieldType.STRING)


def _tinyint(kind: exp.DataType, dialect: str | None, enums: EnumValues) -> ColumnType:
    """``TINYINT(1)`` is how MySQL writes a boolean; anywhere else it is a small integer."""
    flag = dialect == "mysql" and _numbers(kind) == [1]
    return ColumnType(FieldType.BOOLEAN if flag else FieldType.INTEGER)


def _enum(kind: exp.DataType, dialect: str | None, enums: EnumValues) -> ColumnType:
    """An enum written in the column: text, with its values in the description."""
    values = [value.name for value in kind.expressions]
    return ColumnType(FieldType.STRING, values_note(values, "One of"))


def _user_defined(kind: exp.DataType, dialect: str | None, enums: EnumValues) -> ColumnType:
    """A type the file names: an enum it defines, or a Postgres type that is text."""
    name = _type_name(kind.args.get("kind"))
    values = enums(name)
    if values is not None:
        return ColumnType(FieldType.STRING, values_note(values, "One of"))
    text_type = _TEXT_TYPES.get(name[-1].lower()) if name else None
    if text_type is None:
        raise NoEquivalentError(
            f"the type {kind.sql(dialect)} has no equivalent, and no enum of that name is defined"
        )
    return ColumnType(text_type)


def _low_cardinality(kind: exp.DataType, dialect: str | None, enums: EnumValues) -> ColumnType:
    """``LowCardinality(String)`` of ClickHouse is the type it wraps."""
    inner = kind.expressions[0] if kind.expressions else None
    if not isinstance(inner, exp.DataType):
        raise NoEquivalentError(f"the type {kind.sql(dialect)} has no equivalent")
    return column_type(inner, dialect, enums)


def _type_name(node: exp.Expr | str | None) -> tuple[str, ...]:
    """The dotted name a user-defined type is written with; some dialects give it as plain text."""
    if isinstance(node, exp.Dot):
        return tuple(part.name for part in node.flatten())
    if isinstance(node, exp.Expr):
        return (node.name,)
    return (node,) if node else ()


SPECIAL_TYPES = (
    T.DECIMAL,
    T.UDECIMAL,
    T.BIT,
    T.TINYINT,
    T.ENUM,
    T.USERDEFINED,
    T.LOWCARDINALITY,
)
_SPECIAL_CASES: dict[T, Callable[[exp.DataType, str | None, EnumValues], ColumnType]] = {
    T.DECIMAL: _decimal,
    T.UDECIMAL: _decimal,
    T.BIT: _bit,
    T.TINYINT: _tinyint,
    T.ENUM: _enum,
    T.USERDEFINED: _user_defined,
    T.LOWCARDINALITY: _low_cardinality,
}
