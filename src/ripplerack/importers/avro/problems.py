"""The two kinds of problem an Avro schema can have, and how a message lists names."""

from __future__ import annotations

from ripplerack.importers.common import ReadError
from ripplerack.parser import ErrorCode

_LISTED = 10  # how many names a message lists before it counts the rest


def invalid(pointer: str, message: str) -> ReadError:
    """The file is not a well-formed Avro schema."""
    return ReadError(ErrorCode.INVALID_AVRO_SCHEMA, pointer, message)


def unsupported(pointer: str, message: str, *, degradable: bool = True) -> ReadError:
    """The file is fine, but the construct has no RippleRack equivalent."""
    return ReadError(ErrorCode.UNSUPPORTED_AVRO_SCHEMA, pointer, message, degradable=degradable)


def listing(items: list[str]) -> str:
    """The first few names, quoted, and how many more there are."""
    text = ", ".join(repr(item) for item in items[:_LISTED])
    return f"{text}, … ({len(items)} in all)" if len(items) > _LISTED else text
