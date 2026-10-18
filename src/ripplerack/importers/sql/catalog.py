"""What a SQL file defines: its tables and enums, found by name, and the table to import.

A dump spreads one table over several statements: the ``CREATE TABLE`` has the columns, a
``COMMENT ON COLUMN`` their descriptions and an ``ALTER TABLE ... ADD PRIMARY KEY`` says which
cannot be null. The catalog reads all the statements once and gathers what belongs to each table,
whatever the order. A statement that would change the columns after they are created is refused,
for the table that is imported, instead of giving a schema that is out of date without a word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from sqlglot import exp

from ripplerack.importers.common import ReadError, listing
from ripplerack.importers.sql.problems import invalid, place, unsupported

V = TypeVar("V")
_CREATE_TABLE = re.compile(r"\s*(?:OR\s+REPLACE\s+)?(?:[A-Z]+\s+){0,2}TABLE\b", re.IGNORECASE)
_SHOWN = 80  # how much of a statement a message quotes


class Names(Generic[V]):
    """Things found by a dotted name: the whole name, or just the end of it, as SQL allows."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, ...], V] = {}

    def add(self, parts: tuple[str, ...], item: V) -> bool:
        """Remember ``item``; ``False`` if another one already has the name."""
        if parts in self._items:
            return False
        self._items[parts] = item
        return True

    def items(self) -> list[tuple[tuple[str, ...], V]]:
        return list(self._items.items())

    def matches(self, parts: tuple[str, ...]) -> list[V]:
        """What the name refers to: the one whose whole name it is, else all that end with it."""
        if not parts:
            return []
        if parts in self._items:
            return [self._items[parts]]
        return [item for full, item in self._items.items() if full[-len(parts) :] == parts]


@dataclass
class Table:
    """A table the file creates, with what the rest of the file says about it."""

    parts: tuple[str, ...]
    columns: list[exp.ColumnDef]
    line: int | None
    primary_key: set[str]
    comments: dict[str, str] = field(default_factory=dict)  # from COMMENT ON COLUMN
    refused: list[ReadError] = field(default_factory=list)  # ALTERs that change the columns

    @property
    def fullname(self) -> str:
        return ".".join(self.parts)

    @property
    def name(self) -> str:
        return self.parts[-1]


class Catalog:
    """The tables and the enums of a file, and which table is the one to import."""

    def __init__(self, statements: list[exp.Expr], dialect: str | None) -> None:
        self._dialect = dialect
        self._tables: Names[Table] = Names()
        self._enums: Names[list[str]] = Names()
        for statement in statements:
            self._define(statement)
        for statement in statements:
            self._amend(statement)

    def enum_values(self, parts: tuple[str, ...]) -> list[str] | None:
        """The values of the enum a type name refers to; none if it is not one that is defined."""
        found = self._enums.matches(parts)
        return found[0] if len(found) == 1 else None

    def choose(self, select: str | None) -> Table:
        """The table to import: the one ``select`` names, or else the only one the file creates."""
        tables = self._tables.items()
        if select is not None:
            return self._named(select, tables)
        if len(tables) == 1:
            return tables[0][1]
        if not tables:
            raise unsupported("", "the file creates no table to import", degradable=False)
        names = listing(sorted(".".join(parts) for parts, _ in tables))
        raise unsupported(
            "",
            f"the file creates several tables ({names}); choose one with --select",
            degradable=False,
        )

    def _named(self, select: str, tables: list[tuple[tuple[str, ...], Table]]) -> Table:
        found = self._tables.matches(tuple(select.split(".")))
        if len(found) == 1:
            return found[0]
        names = listing(sorted(".".join(parts) for parts, _ in tables))
        if found:
            ambiguous = listing(sorted(table.fullname for table in found))
            raise unsupported(
                "",
                f"several tables are called {select!r} ({ambiguous}); give the schema too",
                degradable=False,
            )
        known = f"; its tables are {names}" if tables else ""
        raise unsupported(
            "", f"the file creates no table called {select!r}{known}", degradable=False
        )

    def _define(self, statement: exp.Expr) -> None:
        """Note the table or the enum a statement creates."""
        if isinstance(statement, exp.Create):
            kind = statement.args.get("kind")
            if kind == "TABLE":
                self._add_table(statement)
            elif kind == "TYPE":
                self._add_enum(statement)
        elif isinstance(statement, exp.Command) and _creates_table(statement):
            raise invalid("", self._not_understood(statement))

    def _not_understood(self, statement: exp.Command) -> str:
        shown = " ".join(statement.sql().split())
        shown = shown if len(shown) <= _SHOWN else shown[:_SHOWN] + "…"
        which = f"the {self._dialect} dialect" if self._dialect else "the dialect that is assumed"
        hint = "" if self._dialect else "; if the file is not standard SQL, give --dialect"
        return f"{which} does not understand this statement: {shown}{hint}"

    def _add_table(self, create: exp.Create) -> None:
        table = _table_of(create)
        if not self._tables.add(table.parts, table):
            raise invalid(
                place(table.fullname, table.line), f"the table {table.fullname!r} is created twice"
            )

    def _add_enum(self, create: exp.Create) -> None:
        body = create.args.get("expression")
        if isinstance(body, exp.DataType) and body.this == exp.DType.ENUM:
            self._enums.add(_qualified(create.this), [value.name for value in body.expressions])

    def _amend(self, statement: exp.Expr) -> None:
        """Gather what a statement says about a table that another statement created."""
        if isinstance(statement, exp.Comment):
            self._comment(statement)
        elif isinstance(statement, exp.Alter) and statement.args.get("kind") == "TABLE":
            self._alter(statement)

    def _comment(self, statement: exp.Comment) -> None:
        column = statement.this
        text = statement.args.get("expression")
        if statement.args.get("kind") != "COLUMN" or not isinstance(column, exp.Column) or not text:
            return
        tables = self._tables.matches(tuple(part.name for part in column.parts[:-1]))
        if len(tables) == 1 and text.name:
            tables[0].comments[column.name] = text.name

    def _alter(self, statement: exp.Alter) -> None:
        tables = self._tables.matches(_qualified(statement.this))
        if len(tables) != 1:
            return  # a table that this file does not create: nothing to say about it here
        table = tables[0]
        for action in statement.args.get("actions") or []:
            key = _added_primary_key(action)
            if key is not None:
                table.primary_key |= _key_columns(key)
            elif _changes_columns(action):
                table.refused.append(self._refusal(table, statement, action))

    def _refusal(self, table: Table, statement: exp.Alter, action: exp.Expr) -> ReadError:
        added = "ADD COLUMN " if isinstance(action, exp.ColumnDef) else ""
        shown = added + " ".join(action.sql(self._dialect).split())
        shown = shown if len(shown) <= _SHOWN else shown[:_SHOWN] + "…"
        return unsupported(
            place(table.fullname, line_of(statement.this)),
            f"ALTER TABLE ... {shown} changes the columns, and the import does not apply ALTER "
            "statements: put the change in the CREATE TABLE",
            degradable=False,
        )


