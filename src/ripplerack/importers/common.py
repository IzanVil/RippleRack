"""What every importer shares: reading JSON safely, naming a schema, pointing at the place a
message is about, the notes an enum leaves in a description, and the report of what went wrong.

The readers of the different formats differ in what they understand, not in how they report it,
so a problem, a warning and the final error look the same whatever the format of the file.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, NoReturn

from pydantic import ValidationError

from ripplerack.importers.base import ImportIssue, ImportResult, IssueCode
from ripplerack.models import Schema, SchemaField
from ripplerack.parser import ErrorCode, RippleRackError

MAX_ENUM_VALUES = 10
_LISTED = 10  # how many names a message lists before it counts the rest
_NAME_SUFFIXES = (".json", ".schema", ".avsc")


class ReadError(Exception):
    """A problem found while reading, with the place in the document it was found."""

    def __init__(
        self, code: ErrorCode, pointer: str, message: str, *, degradable: bool = False
    ) -> None:
        super().__init__(message)
        self.code = code
        self.pointer = pointer
        self.message = message
        # Whether ``lenient`` can turn the field into a json one instead of failing.
        self.degradable = degradable


class Reader:
    """What the readers of every format have in common: the problems and warnings they collect.

    A reader notes every problem it finds instead of stopping at the first, so one error lists
    them all, and every warning once. ``invalid`` is the code of a file that is not well formed
    and ``unsupported`` the code of one that is, but uses what has no RippleRack equivalent.
    """

    def __init__(
        self,
        *,
        lenient: bool,
        invalid: ErrorCode,
        unsupported: ErrorCode,
        subject: str,
        unit: str,
    ) -> None:
        self._lenient = lenient
        self._invalid_code = invalid
        self._unsupported_code = unsupported
        self._subject = subject  # what the file is, for the first line of the error
        self._unit = unit  # what a field is called in that format, for the hint
        self._problems: list[ReadError] = []
        self._issues: list[ImportIssue] = []
        self._noted: set[tuple[IssueCode, str]] = set()

    def _warn(self, code: IssueCode, pointer: str, message: str) -> None:
        if (code, pointer) not in self._noted:
            self._noted.add((code, pointer))
            self._issues.append(ImportIssue(code=code, pointer=pointer, message=message))

    def _finish(
        self, *, source: str, name: str, version: str, fields: list[SchemaField]
    ) -> ImportResult:
        """The result of reading: the schema if nothing went wrong, else the error with it all."""
        if self._problems:
            self._fail(source)
        try:
            schema = Schema(name=name, version=version, fields=fields)
        except ValidationError as exc:
            raise RippleRackError(
                f"{source}: {summarize(exc)}", ErrorCode.VALIDATION_FAILED
            ) from exc
        return ImportResult(schema=schema, issues=tuple(self._issues))

    def _fail(self, source: str) -> NoReturn:
        """Raise the error that lists every problem; its code says whether the file is malformed."""
        invalid = any(p.code is self._invalid_code for p in self._problems)
        lines = [
            f"{source}: cannot import this {self._subject}:",
            *(
                f"  {p.pointer}: {p.message}" if p.pointer else f"  {p.message}"
                for p in self._problems
            ),
        ]
        if not invalid and not self._lenient and any(p.degradable for p in self._problems):
            lines.append(f"  hint: --lenient imports {self._unit} like these as json fields")
        code = self._invalid_code if invalid else self._unsupported_code
        raise RippleRackError("\n".join(lines), code)


def listing(items: list[str]) -> str:
    """The first few names, quoted, and how many more there are."""
    text = ", ".join(repr(item) for item in items[:_LISTED])
    return f"{text}, … ({len(items)} in all)" if len(items) > _LISTED else text


def one_line(text: str) -> str:
    """``text`` with every run of whitespace turned into a single space."""
    return " ".join(text.split())


def parse_json(text: str, source: str) -> Any:
    """Parse ``text`` as JSON, rejecting what would be read ambiguously.

    Repeated keys in one object (the usual parser keeps the last and drops the rest) and the
    non-standard ``NaN`` and ``Infinity`` are errors.
    """
    try:
        return json.loads(text, object_pairs_hook=_no_repeated_keys, parse_constant=_no_constant)
    except RecursionError as exc:
        raise RippleRackError(
            f"{source}: invalid JSON: nested too deeply", ErrorCode.INVALID_JSON
        ) from exc
    except ValueError as exc:
        raise RippleRackError(f"{source}: invalid JSON: {exc}", ErrorCode.INVALID_JSON) from exc


def _no_repeated_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object from its pairs, refusing a key that appears twice."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"the key {key!r} appears more than once in the same object")
        result[key] = value
    return result


def _no_constant(constant: str) -> Any:
    raise ValueError(f"{constant} is not valid JSON")


def child(pointer: str, *tokens: str | int) -> str:
    """Extend a JSON pointer, escaping ``~`` and ``/`` inside the tokens."""
    escaped = (visible(str(token)).replace("~", "~0").replace("/", "~1") for token in tokens)
    return "/".join([pointer, *escaped])


def visible(text: str) -> str:
    """``text`` with its control characters written out.

    A pointer quotes names from the file, and a name can hold an escape sequence: printed as it
    is, it could move the cursor or change the colours of the terminal that shows the message.
    """
    return "".join(
        char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
        for char in text
    )


def describe(value: Any) -> str:
    """A value described for an error message."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, int | float):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "an array"
    return "an object"


def summarize(error: ValidationError) -> str:
    """The problems of a validation error, on one line."""
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    )


def slug(text: str) -> str:
    """Lowercase letters and digits joined by ``_``: a valid, readable schema name.

    The words of a CamelCase name are told apart: ``OrderEvent`` is ``order_event`` and
    ``HTTPRequest`` is ``http_request``.
    """
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", folded)
    words = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", words)
    return re.sub(r"[^a-z0-9]+", "_", words.lower()).strip("_")


def name_schema(candidates: list[str], source: str) -> str:
    """The name of a schema: the first candidate that makes a usable name, else the file's.

    ``source`` is the path of the file, or ``<stdin>``, which has no name to give. When nothing
    makes a usable name the schema is called ``schema``.
    """
    if not source.startswith("<"):
        candidates = [*candidates, strip_suffixes(file_name(source))]
    return next((name for name in map(slug, candidates) if name), "schema")


def strip_suffixes(name: str) -> str:
    """``name`` without the endings of a file name that are not part of the schema's name."""
    for suffix in _NAME_SUFFIXES:
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    return name


def file_name(path: str) -> str:
    """The last part of a path, whether it is written with ``/`` or with a backslash.

    The command gives the importer ``str(path)``, which on Windows uses backslashes; a POSIX
    path parser would take the whole of ``C:\\dir\\orders.json`` for the file name.
    """
    return re.split(r"[\\/]", path)[-1]


def _show(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return one_line(value)
    return json.dumps(value, ensure_ascii=False)


def values_note(values: list[Any], label: str) -> str:
    """``One of: a, b, c``: the values ``enum`` allows, as far as a description can hold them."""
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:  # null is carried by ``nullable``
            continue
        key = json.dumps(value, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(_show(value))
    if not unique:
        return ""
    text = ", ".join(unique[:MAX_ENUM_VALUES])
    if len(unique) > MAX_ENUM_VALUES:
        text += f", … ({len(unique)} values)"
    return f"{label}: {text}"


def with_note(description: str, note: str) -> str:
    """``description`` followed by ``note`` as another sentence."""
    if not note:
        return description
    if not description:
        return note
    separator = " " if description.endswith((".", "!", "?")) else ". "
    return f"{description}{separator}{note}"
