"""Types shared by every importer: what is read, what comes back, what is worth a warning."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from ripplerack.models import SEMVER_PATTERN, Identifier, Schema
from ripplerack.parser import ErrorCode, RippleRackError

_IDENTIFIER = TypeAdapter(Identifier)
STDIN = Path("-")


class SourceFormat(StrEnum):
    """Formats ``ripplerack import`` can read (``--from``)."""

    JSON_SCHEMA = "json-schema"
    AVRO = "avro"
    SQL = "sql"


class IssueCode(StrEnum):
    """Stable identifiers of the warnings an import can produce (see ``docs/import.md``)."""

    DEGRADED_TO_JSON = "degraded_to_json"
    UNDECLARED_REQUIRED = "undeclared_required"
    ADDITIONAL_PROPERTIES_IGNORED = "additional_properties_ignored"


@dataclass(frozen=True)
class ImportIssue:
    """A warning: something was imported, but not exactly as the source says.

    ``pointer`` is a JSON pointer (``#/properties/amount``) to the place in the source
    document the warning is about.
    """

    code: IssueCode
    pointer: str
    message: str

    def __str__(self) -> str:
        return f"warning[{self.code}] {self.pointer}: {self.message}"


@dataclass(frozen=True)
class ImportResult:
    """The schema read from a source, plus the warnings found on the way."""

    schema: Schema
    issues: tuple[ImportIssue, ...] = ()


class Importer(Protocol):
    """Reads the text of a file in some format and returns the schema it describes.

    ``select`` names which of the schemas a file defines to read, for the formats that can hold
    several, and ``dialect`` says which flavour of SQL a file is written in; the formats that
    have no use for either refuse it.
    """

    def __call__(
        self,
        text: str,
        *,
        source: str,
        name: str | None,
        version: str,
        lenient: bool,
        select: str | None,
        dialect: str | None,
    ) -> ImportResult: ...


def source_label(path: Path) -> str:
    """How a source is named in messages: its path, or ``<stdin>``."""
    return "<stdin>" if path == STDIN else str(path)


def read_text(path: Path) -> str:
    """Read a source file as UTF-8 (a byte order mark is accepted); ``-`` is standard input."""
    try:
        if path == STDIN:
            return sys.stdin.buffer.read().decode("utf-8-sig")
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise RippleRackError(f"file not found: {path}", ErrorCode.FILE_NOT_FOUND) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise RippleRackError(
            f"cannot read {source_label(path)}: {exc}", ErrorCode.IO_ERROR
        ) from exc


def is_identifier(text: str) -> bool:
    """Whether ``text`` is usable as is as a schema or field name.

    The model strips surrounding whitespace, so a name that only validates after stripping
    would be renamed without anyone noticing; comparing with the original rules that out.
    """
    try:
        return _IDENTIFIER.validate_python(text) == text
    except ValidationError:
        return False


def is_version(text: str) -> bool:
    """Whether ``text`` is a ``MAJOR.MINOR.PATCH`` version."""
    return re.fullmatch(SEMVER_PATTERN, text) is not None
