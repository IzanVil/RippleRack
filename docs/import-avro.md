# Importing Avro schemas

`ripplerack import --from avro` reads an Avro schema, an `.avsc` file, and writes one of its
records as the YAML that RippleRack reads. It works like the import of a
[JSON Schema](import.md): the output, `-o`, `--force`, `--name`, `--version`, `--lenient`, the
warnings and the exit codes are the same and are explained in the [import guide](import.md).
This page is about what is particular to Avro.

```bash
ripplerack import orders.avsc --from avro > orders.yaml
```

An Avro schema has no version either, so the schema gets `--version`, or `1.0.0`.

## Known limitations

An Avro record is already close to a RippleRack schema: a list of fields, each with a type. But
Avro says more than a schema file can hold. Five limits are worth knowing before you rely on the
importer:

1. **Decimals and bytes lose their exactness.** A `decimal` becomes `float`, so its precision
   and scale are not kept and a value is no longer exact, and `bytes` and `fixed` become
   `string`, though what they hold is not text. A change of precision, of scale or of the size of
   a `fixed` is therefore not detected.
2. **Nested records, arrays and maps are mapped to `json`.** Each one is a single field and
   RippleRack does not look inside it. A change *inside* a nested record, such as removing
   `address.street`, is not detected. Removing `address` itself is. A record that contains
   itself, as a tree does, is just one more `json` field.
3. **Enum symbols are not modelled structurally.** The symbols are written into the field's
   `description` (`One of: PENDING, PAID`). Adding or removing a symbol is therefore seen as a
   change of description, which is a *patch*, even though in practice it can break consumers that
   assume a closed set of values.
4. **The namespace is not kept.** The schema is named after the record alone, so
   `com.example.Order` and `com.other.Order` give the same name. Use `--name` when that matters.
