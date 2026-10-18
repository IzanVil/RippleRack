"""What the type, the constraints and the comment of a SQL column make of a field."""

from __future__ import annotations

import pytest
from sqlglot import exp

from ripplerack.importers.sql.column_types import (
    PLAIN_TYPES,
    REFUSED,
    SPECIAL_TYPES,
    NoEquivalentError,
    _type_name,
    column_type,
)
from ripplerack.parser import ErrorCode
from tests.sql_helpers import fails, fields, issues, one

UNSUPPORTED = ErrorCode.UNSUPPORTED_SQL

# ------------------------------------------------------------------------------- the table


def test_every_type_the_parser_knows_is_decided_once() -> None:
    """A type that sqlglot learns is in none of the three until someone decides about it."""
    every = set(exp.DType)
    decided = [set(PLAIN_TYPES), set(SPECIAL_TYPES), set(REFUSED)]
    assert set().union(*decided) == every, sorted(t.name for t in every.difference(*decided))
    assert sum(len(group) for group in decided) == len(every), "a type is decided twice"


def type_name(sql_type: exp.DType) -> str:
    return sql_type.name


REFUSED_TYPES = sorted(REFUSED, key=type_name)
PLAIN_TYPE_LIST = sorted(PLAIN_TYPES, key=type_name)


@pytest.mark.parametrize("sql_type", REFUSED_TYPES, ids=type_name)
def test_the_types_with_no_equivalent_are_refused(sql_type: exp.DType) -> None:
    with pytest.raises(NoEquivalentError, match="has no equivalent"):
        column_type(exp.DataType(this=sql_type), None, lambda _: None)


@pytest.mark.parametrize("sql_type", PLAIN_TYPE_LIST, ids=type_name)
def test_a_plain_type_gives_its_type_whatever_follows_it(sql_type: exp.DType) -> None:
    kind = exp.DataType(this=sql_type)
    assert column_type(kind, None, lambda _: None).type is PLAIN_TYPES[sql_type]


# --------------------------------------------------------------------------------- postgres


@pytest.mark.parametrize(
    ("sql_type", "expected"),
    [
        ("smallint", "integer"),
        ("integer", "integer"),
        ("int", "integer"),
        ("bigint", "integer"),
        ("serial", "integer"),
        ("bigserial", "integer"),
        ("smallserial", "integer"),
        ("numeric(12)", "integer"),  # the scale is 0 unless given
        ("numeric(12, 0)", "integer"),
        ("decimal(5)", "integer"),
        ("numeric(12, 2)", "float"),
        ("numeric", "float"),  # no precision: any number of digits
        ("decimal", "float"),
        ("real", "float"),
        ("double precision", "float"),
        ("float", "float"),
        ("money", "float"),
        ("boolean", "boolean"),
        ("bool", "boolean"),
        ("bit(1)", "boolean"),
        ("bit", "boolean"),
        ("bit(8)", "string"),  # a string of bits
        ("char(2)", "string"),
        ("varchar", "string"),
        ("character varying(255)", "string"),
        ("text", "string"),
        ("citext", "string"),
        ("uuid", "string"),
        ("bytea", "string"),
        ("time", "string"),
        ("time with time zone", "string"),
        ("interval", "string"),
        ("inet", "string"),
        ("cidr", "string"),
        ("macaddr", "string"),
        ("xml", "string"),
        ("date", "date"),
        ("timestamp", "timestamp"),
        ("timestamp without time zone", "timestamp"),
        ("timestamp with time zone", "timestamp"),
        ("timestamptz", "timestamp"),
        ("timestamp(3) with time zone", "timestamp"),
        ("json", "json"),
        ("jsonb", "json"),
        ("text[]", "json"),
        ("integer[][]", "json"),
    ],
)
def test_postgres_types(sql_type: str, expected: str) -> None:
    assert one(sql_type, dialect="postgres")[0] == expected


# ------------------------------------------------------------------------------------ mysql


