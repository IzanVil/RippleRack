"""Parse the text of a SQL file into statements, with the parser of sqlglot."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import sqlglot
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import ParseError, SqlglotError

from ripplerack.importers.common import ReadError
from ripplerack.importers.sql.problems import invalid

_NO_DIALECT_HINT = "; if the file is not standard SQL, give --dialect"


@contextmanager
def quiet() -> Iterator[None]:
    """Keep sqlglot from warning, through logging, of what it could not do with a statement."""
    logger = logging.getLogger("sqlglot")
    level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(level)


def dialect_names() -> list[str]:
    """The dialects that can be read, by name; the generic one has none."""
    return sorted(name for name in Dialect.classes if name)


def parse_statements(text: str, dialect: str | None) -> list[exp.Expr]:
    """The statements of ``text``; what the parser cannot read is an ``invalid`` problem."""
    if dialect is not None and dialect not in dialect_names():
        raise ValueError(f"unknown SQL dialect {dialect!r}")
    try:
        parsed = sqlglot.parse(text, dialect=dialect)
    except ParseError as error:
        raise _unreadable(error, dialect) from error
    except SqlglotError as error:
        raise invalid("", _first_line(error) + ("" if dialect else _NO_DIALECT_HINT)) from error
    except RecursionError as error:
        raise invalid("", "the SQL is nested too deeply") from error
    return [statement for statement in parsed if statement is not None]


def _unreadable(error: ParseError, dialect: str | None) -> ReadError:
    """The problem a syntax error is: what it expected, and where."""
    details = error.errors[0] if error.errors else {}
    line, column = details.get("line"), details.get("col")
    where = f"line {line}, column {column}" if line is not None and column is not None else ""
    what = details.get("description") or _first_line(error)
    return invalid(where, what + ("" if dialect else _NO_DIALECT_HINT))


def _first_line(error: Exception) -> str:
    """The first line of what a parser says, which is all that fits in a message."""
    lines = str(error).splitlines()
    return lines[0] if lines else "the text cannot be read as SQL"
