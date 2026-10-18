"""From a SQL file to a schema: which table, what is left out, and everything that can go wrong."""

from __future__ import annotations

import logging
import subprocess
import sys

import pytest

from ripplerack.importers.sql import import_sql, sql_dialects
from ripplerack.importers.sql.problems import place
from ripplerack.parser import ErrorCode, RippleRackError
from tests.sql_helpers import fails, fields, issues

INVALID = ErrorCode.INVALID_SQL
UNSUPPORTED = ErrorCode.UNSUPPORTED_SQL

TWO = "CREATE TABLE a (x int); CREATE TABLE b (y text);"
DUMP = """
SET statement_timeout = 0;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TYPE public.mood AS ENUM ('sad', 'ok');
CREATE FUNCTION public.touch() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  CREATE TABLE inside_a_function (nothing int);
  RETURN NEW;
END;
$$;
CREATE TABLE public.orders (id bigint NOT NULL, mood public.mood, note text);
ALTER TABLE public.orders OWNER TO app;
CREATE SEQUENCE public.orders_id_seq START WITH 1;
ALTER SEQUENCE public.orders_id_seq OWNED BY public.orders.id;
CREATE INDEX idx_orders_mood ON public.orders USING btree (mood);
ALTER TABLE ONLY public.orders ALTER COLUMN id SET DEFAULT nextval('public.orders_id_seq');
ALTER TABLE ONLY public.orders ADD CONSTRAINT orders_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.orders ADD CONSTRAINT orders_u UNIQUE (note);
ALTER TABLE ONLY public.orders ADD CONSTRAINT orders_fk FOREIGN KEY (id) REFERENCES public.x (id);
CREATE TRIGGER touch BEFORE UPDATE ON public.orders FOR EACH ROW EXECUTE FUNCTION public.touch();
CREATE VIEW public.v AS SELECT id FROM public.orders;
COMMENT ON TABLE public.orders IS 'All the orders';
GRANT SELECT ON TABLE public.orders TO readonly;
"""


@pytest.mark.parametrize(
    ("name", "line", "expected"),
    [
        ("orders.status", 57, "orders.status (line 57)"),
        ("orders", None, "orders"),
        ("", 57, "line 57"),
        ("", None, ""),
    ],
)
def test_a_place_says_the_name_and_the_line_when_it_has_them(
    name: str, line: int | None, expected: str
) -> None:
    assert place(name, line) == expected


# ---------------------------------------------------------------------- the table to import


def test_a_file_with_one_table_needs_no_select() -> None:
    assert fields("CREATE TABLE t (a int, b text);") == [
        ("a", "integer", True, ""),
        ("b", "string", True, ""),
    ]


def test_the_fields_keep_the_order_of_the_columns() -> None:
    names = [name for name, *_ in fields("CREATE TABLE t (zeta int, alpha int, mid int);")]
    assert names == ["zeta", "alpha", "mid"]


def test_several_tables_need_to_be_told_which() -> None:
    fails(TWO, UNSUPPORTED, "creates several tables ('a', 'b')", "choose one with --select")


def test_select_chooses_a_table_by_its_name() -> None:
    assert fields(TWO, select="b") == [("y", "string", True, "")]


def test_select_chooses_a_table_whatever_the_order_of_the_file() -> None:
    assert fields(TWO, select="a") == [("x", "integer", True, "")]


def test_select_chooses_among_schemas_by_the_whole_name() -> None:
    sql = "CREATE TABLE one.t (x int); CREATE TABLE two.t (y text);"
    assert fields(sql, select="two.t") == [("y", "string", True, "")]
    assert fields(sql, select="one.t") == [("x", "integer", True, "")]


def test_a_name_that_two_tables_share_must_be_given_with_the_schema() -> None:
    sql = "CREATE TABLE one.t (x int); CREATE TABLE two.t (y text);"
    fails(
        sql,
        UNSUPPORTED,
        "several tables are called 't' ('one.t', 'two.t')",
        "the schema",
        select="t",
    )


def test_the_whole_name_wins_over_the_end_of_another() -> None:
    sql = "CREATE TABLE t (x int); CREATE TABLE s.t (y text);"
    assert fields(sql, select="t") == [("x", "integer", True, "")]
    assert fields(sql, select="s.t") == [("y", "string", True, "")]


