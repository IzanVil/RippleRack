# Output formats

RippleRack prints human-friendly tables by default. For CI and other tooling, the
commands below can emit **JSON** instead. This page is the reference for that JSON:
its conventions, its stability guarantees, the error documents and the exit codes. The
graph can also be drawn as a [Mermaid diagram](#mermaid), with or without the impact of
a change highlighted.

| command                                   | JSON                               |
|-------------------------------------------|------------------------------------|
| `ripplerack impact ... --format json`     | [impact document](#impact)         |
| `ripplerack diff BASE HEAD --format json` | [diff document](#diff)             |
| `ripplerack graph ... -F json`            | [graph export](#graph-json-export) |

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
| `command`       | string  | The command that produced the document: `impact` or `diff`. |

### Stability policy

`schemaVersion` only changes when the contract changes in a way that can break a
consumer:

* **Does not bump it:** adding a key to an object, adding a new `error.code`,
  `warnings[].code` or `changes[].kind`. Consumers must **ignore unknown keys** and
  treat unknown codes and kinds generically.
* **Bumps it:** removing or renaming a key, changing a type or the meaning of a
  value, changing the order guarantees, or adding a value to a *closed*
  enumeration: `severity`, `level`, `status`, component `kind` and dependency `kind`.

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

## Diff

`ripplerack diff BASE HEAD --format json` compares two datacenter files. `BASE` is the
"before" and `HEAD` the "after".

```json
{
  "schemaVersion": 1,
  "tool": { "name": "ripplerack", "version": "0.1.0" },
  "command": "diff",
  "base": { "name": "mini-datacenter" },
  "head": { "name": "mini-datacenter" },
  "severity": "high",
  "summary": {
    "added": 2, "removed": 0, "modified": 3,
    "dependenciesAdded": 1, "dependenciesRemoved": 0, "dependenciesModified": 1,
    "schemaChanges": 1, "brokenConsumers": 1, "warnings": 0
  },
  "metadata": [],
  "components": {
    "added": [{ "id": "redis", "kind": "service", "parent": "srv-b1" }],
    "removed": [],
    "modified": [
      {
        "id": "srv-b1",
        "kind": "server",
        "changes": [{ "attribute": "memory_gb", "before": 96.0, "after": 64.0 }]
      }
    ]
  },
  "dependencies": {
    "added": [{ "source": "api", "target": "redis", "kind": "runtime" }],
    "removed": [],
    "modified": [{ "source": "spark", "target": "kafka", "before": "network", "after": "data" }]
  },
  "schemaChanges": [ { "pipeline": "orders-ingest", "severity": "high", "...": "..." } ],
  "removedWithDependents": [],
  "possibleRenames": [],
  "warnings": []
}
```

(Abbreviated; see [`tests/golden/`](../tests/golden) for complete documents, including
one that exercises every section.)

### Top-level keys

| key                     | type   | description |
|-------------------------|--------|-------------|
| `base`, `head`          | object | `{"name": ...}`: the `name` of each datacenter file. |
| `severity`              | string | Overall severity, `none` to `critical`; see [concepts.md](concepts.md#comparing-two-datacenters). |
| `summary`               | object | Counts of the lists below. `brokenConsumers` counts **distinct** pipelines. |
| `metadata`              | array  | Changes to the datacenter itself: `{attribute, before, after}` for `name` and `description`. |
| `components`            | object | `added`, `removed` and `modified` components. |
| `dependencies`          | object | `added`, `removed` and `modified` explicit dependencies. |
| `schemaChanges`         | array  | One entry per pipeline whose schema **fields** changed, sorted by `pipeline`. |
| `removedWithDependents` | array  | Removed components that something still present in head used to depend on. |
| `possibleRenames`       | array  | Hints: a removed and an added component that are identical apart from their id. |
| `warnings`              | array  | Findings that deserve a reviewer's attention. |

### `components`

Components are matched by `id`; an id that changes is a removal plus an addition.

| list         | entry keys                       | notes |
|--------------|----------------------------------|-------|
| `added`, `removed` | `id`, `kind`, `parent`     | `parent` is `null` for racks, the rack for servers, the server for services and the service a pipeline runs on. |
| `modified`   | `id`, `kind`, `changes`          | `changes` is a list of `{attribute, before, after}`. |

Components are sorted by `kind` (rack, server, service, pipeline), then `id`. The
attributes that are compared:

| kind     | `attribute` values |
|----------|--------------------|
| rack     | `power_capacity_kw` |
| server   | `rack`, `cpu_cores`, `memory_gb`, `power_kw` |
| service  | `server`, `cpu_cores`, `memory_gb`, `description` |
| pipeline | `runs_on`, `inputs`, `schema.name`, `schema.version`, `schema.fields` |

`attribute` names a YAML key exactly as written in the file, except `rack` and `server`
(the parent in the nested layout, so moving a server between racks is a
modification) and the dotted `schema.*` paths. `before` and `after` are numbers or
strings, with two exceptions:

* `inputs` is a list of `{pipeline, fields}` sorted by `pipeline`; `fields` is a sorted
  list of field names, or `null` when the consumer reads every field.
* `schema.fields` is a list of `{name, type, nullable, description}` in declaration
  order. The field-by-field analysis is in `schemaChanges`.

The order in which things are listed in the YAML files never matters.

### `dependencies`

`added` and `removed` hold `{source, target, kind}`; `modified` holds
`{source, target, before, after}` where `before` and `after` are the dependency kinds
(`runtime`, `data` or `network`). A dependency is identified by `(source, target)`.
Lists are sorted by `source`, then `target`.

### `schemaChanges`, `removedWithDependents`, `possibleRenames`, `warnings`

* **`schemaChanges[]`** has the same shape as an [impact document](#impact) without the
  envelope and `datacenter` keys: `pipeline`, `severity`, `schema`, `brokenConsumers`,
  `atRisk`, `affected`, `summary`. Impact is evaluated against the **head** datacenter:
  a consumer is broken when, in head, it still reads a field that the change breaks.
  A consumer that was adapted in the same change is fine, and a consumer that only
  exists in head is never reported.
* **`removedWithDependents[]`** is `{id, kind, dependents}`, ordered like `components`.
  `dependents` lists the *direct* dependents that still exist in head, sorted.
  Components removed together with everything that depended on them do not appear.
* **`possibleRenames[]`** is `{kind, from, to}`, ordered by `kind` (rack, server,
  service, pipeline), then `from`. Only unambiguous one-to-one matches are reported, and
  the comparison still treats them as a removal plus an addition.
* **`warnings[]`** is `{code, message}`:

  | `code`                    | meaning |
  |---------------------------|---------|
  | `datacenter_name_changed` | The two files have different `name`s. Are you comparing different datacenters? |
  | `component_kind_changed`  | An id exists in both files but as a different kind of component. |
  | `schema_version_too_low`  | A pipeline's declared schema version is lower than the change requires (or went backwards). |

  Warnings come in this order: name, then kind changes by `id`, then versions by
  `pipeline`. New codes may be added without bumping `schemaVersion`.

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
`validation_failed` it lists every problem found. `diff` reads two files, so its
message tells you whether `BASE` or `HEAD` was the problem. `unknown_pipeline` only
applies to `impact`.

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
| `2`  | `--fail-on-breaking` was given and at least one consumer breaks (for `diff`: `summary.brokenConsumers` is greater than zero), **or** the command line was invalid. |

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

## Mermaid

`ripplerack graph FILE -F mermaid` and `ripplerack impact ... -F mermaid` print a
[Mermaid](https://mermaid.js.org) `flowchart LR` as plain text. It is meant to be read by
people, so unlike the JSON documents it has no envelope and no `schemaVersion`. Output
is deterministic and ends with a newline. Errors are reported as plain text, as with
`--format text`, and the exit codes are the same as for `impact`.

### Reading the diagram

| element  | drawn as |
|----------|----------|
| rack     | the outermost box (a `subgraph`) |
| server   | a box inside its rack |
| service  | a rounded node inside its server |
| pipeline | a hexagon in the `pipelines` group, labelled with the version of its schema |
| arrow    | from a provider to what depends on it, the direction an impact travels, labelled `runs`, `feeds`, `runtime`, `data` or `network` |

Hosting is expressed by nesting, so there are no `hosts` arrows. A rack without servers or
a server without services is drawn as a plain node instead of an empty box. The label of
every node is the original id from your file.

### Impact highlight

With `impact -F mermaid` each node that the change reaches gets one of these classes, the
same statuses as `affected[].status` in the [impact document](#impact):

| class      | meaning | colour |
|------------|---------|--------|
| `changed`  | the pipeline whose schema changes | purple, thick border |
| `broken`   | a direct consumer that breaks | red |
| `atRisk`   | downstream of a broken consumer | orange |
| `affected` | reachable, but not known to break | yellow |

Arrows along the shortest impact paths are coloured by the status of the node they lead
to. A comment line states the severity: `%% impact of changing orders-ingest: critical`.
Components the change does not reach keep the colour of their kind.

### Using the output

````bash
# Markdown that GitHub renders as a diagram
{ echo '```mermaid'; ripplerack graph dc.yaml -F mermaid; echo '```'; } > graph.md

# An SVG with the Mermaid command line tool
ripplerack impact dc.yaml -p orders-ingest -s new.yaml -F mermaid > impact.mmd
mmdc -i impact.mmd -o impact.svg
````

### Notes

* **Diagram ids are generated.** Component ids such as `end`, `graph` or `a.b` are valid in
  a datacenter file but would break Mermaid, so nodes are named `rack_...`, `srv_...`,
  `svc_...` and `pl_...` after their sanitized id (with a numeric suffix if two ids
  collapse to the same text). Treat these ids as an implementation detail.
* **No statement ends with `;`.** Mermaid reads `#`, word characters and `;` as an HTML
  entity, so `fill:#f00;` would be corrupted.
* **Validation.** RippleRack has no Mermaid dependency, so its tests check the structure of
  the output (balanced boxes, declared ids, one class per node, valid arrow indexes) and
  compare it with the golden files in [`tests/golden/`](../tests/golden). Those files
  were also accepted by the Mermaid 11 parser, but the project does not check rendering.