5. **One record per import.** An `.avsc` file can define many records, and each import produces
   one schema. A file that defines several needs [`--select`](#several-records-in-one-file), and
   what the other records define is used only to resolve the names the chosen one refers to.

What has no equivalent, such as a field that may be of two different types, is an error or a
[warning](#strict-and-lenient). Everything an Avro schema says that does not change which fields
exist, what type they have or whether they are optional is ignored; see
[the attributes it reads](#the-attributes-it-reads).

## Using it

```text
ripplerack import FILE --from avro [--select NAME] [-o OUT] [--name NAME] [--version X.Y.Z] [--lenient] [--force]
```

The options are those of the [import guide](import.md#using-it). Only one is particular to Avro:

| option | meaning |
|--------|---------|
| `--select` | The record to import when the file defines several: its full name (`com.example.shop.OrderEvent`) or its name alone (`OrderEvent`) when no other record has it. Using it with `--from json-schema` is a usage error. |

### An example

[`examples/schemas/orders_v2.avsc`](../examples/schemas/orders_v2.avsc) is the schema of the
`orders-ingest` pipeline written the way Avro files usually are: a namespace, a `doc` on a field,
a `long` with a logical type, and a union with `null`.

```bash
ripplerack import examples/schemas/orders_v2.avsc --from avro --version 2.0.0
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
  --schema <(ripplerack import examples/schemas/orders_v2.avsc --from avro --version 2.0.0)
```

### Several records in one file

A file may define many records, as a list of types does. This one defines three records and an
enum, and `OrderEvent` refers to `Status` and to `Address` by name:

```json
[
  {"type": "record", "name": "Address", "namespace": "com.example.shop",
   "fields": [{"name": "street", "type": "string"}, {"name": "city", "type": "string"}]},
  {"type": "enum", "name": "Status", "namespace": "com.example.shop",
   "symbols": ["PENDING", "PAID", "REFUNDED"]},
  {"type": "record", "name": "OrderEvent", "namespace": "com.example.shop",
   "fields": [
     {"name": "event_id", "type": "string"},
     {"name": "status", "type": "Status"},
     {"name": "shipping", "type": "Address"},
     {"name": "coupon", "type": ["null", "string"], "default": null}]},
  {"type": "record", "name": "Customer", "namespace": "com.example.shop",
   "fields": [{"name": "id", "type": "long"}, {"name": "email", "type": ["null", "string"]}]}
]
```

RippleRack does not choose between records. Without `--select` it says which there are:

```text
error: shop.avsc: cannot import this Avro schema:
  #: the file holds several records ('com.example.shop.Address', 'com.example.shop.Customer', 'com.example.shop.OrderEvent'); choose one with --select
```

```bash
ripplerack import shop.avsc --from avro --select OrderEvent
```

```yaml
name: order_event
version: 1.0.0
fields:
  - {name: event_id, type: string}
  - {name: status, type: string, description: 'One of: PENDING, PAID, REFUNDED'}
  - {name: shipping, type: json}
  - {name: coupon, type: string, nullable: true}
```

Which record is imported:

| the file is | without `--select` | with `--select` |
|-------------|--------------------|-----------------|
| a record | that record | the record named, which may be one defined inside it |
| a list of types that holds one record | that record | the record named |
| a list of types that holds several records | an error that lists them | the record named |
| anything else: a name, an enum, an array... | an error | the record named, wherever it is defined |

`--select` looks at **every record the file defines**, also those written inside a field. A name
that two records share, such as `Address` in two namespaces, is an error that asks for the full
name. An enum or a `fixed` is not a record and cannot be selected. A full name is always taken as
it is, even when it is also the name alone of another record.

### The name and the version

The name is the first of these that gives something usable:

| source | example | name |
|--------|---------|------|
| `--name` | `--name orders_v2` | `orders_v2` |
| the name of the record | `"name": "OrderEvent"` | `order_event` |
| the file name | `customer-events.avsc`, for a record called `_` | `customer_events` |
| nothing else | standard input, for a record called `_` | `schema` |

`--name` is used as given. The name of the record is made into a valid name like any other: the
words of a CamelCase name are told apart (`OrderEvent` becomes `order_event`, `HTTPRequest`
becomes `http_request`), it is written in lowercase, and the namespace is left out. The name of
a record is made of letters, digits and `_`, so the file name is needed only for one that has
no letter or digit in it, such as `_`.

## Translation

The fields of the record become the fields of the schema, in the order of the file. This table
shows how one field is read. Its Avro `type` is the first column and its `doc`, if it has one,
the second; the rest is the field that comes out.

| Avro `type` | `doc` | `type` | `nullable` | `description` |
|-------------|-------|--------|------------|---------------|
| `"string"` | — | `string` | `false` | — |
| `"int"` | — | `integer` | `false` | — |
| `"long"` | — | `integer` | `false` | — |
| `"float"` | — | `float` | `false` | — |
| `"double"` | — | `float` | `false` | — |
| `"boolean"` | — | `boolean` | `false` | — |
| `"bytes"` | — | `string` | `false` | — |
| `{"type": "long", "logicalType": "timestamp-millis"}` | — | `timestamp` | `false` | — |
| `{"type": "long", "logicalType": "local-timestamp-micros"}` | — | `timestamp` | `false` | — |
| `{"type": "int", "logicalType": "date"}` | — | `date` | `false` | — |
| `{"type": "string", "logicalType": "uuid"}` | — | `string` | `false` | — |
| `{"type": "int", "logicalType": "time-millis"}` | — | `string` | `false` | — |
| `{"type": "bytes", "logicalType": "decimal", "precision": 10, "scale": 2}` | — | `float` | `false` | — |
| `{"type": "fixed", "name": "Hash", "size": 16}` | — | `string` | `false` | — |
| `{"type": "enum", "name": "Status", "symbols": ["PENDING", "PAID"]}` | — | `string` | `false` | `One of: PENDING, PAID` |
| `{"type": "record", "name": "Address", "fields": [{"name": "street", "type": "string"}]}` | — | `json` | `false` | — |
| `{"type": "array", "items": "string"}` | — | `json` | `false` | — |
| `{"type": "map", "values": "long"}` | — | `json` | `false` | — |
| `["null", "string"]` | — | `string` | `true` | — |
| `["string", "null"]` | — | `string` | `true` | — |
| `["null", {"type": "long", "logicalType": "timestamp-millis"}]` | — | `timestamp` | `true` | — |
| `["null", {"type": "enum", "name": "Status", "symbols": ["NEW"]}]` | — | `string` | `true` | `One of: NEW` |
| `["string"]` | — | `string` | `false` | — |
| `"string"` | `Customer name` | `string` | `false` | `Customer name` |
| `{"type": "enum", "name": "Status", "symbols": ["NEW", "DONE"]}` | `Status` | `string` | `false` | `Status. One of: NEW, DONE` |
| `{"type": "long", "logicalType": "vendor-specific"}` | — | `integer` | `false` | — |
| `{"type": "int", "logicalType": "timestamp-millis"}` | — | `integer` | `false` | — |
| `{"type": "bytes", "logicalType": "decimal"}` | — | `string` | `false` | — |
| `{"type": "string", "default": "x", "aliases": ["y"]}` | — | `string` | `false` | — |

In words:

* **Nullable.** A field is `nullable` when its type is a union that has `null` in it, whichever
  place `null` takes. That is the only way: Avro has no equivalent of `required`, and a
  `default` does not make a field optional.
* **Types.** `int` and `long` are `integer`, and `float` and `double` are `float`. A logical type
  gives the type that fits it: `timestamp-millis`, `timestamp-micros`, `timestamp-nanos` and the
  three `local-timestamp-*` are `timestamp`, `date` is `date`, and `decimal` and `big-decimal` are
  `float`. `uuid`, `time-millis`, `time-micros` and `duration` stay `string`, like `bytes` and
  `fixed`, as RippleRack has no type for them.
* **Logical types that do not apply are ignored**, as the Avro specification asks: one that is
  unknown (`vendor-specific`), one on a type it does not fit (a `timestamp-millis` on an `int`),
  and a `decimal` without a valid `precision` and `scale`. The field has the type of what it
  sits on.
* **`json` is for everything with structure.** Records, arrays and maps are `json` fields, and
  what is inside them is not read; see the [limitations](#known-limitations).
* **Descriptions.** The `doc` of a field is its description, with whitespace reduced to single
  spaces so that it fits on one line. The `doc` of a record, of an enum or of a `fixed` is not
  used. The symbols of an enum are added after the description: up to ten, then a count
  (`One of: S0, S1, S2, S3, S4, S5, S6, S7, S8, S9, … (25 values)`). A `doc` that is not text is
  an error.
* **Names.** A field name must be a valid name (letters, digits, `_`, `.` and `-`; no spaces,
  accents or `@`). An Avro field name always is. One that is not is an error, never renamed or
  skipped, because either would change the contract without anyone noticing.

### Unions and what is refused

A union is the way Avro says a value may be of several types. One of those types and `null` is
the usual way to write an optional value, and it is read as such. Anything else has no
equivalent, since a RippleRack field has one type:

| Avro `type` | Default (strict) | With `--lenient` |
|-------------|------------------|------------------|
| `["string", "long"]` | `unsupported_avro_schema` | `json` field + warning |
| `["null", "string", "long"]` | `unsupported_avro_schema` | `json` field, nullable + warning |
| `"null"` | `unsupported_avro_schema` | `json` field, nullable + warning |
| `[]` | `unsupported_avro_schema` | `json` field + warning |
| `["null", ["string", "long"]]` | `invalid_avro_schema` | `invalid_avro_schema` |
| `"Nope"` | `invalid_avro_schema` | `invalid_avro_schema` |
| `{"type": "array"}` | `invalid_avro_schema` | `invalid_avro_schema` |
| `{"type": {"type": "string"}}` | `invalid_avro_schema` | `invalid_avro_schema` |

The first four are valid Avro that RippleRack cannot express. The last four are not valid Avro
at all: a union inside a union, a name that nothing in the file defines, an array without
`items`, and a `type` that is not a name. `--lenient` forgives the first and not the second.

Other things are always an error, in both modes: a field name that is not valid, a field
declared twice, a type defined twice, a record with no fields, a root that is not a record (a
list of types is read for the records it holds), a file with several records and no `--select`,
and a `--select` that names no record.

### References and namespaces

A name that refers to a type defined elsewhere is looked up as Avro says:

* A name with a dot is a **full name**: `com.example.shop.Address`.
* A name without one is looked up first in the **namespace of the record that uses it**, and
  then among the types that have no namespace.
* A type defined inside a record, in a field or in an array, takes the namespace of that record
  unless it has its own, or a name with a dot.
* A type may refer to the record that contains it. A tree node with a field
  `{"name": "parent", "type": ["null", "Node"]}` is fine: the field is `json`, because records
  are not read inside.
* A name that nothing in the file defines is `invalid_avro_schema`. Names are never fetched from
  another file.

### The attributes it reads

`type`, `name` and `namespace` of the types that are defined; `fields` of a record, with the
`name`, `type` and `doc` of each field; `symbols` of an enum; `items` of an array, `values` of
a map (to know they are there) and `logicalType`, with `precision` and `scale` for a `decimal`.
When one has a value of the wrong shape, such as `fields` that is not a list, the import fails
with `invalid_avro_schema`.

**Everything else is ignored without a warning**: `default`, `order`, `aliases`, the `size` of a
`fixed`, the `doc` of a record, an enum or a `fixed`, and the attributes of a vendor
(`connect.name`, `avro.java.string`...). A RippleRack schema is made of types and
nullability, and has nowhere to put them.

## Strict and lenient

By default nothing that decides which fields exist or what type they have is lost without anyone
noticing: if a field has no equivalent, the import fails and says where. Every problem with a
field is listed at once; a problem with the file as a whole, such as a duplicated name or a
record that has no `fields`, stops the import at the first.

```text
error: lenient.avsc: cannot import this Avro schema:
  #/fields/1/type: the union ['string', 'long'] mixes several types in one field
  #/fields/2/type: the union ['string', 'long'] mixes several types in one field
  #/fields/3/type: type 'null' on its own has no data type
  #/fields/4/type: an empty union has no data type
  hint: --lenient imports fields like these as json fields
```

The places are JSON pointers into the file: `#/fields/1/type` is the type of the second field of
the record, and in a list of types `#/2/fields/0` is the first field of its third element.
`--lenient` imports such fields as `json` fields, which hold any value, keeps the `doc` and the
nullability, and says so for each one:

```text
warning[degraded_to_json] #/fields/1/type: the union ['string', 'long'] mixes several types in one field; field 'choice' imported as json
warning[degraded_to_json] #/fields/2/type: the union ['string', 'long'] mixes several types in one field; field 'maybe' imported as json
warning[degraded_to_json] #/fields/3/type: type 'null' on its own has no data type; field 'nothing' imported as json
warning[degraded_to_json] #/fields/4/type: an empty union has no data type; field 'never' imported as json
```

It only forgives a field. A file that is not valid Avro, a field name that is not valid and a
root that cannot be imported stay errors.

## Warnings

The only warning that an Avro import gives is `degraded_to_json`, under `--lenient`, in the
format [the import guide](import.md#warnings) describes. `additional_properties_ignored` and
`undeclared_required` are about JSON Schema: Avro has no way to close a record or to require a
field that is not declared.

## Errors

An error is printed as an `error:` block on standard error and exits with status `1`, as in the
[import guide](import.md#errors), where `file_not_found`, `io_error` and `output_exists` are
explained. The codes of an Avro import are:

| code | meaning |
|------|---------|
| `invalid_json` | `FILE` is not JSON. Also: a key that appears twice in one object, `NaN` and `Infinity`, and a document nested too deeply. |
| `invalid_avro_schema` | `FILE` is JSON, but not a well-formed Avro schema: a type with no name or a name defined twice, a union inside a union, a name that nothing defines, an array without `items`, a field twice, `fields` that is not a list. |
| `unsupported_avro_schema` | `FILE` is valid, but strict mode cannot import it: a union of several types, `null` on its own, a field name RippleRack cannot use. Also what has no record to import: a root that is not a record, several records and no `--select`, a `--select` that names none, a record with no fields. |

When an error has problems of both kinds, its code is `invalid_avro_schema`.

## In CI

When the team that produces the data owns an Avro schema, it can be the source of truth for the
schema RippleRack checks. Import it, then ask what the new version would break:

```bash
ripplerack import schemas/orders.avsc --from avro --version 2.0.0 -o /tmp/orders.yaml
ripplerack impact datacenter.yaml --pipeline orders-ingest --schema /tmp/orders.yaml --fail-on-breaking
```

The first command exits with `1` when the schema cannot be imported and the second with `2`
when a consumer breaks, so either stops a pull request. If the file defines many records, name
the one the pipeline produces with `--select`. Use strict mode there, so that a field the
importer cannot represent is not turned into a `json` field without anyone reading the warning.
