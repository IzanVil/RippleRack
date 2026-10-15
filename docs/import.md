# Importing schemas

`ripplerack import` reads a schema written in another format and writes it as the YAML that
RippleRack reads, so nobody has to type it by hand. Today it reads **JSON Schema**; Avro and
SQL DDL are planned.

```bash
ripplerack import orders.schema.json --from json-schema > orders.yaml
```

The result is a *schema file*: `name`, `version` and `fields`, the same shape as the files in
[`examples/changes/`](../examples/changes). `ripplerack impact --schema` reads it as it is, and
under a pipeline's `schema:` key in a [datacenter file](yaml-format.md) it says what that
pipeline produces.

## Known limitations

A RippleRack schema is a flat list of fields, each with one of seven types and a `nullable`
flag. A JSON Schema can say much more, so some of it cannot be carried over. Three limits are
worth knowing before you rely on an imported schema:

1. **Enum values are not modelled structurally.** The allowed values are written into the
   field's `description` (`One of: pending, paid`). A change in the values of an enum is
   therefore seen as a change of description, which is a *patch*, even though in practice it
   can break consumers that assume a closed set of values.
2. **Nested objects and arrays are mapped to `json`.** Each one is a single field and RippleRack
   does not look inside it. A change *inside* a nested object or array, such as removing
   `address.street`, is not detected. Removing `address` itself is.