@pytest.mark.parametrize(
    ("sql_type", "expected"),
    [
        ("tinyint(1)", "boolean"),  # how MySQL writes a boolean
        ("tinyint", "integer"),
        ("tinyint(4)", "integer"),
        ("smallint", "integer"),
        ("mediumint", "integer"),
        ("bigint unsigned", "integer"),
        ("year", "integer"),
        ("decimal(10, 2)", "float"),
        ("decimal(10, 0)", "integer"),
        ("decimal(10) unsigned", "integer"),
        ("double unsigned", "float"),
        ("float(7, 3)", "float"),
        ("bool", "boolean"),
        ("bit(1)", "boolean"),
        ("bit(8)", "string"),
        ("varchar(255)", "string"),
        ("mediumtext", "string"),
        ("longtext", "string"),
        ("blob", "string"),
        ("longblob", "string"),
        ("binary(16)", "string"),
        ("varbinary(16)", "string"),
        ("time", "string"),
        ("set('x', 'y')", "string"),
        ("enum('a', 'b')", "string"),
        ("date", "date"),
        ("datetime", "timestamp"),
        ("timestamp", "timestamp"),
        ("json", "json"),
    ],
)
def test_mysql_types(sql_type: str, expected: str) -> None:
    assert one(sql_type, dialect="mysql")[0] == expected


@pytest.mark.parametrize("dialect", [None, "postgres", "sqlite", "tsql", "snowflake"])
def test_tinyint_of_one_is_a_boolean_only_in_mysql(dialect: str | None) -> None:
    assert one("tinyint(1)", dialect=dialect)[0] == "integer"


# ---------------------------------------------------------------- the other dialects


@pytest.mark.parametrize(
    ("dialect", "sql_type", "expected"),
    [
        ("sqlite", "INTEGER", "integer"),
        ("sqlite", "TEXT", "string"),
        ("sqlite", "REAL", "float"),
        ("sqlite", "BLOB", "string"),
        ("sqlite", "NUMERIC", "float"),
        ("sqlite", "BOOLEAN", "boolean"),
        ("sqlite", "DATETIME", "timestamp"),
        ("tsql", "bit", "boolean"),
        ("tsql", "money", "float"),
        ("tsql", "uniqueidentifier", "string"),
        ("tsql", "nvarchar(max)", "string"),
        ("tsql", "datetime2(3)", "timestamp"),
        ("tsql", "datetimeoffset", "timestamp"),
        ("tsql", "smalldatetime", "timestamp"),
        ("tsql", "image", "string"),
        ("tsql", "rowversion", "string"),
        ("bigquery", "INT64", "integer"),
        ("bigquery", "FLOAT64", "float"),
        ("bigquery", "NUMERIC", "float"),
        ("bigquery", "BOOL", "boolean"),
        ("bigquery", "STRING(10)", "string"),
        ("bigquery", "BYTES", "string"),
        ("bigquery", "DATETIME", "timestamp"),
        ("bigquery", "TIMESTAMP", "timestamp"),
        ("bigquery", "ARRAY<STRING>", "json"),
        ("bigquery", "STRUCT<a INT64>", "json"),
        ("snowflake", "NUMBER(38, 0)", "integer"),
        ("snowflake", "NUMBER", "integer"),  # NUMBER is NUMBER(38, 0) in Snowflake
        ("snowflake", "NUMBER(10, 2)", "float"),
        ("snowflake", "FLOAT", "float"),
        ("snowflake", "VARIANT", "json"),
        ("snowflake", "OBJECT", "json"),
        ("snowflake", "ARRAY", "json"),
        ("snowflake", "TIMESTAMP_NTZ", "timestamp"),
        ("snowflake", "TIMESTAMP_LTZ(9)", "timestamp"),
        ("oracle", "NUMBER(10)", "integer"),
        ("oracle", "NUMBER(10, 2)", "float"),
        ("oracle", "VARCHAR2(10)", "string"),
        ("oracle", "CLOB", "string"),
        ("duckdb", "HUGEINT", "integer"),
        ("duckdb", "STRUCT(x INTEGER)", "json"),
        ("duckdb", "INTEGER[]", "json"),
        ("redshift", "SUPER", "json"),
        ("clickhouse", "UInt64", "integer"),
        ("clickhouse", "Nullable(String)", "string"),
        ("clickhouse", "LowCardinality(String)", "string"),
        ("clickhouse", "LowCardinality(Nullable(String))", "string"),
        ("clickhouse", "Array(Int32)", "json"),
        ("clickhouse", "DateTime64(3)", "timestamp"),
        ("clickhouse", "Decimal(10, 2)", "float"),
    ],
)
def test_types_of_the_other_dialects(dialect: str, sql_type: str, expected: str) -> None:
    assert one(sql_type, dialect=dialect)[0] == expected