def test_a_name_with_a_schema_finds_the_table_when_the_file_adds_a_catalog() -> None:
    assert fields("CREATE TABLE db.sch.t (x int);", select="sch.t") == [("x", "integer", True, "")]


@pytest.mark.parametrize("select", ["nope", "T", "s.", ""])
def test_select_names_a_table_that_the_file_does_not_create(select: str) -> None:
    fails(
        "CREATE TABLE t (a int); CREATE TABLE s.u (b int);",
        UNSUPPORTED,
        f"no table called {select!r}",
        "its tables are 's.u', 't'",
        select=select,
    )


def test_select_in_a_file_with_no_table_at_all() -> None:
    fails("SELECT 1;", UNSUPPORTED, "no table called 'x'", select="x")


def test_a_file_that_creates_no_table_has_nothing_to_import() -> None:
    fails("CREATE VIEW v AS SELECT 1; CREATE INDEX i ON t (a);", UNSUPPORTED, "creates no table")


def test_a_long_list_of_tables_is_cut_with_a_count() -> None:
    sql = "".join(f"CREATE TABLE t{n:02} (a int);" for n in range(12))
    fails(sql, UNSUPPORTED, "'t09', … (12 in all)")


def test_the_same_table_created_twice_is_invalid() -> None:
    fails("CREATE TABLE t (a int); CREATE TABLE t (b int);", INVALID, "t (line 1)", "created twice")


def test_the_same_name_in_two_schemas_is_two_tables() -> None:
    assert fields("CREATE TABLE a.t (x int); CREATE TABLE b.t (y int);", select="a.t")


@pytest.mark.parametrize("keyword", ["TEMPORARY", "TEMP", "UNLOGGED", "GLOBAL TEMPORARY"])
def test_every_kind_of_table_is_a_table(keyword: str) -> None:
    assert fields(f"CREATE {keyword} TABLE t (a int);", dialect="postgres")


def test_if_not_exists_and_or_replace_make_no_difference() -> None:
    assert fields("CREATE TABLE IF NOT EXISTS t (a int);") == fields("CREATE TABLE t (a int);")
    assert fields("CREATE OR REPLACE TABLE t (a int);") == fields("CREATE TABLE t (a int);")


# -------------------------------------------------------------------- the name of the schema


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        ("orders", "orders"),
        ("OrderItems", "order_items"),
        ("public.orders", "orders"),  # without the schema
        ("db.sch.Orders", "orders"),
        ('"Order Items"', "order_items"),
        ("`Order-Items`", "order_items"),
    ],
)
def test_the_schema_is_called_as_the_table_without_its_schema(table: str, expected: str) -> None:
    result = import_sql(f"CREATE TABLE {table} (a int);", source="dump.sql", dialect="mysql")
    assert result.schema.name == expected


def test_the_name_option_wins() -> None:
    result = import_sql("CREATE TABLE t (a int);", source="dump.sql", name="mine", version="2.0.0")
    assert (result.schema.name, result.schema.version) == ("mine", "2.0.0")


def test_a_table_that_cannot_name_the_schema_leaves_it_to_the_file() -> None:
    result = import_sql('CREATE TABLE "日本語" (a int);', source="dir/Customer Data.sql")
    assert result.schema.name == "customer_data"


def test_the_version_defaults_to_1_0_0() -> None:
    assert import_sql("CREATE TABLE t (a int);", source="t.sql").schema.version == "1.0.0"


def test_a_name_or_version_the_model_rejects_is_a_validation_error() -> None:
    fails_with = ErrorCode.VALIDATION_FAILED
    fails("CREATE TABLE t (a int);", fails_with, "version", version="one")


# -------------------------------------------------------------------- what is left out


def test_a_pg_dump_gives_its_table_and_leaves_out_the_rest() -> None:
    assert fields(DUMP, dialect="postgres") == [
        ("id", "integer", False, ""),  # the primary key is added by ALTER TABLE
        ("mood", "string", True, "One of: sad, ok"),
        ("note", "string", True, ""),
    ]


