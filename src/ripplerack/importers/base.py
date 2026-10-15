"""Types shared by every importer: what is read, what comes back, what is worth a warning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from ripplerack.models import SEMVER_PATTERN, Identifier, Schema

_IDENTIFIER = TypeAdapter(Identifier)


class SourceFormat(StrEnum):
    """Formats ``ripplerack import`` can read (``--from``)."""

    JSON_SCHEMA = "json-schema"


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
    """Reads the text of a file in some format and returns the schema it describes."""

    def __call__(
        self, text: str, *, source: str, name: str | None, version: str, lenient: bool
    ) -> ImportResult: ...


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
