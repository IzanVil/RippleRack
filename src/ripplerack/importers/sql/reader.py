"""Translate the columns of one table of a SQL file into the fields of a RippleRack schema."""

from __future__ import annotations

from sqlglot import exp

from ripplerack.importers.base import ImportResult, IssueCode, is_identifier
from ripplerack.importers.common import Reader, ReadError, name_schema, one_line, with_note
from ripplerack.importers.sql.catalog import Catalog, Table, line_of
from ripplerack.importers.sql.column_types import ColumnType, NoEquivalentError, column_type
from ripplerack.importers.sql.parse import parse_statements, quiet
from ripplerack.importers.sql.problems import invalid, place, unsupported
from ripplerack.models import FieldType, SchemaField
from ripplerack.parser import ErrorCode

# A column with one of these constraints, or of one of these types, always has a value.
_ALWAYS_SET = (
    exp.PrimaryKeyColumnConstraint,
    exp.AutoIncrementColumnConstraint,
    exp.GeneratedAsIdentityColumnConstraint,
)
_SERIAL_TYPES = (exp.DType.SERIAL, exp.DType.SMALLSERIAL, exp.DType.BIGSERIAL)


class SqlReader(Reader):
    """Reads one SQL file; collects every problem and warning before reporting."""

    def __init__(self, text: str, *, dialect: str | None, lenient: bool) -> None:
        super().__init__(
            lenient=lenient,
            invalid=ErrorCode.INVALID_SQL,
            unsupported=ErrorCode.UNSUPPORTED_SQL,
            subject="SQL file",
            unit="columns",
        )
        self._text = text
        self._dialect = dialect

    def read(
        self, *, source: str, name: str | None, version: str, select: str | None
    ) -> ImportResult:
        """The schema of the table chosen, or the error listing all that is wrong."""
        fields: list[SchemaField] = []
        table_name = ""
        with quiet():
            try:
                catalog = Catalog(parse_statements(self._text, self._dialect), self._dialect)
                table = catalog.choose(select)
                table_name = table.name
                self._problems.extend(table.refused)
                fields = self._fields(table, catalog)
            except ReadError as error:
                self._problems.append(error)
        schema_name = name if name is not None else name_schema([table_name], source)
        return self._finish(source=source, name=schema_name, version=version, fields=fields)

    def _fields(self, table: Table, catalog: Catalog) -> list[SchemaField]:
        fields: list[SchemaField] = []
        seen: set[str] = set()
        for definition in table.columns:
            try:
                fields.append(self._field(definition, table, catalog, seen))
            except ReadError as error:
                self._problems.append(error)
        if not fields and not self._problems:
            self._problems.append(
                unsupported(
                    place(table.fullname, table.line),
                    "the table declares no columns to import",
                    degradable=False,
                )
            )
        return fields

    def _field(
        self, definition: exp.ColumnDef, table: Table, catalog: Catalog, seen: set[str]
    ) -> SchemaField:
        name = definition.name
        pointer = place(f"{table.name}.{name}", line_of(definition))
        _check_name(name, pointer, seen)
        translated = self._translated(name, definition, pointer, catalog)
        constraints = [
            constraint.args["kind"] for constraint in definition.args.get("constraints") or []
        ]
        return SchemaField(
            name=name,
            type=translated.type,
            nullable=_nullable(definition, constraints, table, self._dialect),
            description=with_note(_description(name, constraints, table), translated.note),
        )

    def _translated(
        self, name: str, definition: exp.ColumnDef, pointer: str, catalog: Catalog
    ) -> ColumnType:
        """The type of the column ``name``.

        With ``lenient``, a type that has no equivalent gives a ``json`` field and a warning.
        """
        kind = definition.args.get("kind")
        try:
            if not isinstance(kind, exp.DataType):
                raise NoEquivalentError("the column has no type")
            return column_type(kind, self._dialect, catalog.enum_values)
        except NoEquivalentError as refusal:
            error = unsupported(pointer, str(refusal))
            if not self._lenient:
                raise error from refusal
            self._warn(
                IssueCode.DEGRADED_TO_JSON,
                pointer,
                f"{error.message}; column {name!r} imported as json",
            )
            return ColumnType(FieldType.JSON)


def _check_name(name: str, pointer: str, seen: set[str]) -> None:
    """A column name must be usable as it is, and not used by another column."""
    if not is_identifier(name):
        raise unsupported(
            pointer,
            f"column name {name!r} is not a valid field name "
            "(letters, digits, '_', '.' and '-' only)",
            degradable=False,
        )
    if name in seen:
        raise invalid(pointer, f"column {name!r} is declared more than once")
    seen.add(name)


def _nullable(
    definition: exp.ColumnDef, constraints: list[exp.Expr], table: Table, dialect: str | None
) -> bool:
    """A column can be null unless it is a key, a counter or declared ``NOT NULL``."""
    if dialect == "clickhouse":
        return _clickhouse_nullable(definition.args.get("kind"), constraints)
    declared = any(
        isinstance(constraint, exp.NotNullColumnConstraint)
        and not constraint.args.get("allow_null")
        for constraint in constraints
    )
    always_set = any(isinstance(constraint, _ALWAYS_SET) for constraint in constraints)
    kind = definition.args.get("kind")
    serial = isinstance(kind, exp.DataType) and kind.this in _SERIAL_TYPES
    return not (declared or always_set or serial or definition.name in table.primary_key)


def _clickhouse_nullable(kind: object, constraints: list[exp.Expr]) -> bool:
    """In ClickHouse a column can be null only if its type is ``Nullable(...)``, or it says NULL."""
    if (
        isinstance(kind, exp.DataType)
        and kind.this == exp.DType.LOWCARDINALITY
        and kind.expressions
    ):
        kind = kind.expressions[0]  # LowCardinality(Nullable(String))
    wrapped = isinstance(kind, exp.DataType) and bool(kind.args.get("nullable"))
    said = any(
        isinstance(constraint, exp.NotNullColumnConstraint) and constraint.args.get("allow_null")
        for constraint in constraints
    )
    return wrapped or said


def _description(name: str, constraints: list[exp.Expr], table: Table) -> str:
    """The comment of the column, from the column itself or from ``COMMENT ON COLUMN``."""
    for constraint in constraints:
        if isinstance(constraint, exp.CommentColumnConstraint):
            return one_line(constraint.name)
    return one_line(table.comments.get(name, ""))