# ----------------------------------------------------------------------------------- enums


def test_an_enum_in_the_column_lists_its_values_in_the_description() -> None:
    assert one("enum('new', 'paid')", dialect="mysql") == ("string", True, "One of: new, paid")


def test_an_enum_the_file_creates_lists_its_values_wherever_the_table_is() -> None:
    sql = "CREATE TABLE t (c mood); CREATE TYPE public.mood AS ENUM ('sad', 'ok');"
    assert fields(sql, dialect="postgres") == [("c", "string", True, "One of: sad, ok")]


def test_an_enum_is_found_by_its_whole_name_or_by_the_end_of_it() -> None:
    sql = "CREATE TYPE app.mood AS ENUM ('sad'); CREATE TABLE t (a app.mood, b mood);"
    assert fields(sql, dialect="postgres") == [
        ("a", "string", True, "One of: sad"),
        ("b", "string", True, "One of: sad"),
    ]


def test_an_enum_of_a_long_list_is_cut_with_a_count() -> None:
    values = ", ".join(f"'v{i}'" for i in range(12))
    description = one(f"enum({values})", dialect="mysql")[2]
    assert description.endswith("v9, … (12 values)")


def test_the_values_of_an_enum_come_after_the_comment() -> None:
    sql = "CREATE TABLE t (c enum('a') COMMENT 'The kind');"
    assert fields(sql, dialect="mysql") == [("c", "string", True, "The kind. One of: a")]


def test_an_array_of_enums_is_json() -> None:
    sql = "CREATE TYPE mood AS ENUM ('sad'); CREATE TABLE t (c mood[]);"
    assert fields(sql, dialect="postgres") == [("c", "json", True, "")]


@pytest.mark.parametrize("sql_type", ["hierarchyid", "tsvector", "mystery"])
def test_a_type_the_file_does_not_define_is_refused(sql_type: str) -> None:
    message = fails(f"CREATE TABLE t (c {sql_type});", UNSUPPORTED, "t.c", sql_type)
    assert "no enum of that name is defined" in message


# ---------------------------------------------------------------------------- refused types


@pytest.mark.parametrize(
    ("dialect", "sql_type"),
    [
        ("postgres", "int4range"),
        ("postgres", "geometry(Point, 4326)"),
        ("postgres", "oid"),
        ("bigquery", "GEOGRAPHY"),
        ("snowflake", "VECTOR(FLOAT, 3)"),
        ("tsql", "hierarchyid"),
    ],
)
def test_a_type_with_no_equivalent_is_an_error_and_with_lenient_a_json_field(
    dialect: str, sql_type: str
) -> None:
    fails(f"CREATE TABLE t (c {sql_type});", UNSUPPORTED, "t.c", "hint: --lenient", dialect=dialect)
    assert one(sql_type, dialect=dialect, lenient=True)[0] == "json"
    [warning] = issues(f"CREATE TABLE t (c {sql_type});", dialect=dialect, lenient=True)
    assert warning.code == "degraded_to_json"
    assert warning.pointer == "t.c (line 1)"
    assert "column 'c' imported as json" in warning.message


def test_a_column_with_no_type_is_refused_and_with_lenient_json() -> None:
    sql = "CREATE TABLE t (a INTEGER, untyped, b TEXT);"
    fails(sql, UNSUPPORTED, "t.untyped", "has no type", dialect="sqlite")
    assert fields(sql, dialect="sqlite", lenient=True) == [
        ("a", "integer", True, ""),
        ("untyped", "json", True, ""),
        ("b", "string", True, ""),
    ]


