"""The two kinds of problem a JSON Schema can have, with the code each one is given."""

from __future__ import annotations

from ripplerack.importers.common import ReadError
from ripplerack.parser import ErrorCode


def invalid(pointer: str, message: str) -> ReadError:
    """The file is not a well-formed JSON Schema."""
    return ReadError(ErrorCode.INVALID_JSON_SCHEMA, pointer, message)


def unsupported(pointer: str, message: str, *, degradable: bool = True) -> ReadError:
    """The file is fine, but the construct has no RippleRack equivalent."""
    return ReadError(ErrorCode.UNSUPPORTED_JSON_SCHEMA, pointer, message, degradable=degradable)
