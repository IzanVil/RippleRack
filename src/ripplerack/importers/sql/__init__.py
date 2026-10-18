"""Read the ``CREATE TABLE`` of a SQL file and translate one table into a RippleRack schema.

The columns of the table become the fields of the schema. A column is ``nullable`` unless it is
declared ``NOT NULL``, is part of the primary key or is a counter (``SERIAL``, ``IDENTITY``,
``AUTO_INCREMENT``), and its comment is its description. The type comes from a table of the SQL
types; an enum keeps its values in the description. What the file says about a table in other
statements (``COMMENT ON COLUMN``, ``ALTER TABLE ... ADD PRIMARY KEY``) is gathered first.

As with the other formats, what decides the type but has no equivalent is an error, so nothing is
lost without anyone noticing: a geometry, a range. With ``lenient`` the column becomes a ``json``
one and a warning says so. ``docs/import-sql.md`` lists every rule.

The package has four parts: ``parse`` reads the text with sqlglot, ``catalog`` knows what the file
defines and which table to import, ``column_types`` says what each SQL type makes of a column and
``reader`` translates the columns of that table. sqlglot takes half a second to load, which only
a SQL file should pay for, so it is imported when a file is read and not before.
"""

from __future__ import annotations

from ripplerack.importers.base import ImportResult

__all__ = ["import_sql", "sql_dialects"]


def import_sql(
    text: str,
    *,
    source: str,
    name: str | None = None,
    version: str = "1.0.0",
    lenient: bool = False,
    select: str | None = None,
    dialect: str | None = None,
) -> ImportResult:
    """Read the SQL in ``text`` and translate one table of it; ``source`` names it in messages.

    The table is the only one the file creates, or the one ``select`` names: its name, or the
    schema and the name. ``dialect`` is the flavour of SQL the file is written in, such as
    ``postgres`` or ``mysql``; without it the standard syntax is assumed. ``name`` defaults to the
    name of the table, then the file name in ``source``. Raises :class:`RippleRackError` when the
    file cannot be imported and :class:`ValueError` for a dialect that does not exist.
    """
    from ripplerack.importers.sql.reader import SqlReader

    reader = SqlReader(text, dialect=dialect.lower() if dialect else None, lenient=lenient)
    return reader.read(source=source, name=name, version=version, select=select)


def sql_dialects() -> list[str]:
    """The names of the dialects that ``dialect`` accepts."""
    from ripplerack.importers.sql.parse import dialect_names

    return dialect_names()
