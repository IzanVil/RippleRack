# Output formats

RippleRack prints human-friendly tables by default. For CI and other tooling, the
commands below can emit **JSON** instead. This page is the reference for that JSON:
its conventions, its stability guarantees, the error documents and the exit codes. The
graph can also be drawn as a [Mermaid diagram](#mermaid), with or without the impact of
a change highlighted.

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

> Data schema versions are always called `version`, `oldVersion`, `newVersion` or
> `dataSchemaVersion`. The name `schemaVersion` is reserved for the contract
> version in the envelope.

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
  `dataSchemaVersion`, the version of the schema they produce.
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