def test_a_degraded_column_keeps_what_the_constraints_say() -> None:
    sql = "CREATE TABLE t (c int4range NOT NULL); COMMENT ON COLUMN t.c IS 'Stay';"
    assert fields(sql, dialect="postgres", lenient=True) == [("c", "json", False, "Stay")]


# ------------------------------------------------------------------------------- nullable


@pytest.mark.parametrize(
    ("column", "nullable"),
    [
        ("integer", True),
        ("integer NULL", True),
        ("integer NOT NULL", False),
        ("integer DEFAULT 5", True),  # a default says nothing about null
        ("integer NOT NULL DEFAULT 5", False),
        ("integer PRIMARY KEY", False),
        ("serial", False),
        ("bigserial", False),
        ("integer GENERATED ALWAYS AS IDENTITY", False),
        ("integer GENERATED BY DEFAULT AS IDENTITY", False),
        ("integer GENERATED ALWAYS AS (1 + 1) STORED", True),
    ],
)
def test_nullable_in_postgres(column: str, nullable: bool) -> None:
    assert one(column, dialect="postgres")[1] is nullable


@pytest.mark.parametrize(
    ("column", "nullable"),
    [
        ("int AUTO_INCREMENT", False),
        ("int NOT NULL AUTO_INCREMENT", False),
        ("int", True),
        ("int DEFAULT NULL", True),
    ],
)
def test_nullable_in_mysql(column: str, nullable: bool) -> None:
    assert one(column, dialect="mysql")[1] is nullable


@pytest.mark.parametrize(
    ("table", "nullable"),
    [
        ("(c int, PRIMARY KEY (c))", False),
        ("(c int, CONSTRAINT pk PRIMARY KEY (c))", False),
        ("(c int, d int, PRIMARY KEY (d, c))", False),
        ("(c int, d int, PRIMARY KEY (d))", True),
        ("(c int, UNIQUE (c))", True),  # unique allows null
        ("(c int, d int, FOREIGN KEY (c) REFERENCES o (id))", True),
    ],
)
def test_a_primary_key_of_the_table_is_never_null(table: str, nullable: bool) -> None:
    [(_, _, found, _), *_] = fields(f"CREATE TABLE t {table};")
    assert found is nullable


@pytest.mark.parametrize(
    ("alter", "key"),
    [
        ("ALTER TABLE t ADD PRIMARY KEY (c)", {"c"}),
        ("ALTER TABLE ONLY public.t ADD CONSTRAINT t_pkey PRIMARY KEY (c)", {"c"}),
        ("ALTER TABLE t ADD CONSTRAINT t_pkey PRIMARY KEY (b, c)", {"b", "c"}),
    ],
)
def test_a_primary_key_added_by_alter_table_is_never_null(alter: str, key: set[str]) -> None:
    sql = f"CREATE TABLE public.t (b int, c int, d int); {alter};"
    assert [(name, nullable) for name, _, nullable, _ in fields(sql)] == [
        (name, name not in key) for name in "bcd"
    ]


def test_the_primary_key_may_be_added_before_the_table_is_created() -> None:
    sql = "ALTER TABLE t ADD PRIMARY KEY (c); CREATE TABLE t (c int);"
    assert fields(sql) == [("c", "integer", False, "")]


@pytest.mark.parametrize(
    ("column", "nullable"),
    [
        ("UInt64", False),
        ("Nullable(UInt64)", True),
        ("LowCardinality(String)", False),
        ("LowCardinality(Nullable(String))", True),
        ("String NULL", True),
        ("String NOT NULL", False),
    ],
)
def test_a_column_of_clickhouse_is_null_only_if_it_says_so(column: str, nullable: bool) -> None:
    sql = f"CREATE TABLE t (c {column}) ENGINE = MergeTree ORDER BY tuple();"
    assert fields(sql, dialect="clickhouse")[0][2] is nullable


# --------------------------------------------------------------------------- descriptions


def test_the_comment_of_a_column_is_its_description() -> None:
    assert one("int COMMENT 'Primary key'", dialect="mysql")[2] == "Primary key"


def test_the_comment_of_a_column_is_on_one_line() -> None:
    assert one("int COMMENT 'The   first\n  line'", dialect="mysql")[2] == "The first line"