def test_a_table_created_inside_the_body_of_a_function_is_not_a_table_of_the_file() -> None:
    names = [name for name, *_ in fields(DUMP, dialect="postgres")]
    assert "nothing" not in names
    fails(
        DUMP + "CREATE TABLE other (a int);",
        UNSUPPORTED,
        "creates several tables ('other', 'public.orders')",
        dialect="postgres",
    )


def test_set_grant_comment_on_table_and_views_say_nothing_about_columns() -> None:
    sql = "SET x = 1; GRANT ALL ON t TO me; CREATE VIEW v AS SELECT 1; CREATE TABLE t (a int);"
    assert fields(sql + "COMMENT ON TABLE t IS 'x';") == [("a", "integer", True, "")]


def test_an_alter_table_that_changes_no_column_is_ignored() -> None:
    sql = """CREATE TABLE t (a int);
    ALTER TABLE t ALTER COLUMN a SET DEFAULT 5;
    ALTER TABLE t ALTER COLUMN a DROP DEFAULT;
    ALTER TABLE t ADD CONSTRAINT u UNIQUE (a);
    ALTER TABLE t ADD CONSTRAINT f FOREIGN KEY (a) REFERENCES o (id);
    ALTER TABLE t ADD CONSTRAINT c CHECK (a > 0);
    ALTER TABLE t OWNER TO me;
    ALTER TABLE t ENABLE ROW LEVEL SECURITY;
    ALTER TABLE t DROP CONSTRAINT IF EXISTS c CASCADE;
    """
    assert fields(sql, dialect="postgres") == [("a", "integer", True, "")]


def test_an_alter_table_of_mysql_that_changes_no_column_is_ignored() -> None:
    sql = """CREATE TABLE t (a int);
    ALTER TABLE t ADD KEY k (a);
    ALTER TABLE t DROP FOREIGN KEY f;
    ALTER TABLE t DROP INDEX i;
    ALTER TABLE t DROP PRIMARY KEY;
    ALTER TABLE t ENGINE=InnoDB;
    """
    assert fields(sql, dialect="mysql") == [("a", "integer", True, "")]


@pytest.mark.parametrize("statement", ["ALTER VIEW t RENAME TO u", "ALTER INDEX t RENAME TO u"])
def test_an_alter_of_something_that_is_not_a_table_is_not_an_alter_table(statement: str) -> None:
    sql = f"CREATE TABLE s.t (a int); {statement};"
    assert fields(sql, dialect="postgres") == [("a", "integer", True, "")]


def test_a_comment_on_a_table_is_not_taken_for_one_on_a_column() -> None:
    sql = "CREATE TABLE s (s int); COMMENT ON TABLE s.s IS 'About the table';"
    assert fields(sql, dialect="postgres") == [("s", "integer", True, "")]


def test_a_comment_on_a_column_of_two_tables_is_about_neither() -> None:
    sql = "CREATE TABLE a.t (c int); CREATE TABLE b.t (c int); COMMENT ON COLUMN t.c IS 'Which?';"
    assert fields(sql, select="a.t", dialect="postgres")[0][3] == ""
    assert fields(sql, select="b.t", dialect="postgres")[0][3] == ""


def test_a_comment_on_a_column_finds_the_table_by_its_whole_name() -> None:
    sql = (
        "CREATE TABLE a.t (c int); CREATE TABLE b.t (c int); COMMENT ON COLUMN b.t.c IS 'This one';"
    )
    assert fields(sql, select="a.t", dialect="postgres")[0][3] == ""
    assert fields(sql, select="b.t", dialect="postgres")[0][3] == "This one"


def test_an_alter_table_of_another_table_is_ignored() -> None:
    sql = "CREATE TABLE t (a int); ALTER TABLE elsewhere ADD COLUMN x int;"
    assert fields(sql) == [("a", "integer", True, "")]


def test_an_alter_table_that_finds_two_tables_is_about_neither() -> None:
    sql = "CREATE TABLE a.t (x int); CREATE TABLE b.t (y int); ALTER TABLE t ADD COLUMN z int;"
    assert fields(sql, select="a.t") == [("x", "integer", True, "")]


