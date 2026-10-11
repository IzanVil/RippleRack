# Output formats

RippleRack prints human-friendly tables by default. For CI and other tooling, the
commands below can emit **JSON** instead. This page is the reference for that JSON:
its conventions, its stability guarantees, the error documents and the exit codes.

| command                               | JSON                        |
|---------------------------------------|-----------------------------|
| `ripplerack impact ... --format json` | [impact document](#impact)  |
| `ripplerack graph ... -F json`        | [graph export](#graph-json-export) |

## Conventions

These rules apply to **every** JSON document RippleRack produces.

1. **Keys are camelCase**, always: `schemaVersion`, `brokenConsumers`,
   `dataSchemaVersion`. There is no mixed style. A test walks every document and
   fails on any other spelling.
2. **Enumerated values are lowercase**: single words (`critical`, `major`,
   `pipeline`) or snake_case (`field_removed`, `at_risk`, `file_not_found`).
   Values that *name something from your YAML file*, such as a field or component
   id, keep the exact spelling used in the file.
3. **Every document has an envelope** (below), so a consumer can identify what it
   is reading and which contract it follows.
4. **Output is deterministic.** Equal inputs produce byte-identical output: lists
   have a documented order, objects have a fixed key order, the text is indented
   with two spaces, is pure ASCII (non-ASCII characters are escaped as `\uXXXX`)
   and ends with a newline.
5. **`message` fields are for humans.** Their wording can change at any time. Branch
   on `code`, `kind`, `level`, `severity` and `status`, never on `message`.
6. **`null` means "not applicable"**, for example `field` on a change that is not
   tied to a single field.

### Envelope

| key             | type    | description |
|-----------------|---------|-------------|
| `schemaVersion` | integer | Version of **this JSON contract** (currently `1`). Not the version of any data schema. |
| `tool`          | object  | `{"name": "ripplerack", "version": "<release>"}` |
| `command`       | string  | The command that produced the document: `impact`. |

### Stability policy

`schemaVersion` only changes when the contract changes in a way that can break a
consumer:

* **Does not bump it:** adding a key to an object, adding a new `error.code`,
  adding a new `changes[].kind`. Consumers must **ignore unknown keys** and treat
  unknown codes and kinds generically.
* **Bumps it:** removing or renaming a key, changing a type or the meaning of a
  value, changing the order guarantees, or adding a value to a *closed*
  enumeration (`severity`, `level`, `status`, node `kind`).

The `version` inside `tool` changes with every release and carries no contract
meaning.

> Data schema versions are always called `version`, `oldVersion`, `newVersion`,
> `suggestedVersion` or `dataSchemaVersion`. The name `schemaVersion` is reserved for the
> contract version in the envelope. The next section explains the difference.

## `schemaVersion` and `dataSchemaVersion`

Two version numbers in the output have similar names but version different things. They
are set by different parties, change for different reasons and never influence each other.

| | `schemaVersion` | `dataSchemaVersion` |
|---|---|---|
| **What it versions** | The JSON contract: the shape of the documents RippleRack prints (keys, types, what the values mean, ordering). | Your data: the version of the schema that a pipeline produces. |
| **Who sets it** | RippleRack. It is fixed by the release you run. | You, as `schema.version` of the pipeline in the datacenter file. RippleRack only reads and reports it. |
| **Format** | Integer: `1`. | String `MAJOR.MINOR.PATCH`: `"1.2.0"`. |
| **Where it appears** | At the root of every [envelope](#envelope) document. | On pipeline nodes of the [graph export](#graph-json-export). |
| **Goes up when** | RippleRack changes the JSON contract in a way that can break a consumer (see the [stability policy](#stability-policy)). | You change what a pipeline produces and bump its version. The [SemVer rules](concepts.md#schema-semver-rules) say how far: patch, minor or major. |
| **Does not change when** | Your datacenter or your schemas change, or RippleRack only adds a key or an error code. | RippleRack's JSON contract changes. |

The impact document reports data versions too, under other names: `schema.oldVersion`,
`schema.newVersion` and `schema.suggestedVersion`. They are data versions, not contract
versions. A third number, `tool.version`, is the release of RippleRack itself; it changes
with every release and has no contract meaning.

### They are independent

| What happens | `schemaVersion` | Data versions |
|---|---|---|
| You rename a field and bump the pipeline from `1.2.0` to `2.0.0` | stays `1` | `dataSchemaVersion` is `"2.0.0"` once the file is updated; an impact run reports `oldVersion` `1.2.0` and `newVersion` `2.0.0` |
| You propose a schema that removes a field but still declares `1.2.1` | stays `1` | `newVersion` is `1.2.1`, as declared; `versionConsistent` is `false` and `suggestedVersion` is `2.0.0` |
| You upgrade RippleRack to a release that only adds keys or error codes | stays `1` | unchanged |
| A release renames or removes a key, or changes what a value means | becomes `2` | unchanged: they still come from your file |

The names never overlap either: `schemaVersion` appears only at the root of a document and
`dataSchemaVersion` only on graph nodes, and the test suite checks all of this
(`tests/test_versions.py`).

### Reading them in a script

```bash
# Refuse a JSON contract this script was not written for
jq -e '.schemaVersion == 1' impact.json > /dev/null || { echo "unsupported contract" >&2; exit 1; }

# The data versions: before, after, and the version the change requires
jq -r '.schema | "\(.oldVersion) -> \(.newVersion) (required: \(.suggestedVersion))"' impact.json

# The version of the schema each pipeline produces today
ripplerack graph dc.yaml -F json | jq -r '.nodes[] | select(.kind == "pipeline") | "\(.id) \(.dataSchemaVersion)"'
```

## Impact

`ripplerack impact FILE --pipeline ID --schema NEW_SCHEMA --format json`

```json
{
  "schemaVersion": 1,
  "tool": { "name": "ripplerack", "version": "0.1.0" },
  "command": "impact",
  "datacenter": "mini-datacenter",
  "pipeline": "orders-ingest",
  "severity": "critical",
  "schema": {
    "name": "orders",
    "oldVersion": "1.2.0",
    "newVersion": "2.0.0",
    "level": "major",
    "suggestedVersion": "2.0.0",
    "versionConsistent": true,
    "changes": [
      {
        "kind": "field_removed",
        "level": "major",
        "field": "amount",
        "message": "field 'amount' removed",
        "breaksReaders": true
      }
    ]
  },
  "brokenConsumers": [
    {
      "pipeline": "customer-360",
      "fields": ["amount"],
      "changes": [{ "kind": "field_removed", "field": "amount" }]
    }
  ],
  "atRisk": ["api", "dashboard", "revenue-daily"],
  "affected": [
    {
      "id": "customer-360",
      "kind": "pipeline",
      "distance": 1,
      "path": ["orders-ingest", "customer-360"],
      "status": "broken"
    }
  ],
  "summary": { "affected": 5, "broken": 2, "atRisk": 3, "breakingChanges": 2 }
}
```

(Abbreviated; see [`tests/golden/`](../tests/golden) for complete documents.)

### Top-level keys

| key               | type    | description |
|-------------------|---------|-------------|
| `datacenter`      | string  | `name` of the datacenter file. |
| `pipeline`        | string  | The pipeline whose schema changes. |
| `severity`        | string  | Overall severity: `none`, `low`, `medium`, `high` or `critical` (ascending). |
| `schema`          | object  | The schema comparison, below. |
| `brokenConsumers` | array   | Direct consumers that read a field broken by the change. Sorted by `pipeline`. |
| `atRisk`          | array   | Ids of components downstream of a broken consumer. Sorted. |
| `affected`        | array   | Every component reachable from the pipeline. Sorted by `distance`, then `id`. |
| `summary`         | object  | Counts: `affected`, `broken`, `atRisk`, `breakingChanges`. |

How severity is derived is explained in [concepts.md](concepts.md#impact-severity).

### `schema`

| key                 | type    | description |
|---------------------|---------|-------------|
| `name`              | string  | Name of the current schema. |
| `oldVersion`        | string  | Version in the datacenter file. |
| `newVersion`        | string  | Version declared by the new schema. |
| `level`             | string  | Required bump: `none`, `patch`, `minor` or `major`. |
| `suggestedVersion`  | string  | `oldVersion` bumped by `level`. |
| `versionConsistent` | boolean | `false` when `newVersion` is lower than `suggestedVersion`, for example a breaking change shipped as a patch. |
| `changes`           | array   | Sorted by `level` (major first), then `field`, then `kind`. |

Each entry of `changes`:

| key            | type           | description |
|----------------|----------------|-------------|
| `kind`         | string         | `field_added`, `field_removed`, `type_changed`, `nullability_changed`, `description_changed` or `fields_reordered`. |
| `level`        | string         | `patch`, `minor` or `major`. |
| `field`        | string \| null | The field concerned; `null` for `fields_reordered`. |
| `message`      | string         | Human-readable description. |
| `breaksReaders`| boolean        | Whether consumers that read this field break. |

### `brokenConsumers[]` and `affected[]`

| key        | type     | description |
|------------|----------|-------------|
| `pipeline` | string   | The broken consumer. |
| `fields`   | string[] | Fields it reads that the change breaks. Sorted. |
| `changes`  | object[] | `{kind, field}` pairs responsible. |

| key        | type     | description |
|------------|----------|-------------|
| `id`       | string   | Component id. |
| `kind`     | string   | `rack`, `server`, `service` or `pipeline`. |
| `distance` | integer  | Hops from the changed pipeline. |
| `path`     | string[] | Shortest path from the pipeline to this component, both ends included. |
| `status`   | string   | `broken` (a direct consumer that breaks), `at_risk` (downstream of a broken consumer) or `affected` (reachable, but not known to break). |

## Errors

When `--format json` is requested and the command fails, **stdout stays empty**
and stderr receives one JSON document with the same envelope plus an `error`
object:

```json
{
  "schemaVersion": 1,
  "tool": { "name": "ripplerack", "version": "0.1.0" },
  "command": "impact",
  "error": {
    "code": "unknown_pipeline",
    "message": "unknown pipeline 'ghost'"
  }
}
```

| `error.code`        | meaning |
|---------------------|---------|
| `file_not_found`    | An input file does not exist. |
| `io_error`          | A file exists but cannot be read (permissions, invalid UTF-8...). |
| `invalid_yaml`      | A file is not valid YAML. |
| `invalid_document`  | The datacenter file is valid YAML but its top level is not a mapping. |
| `validation_failed` | A datacenter or schema file does not satisfy the model: unknown keys, wrong types, duplicate ids, references to missing components or fields. |
| `dependency_cycle`  | The dependency graph contains a cycle. |
| `unknown_pipeline`  | `--pipeline` names a pipeline that does not exist. |

For file-related codes `error.message` names the offending file, and for
`validation_failed` it lists every problem found.

Two situations are **not** reported as JSON:

* **Usage errors**, such as an unknown `--format` value or a missing required
  option, are rejected by the argument parser before the output format is known.
  They are plain text on stderr and exit with status `2`.
* **Bugs.** An unexpected internal error prints a Python traceback and exits with
  status `1`. Please report it as an issue.

Without `--format json`, errors are a single human-readable line on stderr.

## Exit codes

| code | meaning |
|------|---------|
| `0`  | Success. |
| `1`  | The command failed: unreadable or invalid input, unknown pipeline. |
| `2`  | `--fail-on-breaking` was given and at least one consumer breaks, **or** the command line was invalid. |

Status `2` has two meanings. To tell them apart in a script, look at stdout: with
`--format json` a breaking-change result always leaves a JSON document there,
whereas a usage error leaves it empty.

```bash
ripplerack impact dc.yaml -p orders-ingest -s new.yaml --format json --fail-on-breaking > impact.json
status=$?
if [ "$status" -eq 2 ] && [ -s impact.json ]; then
  jq -r '.brokenConsumers[].pipeline' impact.json   # which consumers break
fi
```

## Graph JSON export

`ripplerack graph FILE -F json` prints the dependency graph. It predates the
envelope, so it has **no** `schemaVersion`, and it follows the same key style:

```json
{
  "name": "mini-datacenter",
  "nodes": [
    { "id": "kafka", "kind": "service" },
    { "id": "orders-ingest", "kind": "pipeline", "dataSchemaVersion": "1.2.0" }
  ],
  "edges": [
    { "source": "kafka", "target": "orders-ingest", "relation": "runs" }
  ]
}
```

* `nodes[].kind` is `rack`, `server`, `service` or `pipeline`; only pipelines have
  `dataSchemaVersion`, the version of the schema they produce. It is a data version, not
  the contract version: see [`schemaVersion` and `dataSchemaVersion`](#schemaversion-and-dataschemaversion).
* `edges[].relation` is `hosts`, `runs`, `feeds`, `runtime`, `data` or `network`.
  Edges point in the direction an impact propagates.
* Attribute values are strings.