3. **A JSON Schema without `required` produces all fields nullable.** In a RippleRack schema
   `nullable` is the only way to say that a field is optional (see
   [Schema fields](yaml-format.md#schema-fields)), so every property that `required` does not
   list becomes `nullable: true`. Many schemas leave `required` out, and then every imported
   field is optional.

What the importer cannot represent, and what changes which fields exist, what type they have or
whether they are optional, is an error or a [warning](#warnings). Value constraints such as
`minimum` or `pattern` are ignored; see [the keywords it reads](#the-keywords-it-reads).

## Using it

```text
ripplerack import FILE --from json-schema [-o OUT] [--name NAME] [--version X.Y.Z] [--lenient] [--force]
```

| option | meaning |
|--------|---------|
| `FILE` | The file to import. `-` reads standard input. It is read as UTF-8; a byte order mark is accepted. |
| `--from` | The format of `FILE`. Required: the format is never guessed. Today: `json-schema`. |
| `-o`, `--output` | Write the schema to this file instead of standard output. `-o -` is standard output. |
| `--name` | The name of the schema. Letters, digits, `_`, `.` and `-` only. See [the name](#the-name-and-the-version). |
| `--version` | The version to give the schema, `MAJOR.MINOR.PATCH`. Default: `1.0.0`. |
| `--lenient` | Import what has no equivalent as `json` fields, with a warning, instead of failing. See [strict and lenient](#strict-and-lenient). |
| `--force` | Overwrite the output file if it exists. |

### An example

[`examples/schemas/orders_v2.schema.json`](../examples/schemas/orders_v2.schema.json) is a JSON
Schema written the way one is in practice: an `$id` and a `title`, a definition used through
`$ref`, a nullable union, a `required` list and value constraints.

```bash
ripplerack import examples/schemas/orders_v2.schema.json --from json-schema --version 2.0.0
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

This is exactly [`examples/changes/orders_v2.yaml`](../examples/changes/orders_v2.yaml), so it
can go straight into `impact`. In a shell that has process substitution, no file is needed:

```bash
ripplerack impact examples/mini_datacenter.yaml --pipeline orders-ingest \
  --schema <(ripplerack import examples/schemas/orders_v2.schema.json --from json-schema --version 2.0.0)
```

The report is the same `critical` one as in the [quick tour](../README.md#impact-what-breaks-if-this-schema-changes).
Give `--version` the version you intend to publish: the default, `1.0.0`, is that of a new
schema, and `impact` warns when the declared version is lower than the change requires.

### The name and the version

The name is the first of these that gives something usable:

| source | example | name |
|--------|---------|------|
| `--name` | `--name orders_v2` | `orders_v2` |
| the root `title` | `"title": "Order Event"` | `order_event` |
| the last part of the root `$id` | `"$id": "https://example.com/schemas/orders.schema.json"` | `orders` |
| the file name | `customer-events.json` | `customer_events` |
| nothing else | standard input without a title or `$id` | `schema` |

`--name` is used as given. The others are made into a valid name: lowercase, accents removed,
every run of characters other than letters and digits turned into `_`, and the `.json` and
`.schema` endings of a file name or `$id` dropped.

A JSON Schema has no version, so none is guessed: it is `--version`, or `1.0.0`.

### Writing the result

The YAML goes to standard output, or to the file given with `-o`, after which one line says
what was written. **An existing output file is not overwritten** unless `--force` is given, and
the input file is never overwritten: the output is not a datacenter, and `-o datacenter.yaml`
would destroy one. Warnings go to standard error, one per line, so they never mix with the
YAML. The output is deterministic: the same schema always gives the same bytes.

| exit code | meaning |
|-----------|---------|
| `0` | The schema was imported, with or without warnings. |
| `1` | The import failed: an unreadable file, invalid JSON or JSON Schema, something unsupported in strict mode, an output file that exists. |
| `2` | The command line is wrong: a missing `--from`, an unknown format, an invalid `--name` or `--version`. |

## Translation

Each property of the root object becomes a field, in the order of the file. This table shows
how one property is read. Its schema is the first column; whether `required` lists the property
is the second. The rest is the field that comes out.

| Property schema | In `required` | `type` | `nullable` | `description` |
|-----------------|---------------|--------|------------|---------------|
| `{"type": "string"}` | yes | `string` | `false` | — |
| `{"type": "string"}` | no | `string` | `true` | — |
| `{"type": "string", "format": "date-time"}` | yes | `timestamp` | `false` | — |
| `{"type": "string", "format": "date"}` | yes | `date` | `false` | — |
| `{"type": "string", "format": "uuid"}` | yes | `string` | `false` | — |
| `{"type": "integer"}` | yes | `integer` | `false` | — |
| `{"type": "number"}` | yes | `float` | `false` | — |
| `{"type": "boolean"}` | yes | `boolean` | `false` | — |
| `{"type": "object", "properties": {"street": {"type": "string"}}}` | yes | `json` | `false` | — |
| `{"type": "array", "items": {"type": "string"}}` | yes | `json` | `false` | — |
| `{}` | yes | `json` | `false` | — |
| `{"type": ["string", "null"]}` | yes | `string` | `true` | — |
| `{"anyOf": [{"type": "integer"}, {"type": "null"}]}` | yes | `integer` | `true` | — |
| `{"type": "string", "nullable": true}` | yes | `string` | `true` | — |
| `{"enum": ["pending", "paid"]}` | yes | `string` | `false` | `One of: pending, paid` |
| `{"type": "integer", "enum": [1, 2, 3]}` | yes | `integer` | `false` | `One of: 1, 2, 3` |
| `{"const": "EUR"}` | yes | `string` | `false` | `Always: EUR` |
| `{"type": "string", "description": "Customer name"}` | yes | `string` | `false` | `Customer name` |
| `{"type": "string", "title": "Customer name"}` | yes | `string` | `false` | — |
| `{"type": "string", "description": "Status", "enum": ["new", "done"]}` | yes | `string` | `false` | `Status. One of: new, done` |
| `{"type": "string", "minLength": 1, "pattern": "^a"}` | yes | `string` | `false` | — |

In words:

* **Nullable.** A field is `nullable` when `required` does not list it, or when its schema
  allows `null`: `null` in `type`, an `anyOf` or `oneOf` of one schema and `{"type": "null"}`,
  `null` among the values of an `enum`, or the OpenAPI extension `nullable: true`.
* **Types.** `number` is `float`. Only the string formats `date-time` and `date` change the type;
  any other format (`uuid`, `email`, `uri`...) is still a `string`. A schema with no `type` takes
  the type of the values of its `enum` or `const`, or `json` when they are of several kinds.
* **`json` is for everything with structure.** Objects, arrays and schemas that say nothing
  about their type are `json` fields, and nested objects are not flattened (see the
  [limitations](#known-limitations)).
* **Descriptions.** `description` is used, with whitespace reduced to single spaces so that it fits
  on one line. A property without one gives a field without one: its `title` is ignored, because it
  mostly repeats the name. Enum values are added after the description: up to ten, then a count
  (`One of: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, … (25 values)`). `null` is not listed, because
  `nullable` carries it.
* **Names.** A property name that is not a valid field name (letters, digits, `_`, `.` and `-`:
  no spaces, accents or `@`) is an error. It is never renamed or skipped, because either would
  change the contract without anyone noticing.
* **Properties that cannot exist.** A property whose schema is `false` is not a field.

### References and composition

| Construct | Default (strict) | With `--lenient` |
|-----------|------------------|------------------|
| `$ref` inside the document: `#/$defs/Name`, `#/definitions/Name`, any JSON pointer | Followed. Keywords next to the `$ref` win over the target's. | the same |
| `$ref` to another file or a URL, an `$anchor`, a `$dynamicRef` or `$recursiveRef`, a reference that refers back to itself | error | `json` field + warning |
| `$ref` that points to nothing | error | error |
| `allOf` with one member, the usual way to add text to a `$ref` | Merged. | the same |
| `allOf` with several members at the root | The objects are merged: their properties and `required` lists are joined, and fields from what is extended come first. A property declared differently by two members is an error. | the same |
| `allOf` with several members on a field | error | `json` field + warning |
| `oneOf` or `anyOf` of one schema and `{"type": "null"}` | A nullable field of that schema's type. | the same |
| any other `oneOf` or `anyOf` | error | `json` field + warning |
| `type` with several types besides `null`, or `type: "null"` alone | error | `json` field + warning |
| a name in `required` that `properties` does not declare | error | a required `json` field + warning |
| `oneOf`, `anyOf`, `then`, `else` or `dependentSchemas` on the root that declare properties the schema does not | error | error |
| a root that is not an object schema, or declares no properties | error | error |
| a property name that is not a valid field name | error | error |

Alternatives on the root that only constrain properties the schema declares, such as
`oneOf: [{"required": ["a"]}, {"required": ["b"]}]` or an `if`/`then` that requires a
field, change nothing and are ignored like any constraint. Alternatives that declare *other*
properties are refused, because those fields would be lost: a schema that is a family of
variants cannot be imported as one schema yet.

References are never fetched: the importer reads one file and touches nothing else.

### The keywords it reads

`$id` and `title` on the root, where they name the schema, and `description`, `type`, `format`,
`enum`, `const`, `nullable`, `properties`, `required`, `$ref`, `allOf`, `oneOf`, `anyOf`,
`additionalProperties` and `unevaluatedProperties`. When one has a value of the wrong shape, such
as a `required` that is not a list of strings or an unknown `type`, the import fails with
`invalid_json_schema`.

**Everything else is ignored without a warning**: value constraints (`minimum`, `maxLength`,
`pattern`, `minItems`, `uniqueItems`...), annotations (`default`, `examples`, `deprecated`,
`$comment`...), `not`, `if`/`then`/`else`, `patternProperties`, and keywords of a vendor or of a
later draft. A RippleRack schema is made of types and nullability, and has nowhere to put
them. The exception is `additionalProperties: false` and `unevaluatedProperties: false`, which
get a warning.

## Strict and lenient

By default nothing that decides which fields exist or what type they have is lost without anyone
noticing: if a construct has no equivalent, the import fails and says where. Every problem with a
property is listed at once; a problem with the root of the schema, such as a `required` that is
not a list, stops the import at the first.

```text
error: lenient.schema.json: cannot import this JSON Schema:
  #/properties/choice/oneOf: oneOf with 2 alternatives has no equivalent type
  #/properties/far/$ref: $ref 'https://example.com/other.json#/$defs/thing' points outside this document; only references to this document (#/...) are supported
  #/properties/both/allOf: allOf with 2 members has no equivalent for a field
  #/properties/mixed/type: type ['integer', 'string'] mixes several types in one field
  #/properties/nothing/type: type 'null' on its own has no data type
  #/required: required property 'ghost' is not declared in properties
  hint: --lenient imports properties like these as json fields
```

The places are JSON pointers into the file. `--lenient` imports such properties as `json`
fields, which hold any value, and says so for each one (see [warnings](#warnings)). It only
forgives a property: a broken schema, a root that cannot be imported and a property name that
is not valid stay errors.

## Warnings

A warning means the schema was imported, but not exactly as the source says. Each is one line
on standard error, `warning[code] pointer: message`, and the code is stable.

| code | when | in modes |
|------|------|----------|
| `additional_properties_ignored` | A schema that is read says `additionalProperties: false` or `unevaluatedProperties: false` (the second is what the 2019-09 and later drafts use, notably next to `allOf`): it declares that no other fields exist, which a RippleRack schema cannot say. | strict and lenient |
| `degraded_to_json` | A property has no equivalent type and was imported as a `json` field. | `--lenient` only |
| `undeclared_required` | `required` names a property that `properties` does not declare; it was imported as a required `json` field. | `--lenient` only |

```text
warning[additional_properties_ignored] #/additionalProperties: additionalProperties: false is ignored; a RippleRack schema cannot say that no other fields exist
warning[additional_properties_ignored] #/$defs/Customer/unevaluatedProperties: unevaluatedProperties: false is ignored; a RippleRack schema cannot say that no other fields exist
warning[degraded_to_json] #/properties/choice/oneOf: oneOf with 2 alternatives has no equivalent type; field 'choice' imported as json
```

`additional_properties_ignored` is given, for each of the two keywords, for every schema the
importer reads: the root, the members of an `allOf`, the target of a `$ref` and the schema of each
property. It is not given for definitions that nothing refers to, nor for what is inside a
property that becomes a `json` field, since that is not read. The imported schema is the same with
or without it; the warning only tells you what the source said and the result does not.

## Errors

An error is printed as an `error:` block on standard error and exits with status `1`. Its code
is a stable identifier, `RippleRackError.code` in `ripplerack.parser`; the codes are listed
with the others in [output-formats.md](output-formats.md#errors). `import` writes YAML and has
no `--format json`, so the code itself is not printed.

| code | meaning |
|------|---------|
| `file_not_found` | `FILE` does not exist. |
| `io_error` | `FILE` cannot be read (permissions, not UTF-8), or the output cannot be written. |
| `invalid_json` | `FILE` is not JSON. Also: a key that appears twice in one object (a parser would keep one and drop the other), `NaN` and `Infinity`, and a document nested too deeply. |
| `invalid_json_schema` | `FILE` is JSON, but a keyword the importer reads has the wrong shape (a `required` that is not a list, an unknown `type`), the root is not a schema, or a `$ref` points to nothing. |
| `unsupported_json_schema` | `FILE` is a well-formed schema that uses something with no equivalent in strict mode, or something that cannot be imported at all, such as a root that is not an object. |
| `output_exists` | The output file exists and `--force` was not given, or it is the input file. |

## In CI

When the team that produces the data owns a JSON Schema, it can be the source of truth for the
schema RippleRack checks. Import it, then ask what the new version would break:

```bash
ripplerack import schemas/orders.schema.json --from json-schema --version 2.0.0 -o /tmp/orders.yaml
ripplerack impact datacenter.yaml --pipeline orders-ingest --schema /tmp/orders.yaml --fail-on-breaking
```

The first command exits with `1` when the schema cannot be imported and the second with `2`
when a consumer breaks, so either stops a pull request. Use strict mode there, so that a
construct the importer cannot represent is not turned into a `json` field without anyone
reading the warning.
