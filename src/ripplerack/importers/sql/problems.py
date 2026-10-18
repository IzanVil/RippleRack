"""The two kinds of problem a SQL file can have, and how a message says where it is."""

from __future__ import annotations

from ripplerack.importers.common import ReadError
from ripplerack.parser import ErrorCode


def invalid(pointer: str, message: str) -> ReadError:
    """The file is not SQL that the dialect it is read with understands."""
    return ReadError(ErrorCode.INVALID_SQL, pointer, message)


def unsupported(pointer: str, message: str, *, degradable: bool = True) -> ReadError:
    """The file is fine, but the construct has no RippleRack equivalent."""
    return ReadError(ErrorCode.UNSUPPORTED_SQL, pointer, message, degradable=degradable)


def place(name: str = "", line: int | None = None) -> str:
    """Where a message is about: ``orders.status (line 57)``, ``line 57`` or nothing."""
    if not name:
        return f"line {line}" if line is not None else ""
    return f"{name} (line {line})" if line is not None else name