# ------------------------------------------------------------------------ what is refused


@pytest.mark.parametrize(
    "alter",
    [
        "ADD COLUMN extra int",
        "ADD COLUMN IF NOT EXISTS extra int",
        "DROP COLUMN b",
        "RENAME COLUMN b TO c",
        "ALTER COLUMN b TYPE bigint",
        "ALTER COLUMN b SET NOT NULL",
        "ALTER COLUMN b DROP NOT NULL",
        "RENAME TO u",
    ],
)
def test_an_alter_table_that_changes_the_columns_is_refused(alter: str) -> None:
    sql = f"CREATE TABLE t (a int, b int); ALTER TABLE t {alter};"
    fails(
        sql,
        UNSUPPORTED,
        "t (line 1)",
        "changes the columns",
        "put the change in the CREATE TABLE",
        dialect="postgres",
    )


@pytest.mark.parametrize(
    "alter",
    [
        "ADD COLUMN c int NOT NULL",
        "MODIFY COLUMN b bigint",
        "CHANGE COLUMN b c int",
        "DROP COLUMN b",
    ],
)
def test_the_alter_table_of_mysql_that_changes_the_columns_is_refused(alter: str) -> None:
    sql = f"CREATE TABLE t (a int, b int); ALTER TABLE t {alter};"
    fails(sql, UNSUPPORTED, "changes the columns", dialect="mysql")


def test_every_alter_table_that_changes_the_columns_is_listed_with_its_line() -> None:
    sql = "CREATE TABLE t (a int);\nALTER TABLE t ADD COLUMN b int;\n\nALTER TABLE t DROP COLUMN a;"
    message = fails(sql, UNSUPPORTED, "ADD COLUMN b INT", "DROP COLUMN a")
    assert message.count("changes the columns") == 2
    assert "t (line 2)" in message
    assert "t (line 4)" in message


def test_an_alter_table_is_refused_even_with_lenient() -> None:
    sql = "CREATE TABLE t (a int); ALTER TABLE t ADD COLUMN b int;"
    message = fails(sql, UNSUPPORTED, "changes the columns", lenient=True)
    assert "hint" not in message


@pytest.mark.parametrize(
    ("statement", "fragment"),
    [
        ("CREATE TABLE t AS SELECT 1 AS a", "without a list of columns"),
        ("CREATE TABLE t PARTITION OF p FOR VALUES IN (1)", "without a list of columns"),
        ("CREATE TABLE t (LIKE other)", "takes columns from another one"),
        ("CREATE TABLE t (a int) INHERITS (other)", "takes columns from another one"),
    ],
)
def test_a_table_whose_columns_the_file_does_not_list_is_refused(
    statement: str, fragment: str
) -> None:
    fails(statement, UNSUPPORTED, "t (line 1)", fragment, dialect="postgres", lenient=True)


def test_a_table_like_another_is_refused_even_when_it_is_not_the_one_imported() -> None:
    fails(
        "CREATE TABLE s (a int); CREATE TABLE t (LIKE s);",
        UNSUPPORTED,
        "t (line 1)",
        select="s",
        dialect="postgres",
    )


def test_a_table_with_no_columns_has_nothing_to_import() -> None:
    fails("CREATE TABLE t ();", UNSUPPORTED, "t (line 1)", "declares no columns")


@pytest.mark.parametrize("name", ["order date", "a/b", "ünïcode", "x y"])
def test_a_column_name_that_is_not_a_field_name_is_never_renamed_or_skipped(name: str) -> None:
    message = fails(
        f'CREATE TABLE t (ok int, "{name}" int);',
        UNSUPPORTED,
        f"t.{name} (line 1)",
        "not a valid field name",
    )
    assert "hint" not in message


def test_a_column_name_that_is_not_a_field_name_is_an_error_with_lenient() -> None:
    fails('CREATE TABLE t ("a b" int);', UNSUPPORTED, "not a valid field name", lenient=True)


def test_names_with_dots_dashes_and_digits_are_fine() -> None:
    assert [n for n, *_ in fields('CREATE TABLE t ("a.b" int, "c-d" int, e2 int);')] == [
        "a.b",
        "c-d",
        "e2",
    ]