def _creates_table(command: exp.Command) -> bool:
    """Whether a statement the parser left as plain text was a ``CREATE TABLE``."""
    return command.name.upper() == "CREATE" and bool(
        _CREATE_TABLE.match(command.text("expression"))
    )


def _table_of(create: exp.Create) -> Table:
    """The table a ``CREATE TABLE`` defines, if it lists the columns itself."""
    schema = create.this
    node = schema.this if isinstance(schema, exp.Schema) else schema
    parts, line = _qualified(node), line_of(node)
    where = place(".".join(parts), line)
    properties = create.args.get("properties")
    inherits = properties is not None and properties.find(exp.InheritsProperty) is not None
    if not isinstance(schema, exp.Schema):
        raise unsupported(
            where,
            "a CREATE TABLE without a list of columns (AS SELECT, LIKE, PARTITION OF) "
            "has columns that the file does not list",
            degradable=False,
        )
    if inherits or any(isinstance(item, exp.LikeProperty) for item in schema.expressions):
        raise unsupported(
            where,
            "a table that takes columns from another one (LIKE, INHERITS) has columns that the "
            "file does not list",
            degradable=False,
        )
    return Table(parts, _columns_of(schema), line, _declared_primary_key(schema))


def _columns_of(schema: exp.Schema) -> list[exp.ColumnDef]:
    """The columns a table lists. The parser gives one with no type and no constraint as a name."""
    return [
        item if isinstance(item, exp.ColumnDef) else exp.ColumnDef(this=item)
        for item in schema.expressions
        if isinstance(item, exp.ColumnDef | exp.Identifier)
    ]


def _declared_primary_key(schema: exp.Schema) -> set[str]:
    """The columns that a ``PRIMARY KEY (...)`` in the table lists."""
    names: set[str] = set()
    for item in schema.expressions:
        if not isinstance(item, exp.ColumnDef | exp.Identifier):
            key = item if isinstance(item, exp.PrimaryKey) else item.find(exp.PrimaryKey)
            names |= _key_columns(key) if key is not None else set()
    return names


def _added_primary_key(action: exp.Expr) -> exp.PrimaryKey | None:
    """The primary key that an ``ADD CONSTRAINT`` or an ``ADD PRIMARY KEY`` adds."""
    if not isinstance(action, exp.AddConstraint):
        return None
    for item in action.expressions:
        key: exp.PrimaryKey | None = item.find(exp.PrimaryKey)
        if key is not None:
            return key
    return None


def _key_columns(key: exp.PrimaryKey) -> set[str]:
    """The names of the columns of a primary key."""
    names: set[str] = set()
    for item in key.expressions:
        identifier = item if isinstance(item, exp.Identifier) else item.find(exp.Identifier)
        if identifier is not None:
            names.add(identifier.name)
    return names


def _changes_columns(action: exp.Expr) -> bool:
    """Whether an action of an ALTER TABLE adds, drops, renames or changes a column."""
    if isinstance(action, exp.ColumnDef | exp.RenameColumn | exp.ModifyColumn | exp.AlterRename):
        return True
    if isinstance(action, exp.Drop):
        return action.args.get("kind") == "COLUMN"
    if isinstance(action, exp.AlterColumn):
        only_the_default = action.args.get("default") is not None or (
            action.args.get("drop") and not action.args.get("allow_null")
        )
        return not only_the_default
    return False


def _qualified(node: exp.Expr) -> tuple[str, ...]:
    """The dotted name of a table or a type, as the statement writes it."""
    return tuple(part.name for part in node.parts) if isinstance(node, exp.Table) else ()


def line_of(node: exp.Expr) -> int | None:
    """The line of the file where a name is written."""
    identifier = node if isinstance(node, exp.Identifier) else node.find(exp.Identifier)
    line = identifier.meta.get("line") if identifier is not None else None
    return line if isinstance(line, int) else None
