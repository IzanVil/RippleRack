# Importing SQL

`ripplerack import --from sql` reads a SQL file, the `CREATE TABLE` statements of a database dump
or of a migration, and writes one table of it as the YAML that RippleRack reads. It works like the
import of a [JSON Schema](import.md): the output, `-o`, `--force`, `--name`, `--version`,
`--lenient`, the warnings and the exit codes are the same and are explained in the
[import guide](import.md). This page is about what is particular to SQL.

```bash
ripplerack import orders.sql --from sql > orders.yaml
```

A table has no version either, so the schema gets `--version`, or `1.0.0`.

## Known limitations

A table is already close to a RippleRack schema: a list of columns, each with a type that may be
null or not. But SQL says more than a schema file can hold. Six limits are worth knowing before
you rely on the importer:

1. **Numbers, sizes and bytes lose their exactness.** A `DECIMAL` or `NUMERIC` with decimals
   becomes `float`, so its precision and scale are not kept and a value is no longer exact.
   Neither is the length of a `VARCHAR`, nor the size of an integer (`SMALLINT` and `BIGINT`
   are both `integer`), and `BYTEA` and `BLOB` become `string`, though what they hold is not
   text. A change of any of these is not detected.
2. **Arrays and structures are mapped to `json`.** A `jsonb`, a `text[]` or a `STRUCT` is a
   single field and RippleRack does not look inside it. A change *inside* it is not detected.
3. **Enum values are not modelled structurally.** The values are written into the field's
   `description` (`One of: new, paid`). Adding or removing one is therefore seen as a change of
   description, which is a *patch*, even though in practice it can break consumers that assume
   a closed set of values.