def test_the_same_column_twice_is_invalid() -> None:
    fails(
        "CREATE TABLE t (a int, b int, a text);", INVALID, "t.a (line 1)", "declared more than once"
    )


def test_every_problem_is_reported_at_once_and_in_order() -> None:
    sql = 'CREATE TABLE t (\n  a geometry,\n  "b c" int,\n  d int4range,\n  a int\n);'
    message = fails(
        sql, INVALID, dialect="postgres"
    )  # one invalid problem makes the whole error invalid
    lines = message.splitlines()
    assert [line.split(":")[0].strip() for line in lines[1:]] == [
        "t.a (line 2)",
        "t.b c (line 3)",
        "t.d (line 4)",
        "t.a (line 5)",
    ]
    assert "hint" not in message


def test_unsupported_problems_alone_make_an_unsupported_error_with_a_hint() -> None:
    message = fails(
        "CREATE TABLE t (a geometry, b int4range);", UNSUPPORTED, "t.a", "t.b", dialect="postgres"
    )
    assert message.endswith("hint: --lenient imports columns like these as json fields")


def test_lenient_imports_what_it_can_and_the_rest_is_still_listed() -> None:
    sql = 'CREATE TABLE t (a geometry, "b c" int, d int);'
    message = fails(sql, UNSUPPORTED, "t.b c", dialect="postgres", lenient=True)
    assert "t.a" not in message


def test_a_degraded_column_gives_one_warning_with_its_place() -> None:
    sql = "CREATE TABLE t (\n  ok int,\n  geo geometry(Point, 4326)\n);"
    [warning] = issues(sql, dialect="postgres", lenient=True)
    assert str(warning).startswith("warning[degraded_to_json] t.geo (line 3): the type GEOMETRY")


def test_strict_mode_gives_no_warning_for_what_it_imports() -> None:
    assert issues("CREATE TABLE t (a int, b text);") == []


# ------------------------------------------------------------------------- syntax errors


def test_a_syntax_error_says_the_line_and_the_column() -> None:
    message = fails("CREATE TABLE t (\n  a int,\n  b int c\n);", INVALID, "line 3, column 9")
    assert "give --dialect" in message  # without a dialect, the likely cause is the dialect


def test_a_syntax_error_with_a_dialect_does_not_blame_it() -> None:
    message = fails("CREATE TABLE t (a int", INVALID, "line 1", dialect="postgres")
    assert "dialect" not in message


def test_text_that_cannot_be_split_into_tokens_is_invalid() -> None:
    fails("CREATE TABLE t (a int DEFAULT 'oops);", INVALID, "tokenizing")


def test_a_create_table_the_dialect_leaves_as_plain_text_is_invalid() -> None:
    message = fails(
        "CREATE TABLE `t` (`a` int) ENGINE=InnoDB;",
        INVALID,
        "does not understand",
        "CREATE TABLE `t`",
    )
    assert "give --dialect" in message
    fails(
        "CREATE FOREIGN TABLE t (a int) SERVER s;",
        INVALID,
        "the postgres dialect does not understand",
        dialect="postgres",
    )


def test_a_create_table_left_as_plain_text_is_invalid_even_if_it_is_not_the_one_imported() -> None:
    fails(
        "CREATE TABLE s (a int); CREATE FOREIGN TABLE t (a int) SERVER x;",
        INVALID,
        "FOREIGN TABLE",
        select="s",
        dialect="postgres",
    )


def test_other_commands_the_parser_leaves_as_plain_text_are_ignored() -> None:
    sql = "CREATE TABLE t (a int); ALTER TABLE t OWNER TO me; CREATE TABLESPACE s LOCATION '/x';"
    assert fields(sql, dialect="postgres") == [("a", "integer", True, "")]


def test_a_long_statement_is_cut_in_the_message() -> None:
    sql = "CREATE TABLE `t` (" + ", ".join(f"`c{n}` int" for n in range(40)) + ") ENGINE=InnoDB;"
    message = fails(sql, INVALID, "does not understand")
    assert "…" in message
    assert len(message.splitlines()[1]) < 220