def test_comment_on_column_is_the_description() -> None:
    sql = "CREATE TABLE public.t (c int); COMMENT ON COLUMN public.t.c IS 'Order total';"
    assert fields(sql, dialect="postgres") == [("c", "integer", True, "Order total")]


def test_comment_on_column_finds_the_table_by_the_end_of_its_name() -> None:
    sql = "CREATE TABLE public.t (c int); COMMENT ON COLUMN t.c IS 'Short';"
    assert fields(sql, dialect="postgres")[0][3] == "Short"


@pytest.mark.parametrize(
    "statement",
    [
        "COMMENT ON TABLE t IS 'About the table'",
        "COMMENT ON COLUMN t.other IS 'A column that is not there'",
        "COMMENT ON COLUMN nowhere.c IS 'A table that is not there'",
    ],
)
def test_a_comment_that_is_about_nothing_here_is_ignored(statement: str) -> None:
    sql = f"CREATE TABLE t (c int); {statement};"
    assert fields(sql, dialect="postgres") == [("c", "integer", True, "")]


def test_the_comment_of_the_column_comes_before_a_comment_on_column() -> None:
    sql = "CREATE TABLE t (c int COMMENT 'inline'); COMMENT ON COLUMN t.c IS 'later';"
    assert fields(sql, dialect="mysql")[0][3] == "inline"


def test_the_table_comment_of_mysql_is_not_a_description() -> None:
    sql = "CREATE TABLE t (c int) ENGINE=InnoDB COMMENT='About the table';"
    assert fields(sql, dialect="mysql") == [("c", "integer", True, "")]


# -------------------------------------------------------------------------------- more cases


def test_a_scale_of_zero_makes_an_integer_whatever_the_precision_is() -> None:
    assert one("NUMBER(*, 0)", dialect="oracle")[0] == "integer"
    assert one("NUMBER(*, 2)", dialect="oracle")[0] == "float"
    assert one("NUMBER(*)", dialect="oracle")[0] == "float"


@pytest.mark.parametrize("sql_type", ["CITEXT", "Citext", "CIDR", "MacAddr8"])
def test_the_text_types_of_postgres_are_found_in_any_case(sql_type: str) -> None:
    assert one(sql_type, dialect="postgres")[0] == "string"


def test_two_enums_with_the_same_name_in_two_schemas_are_told_apart() -> None:
    sql = """CREATE TYPE one.mood AS ENUM ('sad'); CREATE TYPE two.mood AS ENUM ('ok');
    CREATE TABLE t (a one.mood, b two.mood);"""
    assert [(name, note) for name, _, _, note in fields(sql, dialect="postgres")] == [
        ("a", "One of: sad"),
        ("b", "One of: ok"),
    ]


def test_an_enum_name_that_two_enums_share_must_be_given_with_the_schema() -> None:
    sql = """CREATE TYPE one.mood AS ENUM ('sad'); CREATE TYPE two.mood AS ENUM ('ok');
    CREATE TABLE t (c mood);"""
    fails(sql, UNSUPPORTED, "t.c", "several enums are called 'mood'", dialect="postgres")


def test_the_name_of_a_type_is_read_whatever_the_parser_makes_of_it() -> None:
    assert _type_name(None) == ()
    assert _type_name("HIERARCHYID") == ("HIERARCHYID",)
    assert _type_name(exp.to_identifier("mood")) == ("mood",)
    dotted = exp.Dot.build([exp.to_identifier("app"), exp.to_identifier("mood")])
    assert _type_name(dotted) == ("app", "mood")


def test_a_low_cardinality_type_that_wraps_nothing_has_no_equivalent() -> None:
    sql = "CREATE TABLE t (c LowCardinality) ENGINE = Memory;"
    fails(sql, UNSUPPORTED, "t.c", "has no equivalent", dialect="clickhouse")


def test_a_composite_type_is_not_an_enum() -> None:
    sql = "CREATE TYPE pair AS (a int, b text); CREATE TABLE t (c pair);"
    fails(sql, UNSUPPORTED, "t.c", "pair", dialect="postgres")