4. **One table per import.** A file can create many tables, and each import produces one
   schema. A file that creates several needs [`--select`](#several-tables-in-one-file).
5. **The columns are the ones `CREATE TABLE` gives.** An `ALTER TABLE` that adds, drops, renames
   or changes a column of the table that is imported is not applied, and the import fails
   instead of giving a schema that is out of date. Only the primary key that an `ALTER TABLE`
   adds is read. `UNIQUE`, `CHECK` and `FOREIGN KEY` constraints, `DEFAULT` values, indexes and
   the sizes of types say nothing about which fields exist, and are [left out](#the-rest-of-the-file).
6. **The parser has its limits.** SQL is read with [sqlglot](https://github.com/tobymao/sqlglot),
   which knows many dialects but not every syntax: `PRIMARY KEY CLUSTERED` of T-SQL, the
   `bit varying` type of PostgreSQL or `COMMENT ON ... IS NULL` make it fail, and the import
   says where (`invalid_sql`). It is also forgiving: a statement it cannot read as a whole, such
   as `CREATE TABL`, is left out, and if it was the only table the error says that the file
   creates none.

What has no equivalent, such as a geometry or a range, is an error or a
[warning](#strict-and-lenient). The dialects PostgreSQL, MySQL, SQLite, Snowflake, BigQuery and
T-SQL have been tried on real dumps; the others, such as ClickHouse, Oracle or DuckDB, on the
types and the constraints they write differently.

## Using it

```text
ripplerack import FILE --from sql [--dialect NAME] [--select TABLE] [-o OUT] [--name NAME] [--version X.Y.Z] [--lenient] [--force]
```

The options are those of the [import guide](import.md#using-it). Two are particular to SQL:

| option | meaning |
|--------|---------|
| `--dialect` | The flavour of SQL the file is written in: `postgres`, `mysql`, `sqlite`, `snowflake`, `bigquery`, `tsql`... Without it the standard syntax is assumed. An unknown name is a usage error that lists the ones there are, and so is using it with another format. |
| `--select` | The table to import when the file creates several: its name (`orders`) or the schema and the name (`public.orders`). See [several tables](#several-tables-in-one-file). |

### An example

[`examples/schemas/orders_v2.sql`](../examples/schemas/orders_v2.sql) is the table of the
`orders-ingest` pipeline written the way a SQL file is: not null columns, a primary key, a
nullable `VARCHAR` and the comment of a column.

```bash
ripplerack import examples/schemas/orders_v2.sql --from sql --version 2.0.0
```

```yaml
name: orders
version: 2.0.0
fields:
  - {name: order_id, type: integer}
  - {name: customer_id, type: integer}
  - {name: amount_cents, type: integer, description: Order total in cents}
  - {name: currency, type: string}
  - {name: created_at, type: timestamp}
  - {name: coupon_code, type: string, nullable: true}
```

This is the very output of [the JSON Schema example](import.md#an-example), and so exactly
[`examples/changes/orders_v2.yaml`](../examples/changes/orders_v2.yaml): it goes straight into
`impact`, and the report is the same `critical` one.

```bash
ripplerack impact examples/mini_datacenter.yaml --pipeline orders-ingest \
  --schema <(ripplerack import examples/schemas/orders_v2.sql --from sql --version 2.0.0)
```

### The dialect

SQL is not one language. A MySQL dump has backticks and `ENGINE=InnoDB`, a PostgreSQL one has
`::regclass` and `ONLY`, and the same words mean different things: `TINYINT(1)` is how MySQL
writes a boolean. RippleRack does not guess which a file is: without `--dialect` it reads the
standard syntax, and a file that is not standard SQL fails with the line and the column, and
with a hint.

```text
error: mysqldump.sql: cannot import this SQL file:
  line 6, column 28: Invalid expression / Unexpected token; if the file is not standard SQL, give --dialect
```

```bash
ripplerack import mysqldump.sql --from sql --dialect mysql
```

The dialect changes three things: the syntax that is understood, `TINYINT(1)`, which is a
`boolean` in `mysql` and an `integer` in any other, and the columns of `clickhouse`, which
cannot be null unless their type is `Nullable(...)`. The name is read in any case.

### Several tables in one file

A dump creates many tables. RippleRack does not choose between them. Without `--select` it says
which there are:

```sql
-- A small shop in MySQL: three tables, so one has to be chosen.
CREATE TABLE `customers` (
  `id` int NOT NULL AUTO_INCREMENT,
  `email` varchar(255) NOT NULL COMMENT 'Where the receipts go',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;

CREATE TABLE `order_items` (
  `order_id` int NOT NULL,
  `sku` varchar(32) NOT NULL,
  `quantity` smallint unsigned NOT NULL DEFAULT 1,
  `gift` tinyint(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`order_id`, `sku`)
) ENGINE=InnoDB;

CREATE TABLE `OrderEvents` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `kind` enum('created','paid','shipped') NOT NULL,
  `at` datetime NOT NULL,
  `detail` json DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
```

```text
error: shop.sql: cannot import this SQL file:
  the file creates several tables ('OrderEvents', 'customers', 'order_items'); choose one with --select
```

```bash
ripplerack import shop.sql --from sql --dialect mysql --select OrderEvents
```

```yaml
name: order_events
version: 1.0.0
fields:
  - {name: id, type: integer}
  - {name: kind, type: string, description: 'One of: created, paid, shipped'}
  - {name: at, type: timestamp}
  - {name: detail, type: json, nullable: true}
```

Which table is imported:

| the file creates | without `--select` | with `--select` |
|------------------|--------------------|-----------------|
| one table | that table | the table named; an error if it names another |
| several tables | an error that lists them | the table named |
| no table | an error | an error |

`--select` looks at **every table the file creates**. A table is found by its whole name,
`public.orders`, or by the end of it, `orders`, when no other table ends the same way; two tables
called `orders` in two schemas are an error that asks for the schema. A whole name is always taken
as it is, even when it is also the name alone of another table. Case matters: `Orders` is not
`orders`.

### The name and the version

The name is the first of these that gives something usable:

| source | example | name |
|--------|---------|------|
| `--name` | `--name orders_v2` | `orders_v2` |
| the name of the table | `CREATE TABLE public.OrderItems` | `order_items` |
| the file name | `customer-data.sql`, for a table whose name has no letter or digit | `customer_data` |
| nothing else | standard input, for a table whose name has no letter or digit | `schema` |

`--name` is used as given. The name of the table is made into a valid name like any other: the
schema is left out, the words of a CamelCase name are told apart (`OrderItems` becomes
`order_items`), it is written in lowercase, and every run of characters other than letters and
digits becomes `_`. A table name that is made only of other letters, such as `日本語`, is the
one case where the file name is needed.

## Translation

The columns of the table become the fields of the schema, in the order of the file. This table
shows how one column is read. The dialect is the first column and the definition of the column,
the part that follows its name, the second; the rest is the field that comes out.

| dialect | column | `type` | `nullable` | `description` |
|---------|--------|--------|------------|---------------|
| `postgres` | `bigint` | `integer` | `true` | — |
| `postgres` | `bigint NOT NULL` | `integer` | `false` | — |
| `postgres` | `integer NULL` | `integer` | `true` | — |
| `postgres` | `smallint DEFAULT 0` | `integer` | `true` | — |
| `postgres` | `integer NOT NULL DEFAULT 0` | `integer` | `false` | — |
| `postgres` | `integer PRIMARY KEY` | `integer` | `false` | — |
| `postgres` | `bigserial` | `integer` | `false` | — |
| `postgres` | `integer GENERATED ALWAYS AS IDENTITY` | `integer` | `false` | — |
| `postgres` | `numeric(12)` | `integer` | `true` | — |
| `postgres` | `numeric(12, 0)` | `integer` | `true` | — |
| `postgres` | `numeric(12, 2)` | `float` | `true` | — |
| `postgres` | `numeric` | `float` | `true` | — |
| `postgres` | `double precision` | `float` | `true` | — |
| `postgres` | `money` | `float` | `true` | — |
| `postgres` | `boolean` | `boolean` | `true` | — |
| `postgres` | `bit(1)` | `boolean` | `true` | — |
| `postgres` | `bit(8)` | `string` | `true` | — |
| `postgres` | `character varying(255)` | `string` | `true` | — |
| `postgres` | `text` | `string` | `true` | — |
| `postgres` | `citext` | `string` | `true` | — |
| `postgres` | `uuid` | `string` | `true` | — |
| `postgres` | `bytea` | `string` | `true` | — |
| `postgres` | `time` | `string` | `true` | — |
| `postgres` | `interval` | `string` | `true` | — |
| `postgres` | `inet` | `string` | `true` | — |
| `postgres` | `date` | `date` | `true` | — |
| `postgres` | `timestamp without time zone` | `timestamp` | `true` | — |
| `postgres` | `timestamp with time zone` | `timestamp` | `true` | — |
| `postgres` | `jsonb` | `json` | `true` | — |
| `postgres` | `text[]` | `json` | `true` | — |
| `mysql` | `tinyint(1)` | `boolean` | `true` | — |
| `mysql` | `tinyint` | `integer` | `true` | — |
| `mysql` | `bigint unsigned NOT NULL AUTO_INCREMENT` | `integer` | `false` | — |
| `mysql` | `decimal(10) unsigned` | `integer` | `true` | — |
| `mysql` | `float(7, 3)` | `float` | `true` | — |
| `mysql` | `mediumtext` | `string` | `true` | — |
| `mysql` | `datetime` | `timestamp` | `true` | — |
| `mysql` | `json` | `json` | `true` | — |
| `mysql` | `int COMMENT 'Primary key'` | `integer` | `true` | `Primary key` |
| `mysql` | `enum('new', 'paid') NOT NULL` | `string` | `false` | `One of: new, paid` |
| `mysql` | `enum('new', 'paid') COMMENT 'State'` | `string` | `true` | `State. One of: new, paid` |
| `mysql` | `set('x', 'y')` | `string` | `true` | — |
| `sqlite` | `INTEGER PRIMARY KEY AUTOINCREMENT` | `integer` | `false` | — |
| `sqlite` | `REAL` | `float` | `true` | — |
| `sqlite` | `BLOB` | `string` | `true` | — |
| `tsql` | `bit` | `boolean` | `true` | — |
| `tsql` | `uniqueidentifier NOT NULL` | `string` | `false` | — |
| `tsql` | `datetimeoffset` | `timestamp` | `true` | — |
| `bigquery` | `INT64` | `integer` | `true` | — |
| `bigquery` | `NUMERIC` | `float` | `true` | — |
| `bigquery` | `ARRAY<STRING>` | `json` | `true` | — |
| `bigquery` | `STRUCT<a INT64>` | `json` | `true` | — |
| `snowflake` | `NUMBER(38, 0)` | `integer` | `true` | — |
| `snowflake` | `NUMBER(10, 2)` | `float` | `true` | — |
| `snowflake` | `VARIANT` | `json` | `true` | — |
| `snowflake` | `TIMESTAMP_NTZ` | `timestamp` | `true` | — |
| `snowflake` | `STRING COMMENT 'a string'` | `string` | `true` | `a string` |
| `clickhouse` | `UInt64` | `integer` | `false` | — |
| `clickhouse` | `Nullable(String)` | `string` | `true` | — |
| `clickhouse` | `LowCardinality(Nullable(String))` | `string` | `true` | — |

In words:

* **Nullable.** A column is `nullable` unless it is declared `NOT NULL`, is part of the primary
  key, or counts by itself: `SERIAL`, `IDENTITY`, `AUTO_INCREMENT`. The primary key may be
  written in the column, in the table (`PRIMARY KEY (a, b)`) or added later with
  `ALTER TABLE ... ADD PRIMARY KEY`. A `UNIQUE` column can be null, and a `DEFAULT` says nothing
  about it. ClickHouse is the other way round: a column can be null only if its type is
  `Nullable(...)`.
* **Types.** Every integer type is `integer`, whatever its size, signed or not; `float`,
  `double`, `real` and `money` are `float`. A `DECIMAL` or `NUMERIC` is an `integer` when its
  scale is 0, written (`numeric(12, 0)`) or not (`numeric(12)`, `NUMBER(38)`), and a `float`
  otherwise, with decimals or without a precision. `boolean` and `bit(1)` are `boolean`, and so
  is `tinyint(1)` in `mysql`. Text, `uuid`, bytes (`bytea`, `blob`, `binary`), `time`,
  `interval`, network types (`inet`, `cidr`, `macaddr`), `xml`, `enum` and `set` are `string`.
  A `date` is `date`, and a `timestamp` or a `datetime`, with or without a time zone, is
  `timestamp`. `json`, `jsonb`, `variant`, `object`, `struct`, `map` and every array are `json`.
  There are 87 plain types besides those that depend on their parameters; a test fails when the
  parser learns one that is not decided.
* **Enums.** An `enum('a', 'b')` in the column, and a type that the file creates with
  `CREATE TYPE ... AS ENUM` and a column uses (before or after the table), are `string` with
  their values in the description: up to ten, then a count
  (`One of: v0, v1, v2, v3, v4, v5, v6, v7, v8, v9, … (14 values)`). The values come after the
  comment of the column.
* **Descriptions.** The comment of a column is its description, with whitespace reduced to single
  spaces so that it fits on one line. It is the `COMMENT '...'` of the column (MySQL, Snowflake)
  or a `COMMENT ON COLUMN table.column IS '...'` anywhere in the file (PostgreSQL). The comment of
  the table is not used.
* **Names.** A column name must be a valid name (letters, digits, `_`, `.` and `-`; no spaces,
  accents or `@`), and is kept as written. One that is not, such as `"order date"`, is an error,
  never renamed or skipped, because either would change the contract without anyone noticing.

### What is refused

A few types have no equivalent in a schema made of strings, numbers, booleans, dates and
JSON. They are 34 in all (geometries, ranges, vectors, `hstore`...), and so is a type that the
file does not define (`hierarchyid`, `tsvector`) or a column that has no type, which SQLite
allows. Every one is an error in strict mode and a `json` field with `--lenient`:

| dialect | columns | strict | with `--lenient` |
|---------|---------|--------|------------------|
| `postgres` | `c geometry(Point, 4326)` | `unsupported_sql` | `json` field + warning |
| `postgres` | `c int4range NOT NULL` | `unsupported_sql` | `json` field + warning |
| `postgres` | `c tsvector` | `unsupported_sql` | `json` field + warning |
| `snowflake` | `c VECTOR(FLOAT, 3)` | `unsupported_sql` | `json` field + warning |
| `sqlite` | `c` | `unsupported_sql` | `json` field + warning |
| `postgres` | `c int, c text` | `invalid_sql` | `invalid_sql` |
| `postgres` | `c int, d int e` | `invalid_sql` | `invalid_sql` |

The first five are valid SQL that RippleRack cannot express. The last two are not valid: a
column declared twice, and a word too many. `--lenient` forgives the first and not the second.

Other things are always an error, in both modes: a column name that is not valid, a table
created twice, a table with no columns, a `CREATE TABLE` whose columns the file does not list
(`AS SELECT`, `LIKE`, `INHERITS`, `PARTITION OF`), a `CREATE TABLE` that the dialect does not
understand, an `ALTER TABLE` that changes a column of the table, a file that creates no table,
several tables and no `--select`, and a `--select` that names none.

### The rest of the file

A dump has many more statements than tables. The import reads what is about the columns of the
table and leaves out the rest without a word:

* **Read**: `CREATE TYPE ... AS ENUM`, for the columns that use the type; `COMMENT ON COLUMN`,
  for the description; `ALTER TABLE ... ADD PRIMARY KEY` and
  `ALTER TABLE ... ADD CONSTRAINT ... PRIMARY KEY (...)`, for the columns that cannot be null.
  They may come before or after the `CREATE TABLE`, and a name is looked up as in
  [`--select`](#several-tables-in-one-file).
* **Left out**: `SET`, `CREATE INDEX`, `CREATE SEQUENCE`, `CREATE FUNCTION` (a `CREATE TABLE`
  inside its body is not a table of the file), `CREATE TRIGGER`, `CREATE VIEW`,
  `CREATE EXTENSION`, `GRANT`, `COMMENT ON TABLE`, `ALTER ... OWNER TO`, an `ALTER TABLE` that
  adds a `UNIQUE`, `CHECK` or `FOREIGN KEY` constraint or sets a default, and every statement
  the parser leaves as plain text.
* **Refused**: an `ALTER TABLE` of the imported table that adds, drops, renames or changes a
  column, or its null-ness. It is listed with its line; one of another table is of no concern.

```text
error: t.sql: cannot import this SQL file:
  t (line 2): ALTER TABLE ... ADD COLUMN b INT changes the columns, and the import does not apply ALTER statements: put the change in the CREATE TABLE
```

## Strict and lenient

By default nothing that decides which fields exist or what type they have is lost without anyone
noticing: if a column has no equivalent, the import fails and says where. Every problem with a
column is listed at once; a problem with the file as a whole, such as a syntax error, stops the
import at the first.

```text
error: lenient.sql: cannot import this SQL file:
  places.location (line 4): the type GEOMETRY(POINT, 4326) has no equivalent
  places.open_days (line 5): the type INT4RANGE has no equivalent
  hint: --lenient imports columns like these as json fields
```

The places are the table and the column, with the line of the file where the column is written;
a syntax error says its line and column. `--lenient` imports such columns as `json` fields, which
hold any value, keeps the comment and the nullability, and says so for each one:

```text
warning[degraded_to_json] places.location (line 4): the type GEOMETRY(POINT, 4326) has no equivalent; column 'location' imported as json
warning[degraded_to_json] places.open_days (line 5): the type INT4RANGE has no equivalent; column 'open_days' imported as json
```

It only forgives a column. A file that is not valid SQL, a column name that is not valid and an
`ALTER TABLE` that changes the columns stay errors.

## Warnings

The only warning that a SQL import gives is `degraded_to_json`, under `--lenient`, in the format
[the import guide](import.md#warnings) describes. `additional_properties_ignored` and
`undeclared_required` are about JSON Schema.

## Errors

An error is printed as an `error:` block on standard error and exits with status `1`, as in the
[import guide](import.md#errors), where `file_not_found`, `io_error` and `output_exists` are
explained. The codes of a SQL import are:

| code | meaning |
|------|---------|
| `invalid_sql` | `FILE` is not SQL that the dialect understands: a syntax error, a `CREATE TABLE` the dialect leaves as plain text, a table created twice, a column declared twice. |
| `unsupported_sql` | `FILE` is valid, but strict mode cannot import it: a type with no equivalent, a column with no type, a column name RippleRack cannot use. Also what has no table to import: a file that creates none or several and no `--select`, a `--select` that names none, a table with no columns, a table whose columns the file does not list, an `ALTER TABLE` that changes them. |

When an error has problems of both kinds, its code is `invalid_sql`.

## In CI

When the team that produces the data owns the migrations, the database can be the source of truth
for the schema RippleRack checks. Dump it, import the table, then ask what the new version would
break:

```bash
pg_dump --schema-only mydb > schema.sql
ripplerack import schema.sql --from sql --dialect postgres --select orders --version 2.0.0 -o /tmp/orders.yaml
ripplerack impact datacenter.yaml --pipeline orders-ingest --schema /tmp/orders.yaml --fail-on-breaking
```

The first command exits with `1` when the table cannot be imported and the second with `2` when a
consumer breaks, so either stops a pull request. Use strict mode there, so that a column the
importer cannot represent is not turned into a `json` field without anyone reading the warning.