def test_the_parser_does_not_log_what_it_leaves_as_plain_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    sql = "CREATE TABLE t (a int); ALTER TABLE t OWNER TO me;"
    import_sql(sql, source="t.sql", dialect="postgres")
    with pytest.raises(RippleRackError, match="cannot import"):
        import_sql("CREATE TABLE `t` (`a` int) ENGINE=InnoDB;", source="t.sql")
    alter = "CREATE TABLE t (a int); ALTER TABLE t ALTER COLUMN a TYPE bigint;"
    with pytest.raises(RippleRackError, match="changes the columns"):
        import_sql(alter, source="t.sql", dialect="postgres")
    assert [record.getMessage() for record in caplog.records if record.name == "sqlglot"] == []


def test_the_level_of_the_logger_of_the_parser_is_left_as_it_was() -> None:
    logger = logging.getLogger("sqlglot")
    before = logger.level
    logger.setLevel(logging.INFO)
    try:
        import_sql("CREATE TABLE t (a int);", source="t.sql")
        assert logger.level == logging.INFO
        with pytest.raises(RippleRackError):
            import_sql("CREATE TABLE t (a int", source="t.sql")
        assert logger.level == logging.INFO
    finally:
        logger.setLevel(before)


def test_a_file_that_is_not_understood_prints_only_the_error() -> None:
    """With no logging set up, as outside the tests, the warnings of the parser would be seen."""
    code = (
        "from ripplerack.importers.sql import import_sql\n"
        "try:\n"
        "    import_sql('CREATE TABLE `t` (`a` int) ENGINE=InnoDB;', source='t.sql')\n"
        "except Exception as error:\n"
        "    print(type(error).__name__)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert (done.stdout.strip(), done.stderr) == ("RippleRackError", "")


# ---------------------------------------------------------------------------- the dialect


def test_the_dialect_is_read_in_lower_case_or_any_case() -> None:
    sql = "CREATE TABLE `t` (`flag` tinyint(1));"
    assert (
        fields(sql, dialect="MySQL")
        == fields(sql, dialect="mysql")
        == [("flag", "boolean", True, "")]
    )


def test_a_dialect_that_does_not_exist_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="unknown SQL dialect 'nope'"):
        import_sql("CREATE TABLE t (a int);", source="t.sql", dialect="nope")


def test_the_dialects_are_named_and_the_generic_one_is_not_among_them() -> None:
    names = sql_dialects()
    assert {"postgres", "mysql", "sqlite", "bigquery", "snowflake", "tsql"} <= set(names)
    assert "" not in names
    assert names == sorted(names)


def test_the_same_file_means_different_things_to_different_dialects() -> None:
    assert fields("CREATE TABLE t (a tinyint(1));", dialect="mysql")[0][1] == "boolean"
    assert fields("CREATE TABLE t (a tinyint(1));", dialect="tsql")[0][1] == "integer"


# ----------------------------------------------------------------------------- big files


def test_a_file_of_a_thousand_tables_is_read() -> None:
    sql = "".join(f"CREATE TABLE t{n} (a int, b text);" for n in range(1000))
    assert fields(sql, select="t999") == [("a", "integer", True, ""), ("b", "string", True, "")]


def test_a_table_of_a_thousand_columns_is_read() -> None:
    sql = "CREATE TABLE t (" + ", ".join(f"c{n} int" for n in range(1000)) + ");"
    assert len(fields(sql)) == 1000


def test_deeply_nested_sql_is_an_error_not_a_crash() -> None:
    sql = "CREATE TABLE t (a int DEFAULT " + "(" * 3000 + "1" + ")" * 3000 + ");"
    with pytest.raises(RippleRackError):
        import_sql(sql, source="t.sql")


# ----------------------------------------------------------------------- the import cost


def test_sqlglot_is_loaded_only_when_a_sql_file_is_read() -> None:
    code = (
        "import sys, ripplerack.cli, ripplerack.importers\n"
        "assert 'sqlglot' not in sys.modules, 'sqlglot was imported'\n"
        "from ripplerack.importers.sql import import_sql\n"
        "import_sql('CREATE TABLE t (a int);', source='t.sql')\n"
        "assert 'sqlglot' in sys.modules\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
