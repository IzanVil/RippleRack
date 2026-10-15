# RippleRack

**See the ripple before you make the splash.**

[![CI](https://github.com/IzanVil/RippleRack/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/IzanVil/RippleRack/actions/workflows/ci.yml)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/dynamic/toml?url=https%3A%2F%2Fraw.githubusercontent.com%2FIzanVil%2FRippleRack%2Fmain%2Fpyproject.toml&query=%24.project.version&label=version)](CHANGELOG.md)

RippleRack is a local-first simulator for datacenters and data pipelines. You
describe your racks, servers, services and pipelines in a single YAML file and
RippleRack tells you what happens when something changes:

- 🧬 **Semantic versioning for data**: diff two versions of a schema and get
  `patch` / `minor` / `major`, the full list of changes and the version you
  should have declared.
- 🌊 **Cascading impact analysis**: walk the dependency graph to find every
  downstream pipeline, service and dashboard, which consumers actually break
  and how severe the whole change is. Compare two versions of a whole
  datacenter file to review a change before you merge it.
- 🏗️ **Infrastructure simulation**: push the load up, take a server down and
  see what overloads and what goes offline with it.

Everything runs locally from a text file. There are no agents, no cloud
accounts and no databases.

> Status: **alpha**. The CLI and the engines work and are tested. The file format and the
> JSON output may still change before 1.0; JSON changes bump `schemaVersion` and are listed in
> the [changelog](CHANGELOG.md).

## In 10 seconds

From a checkout (see [Installation](#installation)):

```bash
# What breaks if orders-ingest renames `amount` to `amount_cents`?
uv run ripplerack impact examples/mini_datacenter.yaml -p orders-ingest \
  -s examples/changes/orders_v2.yaml --format json \
  | jq -c '{severity, broken: [.brokenConsumers[].pipeline]}'
# {"severity":"critical","broken":["customer-360","orders-enriched"]}

# Gate a pull request on a change to the whole datacenter (exit code 2 if a consumer breaks)
uv run ripplerack diff examples/mini_datacenter.yaml examples/mini_datacenter_v2.yaml --fail-on-breaking
```

## Why?

Infrastructure tools model machines. Data catalogs model tables. Schema
registries model compatibility. In real life a renamed column on a Kafka topic
breaks a Spark job, which empties a dashboard, which pages someone at 3 AM.
RippleRack puts all of that in **one graph**, so the question *"what breaks if I
ship this?"* has a concrete answer. You can run it before merging, inside CI,
or just to learn how these systems fit together.

## Installation

RippleRack requires Python 3.11+ and uses [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/IzanVil/RippleRack.git
cd RippleRack
uv sync
uv run ripplerack --help
```

To install the CLI globally from a checkout:

```bash
uv tool install .
ripplerack --help
```

## Documentation

| Guide | What you will find |
|-------|--------------------|
| [Datacenter file format](docs/yaml-format.md) | The YAML you write and the validation rules |
| [Concepts](docs/concepts.md) | The impact graph, the schema SemVer rules, severity, `diff` and `simulate` |
| [Output formats](docs/output-formats.md) | The JSON documents, error codes, exit codes and Mermaid diagrams |
| [Importing schemas](docs/import.md) | `ripplerack import`: turn a JSON Schema into a schema file, the translation rules, warnings and known limitations |
| [Changelog](CHANGELOG.md) | What changed in each version |
| [Contributing](CONTRIBUTING.md) | Setup, checks and conventions |

## Quick tour

The repository ships with [`examples/mini_datacenter.yaml`](examples/mini_datacenter.yaml):
2 racks, 3 servers, 5 services and 4 pipelines forming an order analytics
stack.

### `validate`: check the file

```bash
uv run ripplerack validate examples/mini_datacenter.yaml
```

This checks types, unique ids, references between components, the fields that
consumers read and dependency cycles. Typos in keys are reported instead of
being silently ignored.

### `graph`: look at the dependency graph

```bash
uv run ripplerack graph examples/mini_datacenter.yaml            # tree in the terminal
uv run ripplerack graph examples/mini_datacenter.yaml -F dot -o dc.dot   # Graphviz
uv run ripplerack graph examples/mini_datacenter.yaml -F json    # machine readable
uv run ripplerack graph examples/mini_datacenter.yaml -F mermaid # Mermaid flowchart
```

`-F mermaid` prints a [Mermaid](https://mermaid.js.org) flowchart: racks and servers are
nested boxes, services and pipelines have their own shapes, and arrows are labelled with
the relation. Paste it between `mermaid` code fences in any Markdown file (GitHub renders
it) or save it with `-o graph.mmd` and render it with `mmdc`.

### `impact`: what breaks if this schema changes?

```bash
uv run ripplerack impact examples/mini_datacenter.yaml \
  --pipeline orders-ingest \
  --schema examples/changes/orders_v2.yaml
```

```text
─────────────────────── Impact of changing orders-ingest ───────────────────────
Schema orders 1.2.0 → 2.0.0   change: major   suggested version: 2.0.0
Schema changes
┏━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ level ┃ kind          ┃ detail                              ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ major │ field_removed │ field 'amount' removed              │
│ major │ field_added   │ required field 'amount_cents' added │
└───────┴───────────────┴─────────────────────────────────────┘
Broken consumers
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ pipeline        ┃ fields ┃ reason                 ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ orders-enriched │ amount │ field 'amount' removed │
│ customer-360    │ amount │ field 'amount' removed │
└─────────────────┴────────┴────────────────────────┘
Downstream components
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ component         ┃ kind     ┃ hops ┃ path                                                        ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ✗ customer-360    │ pipeline │    1 │ orders-ingest → customer-360                                │
│ ✗ orders-enriched │ pipeline │    1 │ orders-ingest → orders-enriched                             │
│ ! api             │ service  │    2 │ orders-ingest → customer-360 → api                          │
│ ! revenue-daily   │ pipeline │    2 │ orders-ingest → orders-enriched → revenue-daily             │
│ ! dashboard       │ service  │    3 │ orders-ingest → orders-enriched → revenue-daily → dashboard │
└───────────────────┴──────────┴──────┴─────────────────────────────────────────────────────────────┘
Severity:  CRITICAL
```

Try the other examples in [`examples/changes/`](examples/changes):

| file | what it shows | severity |
|------|---------------|----------|
| `orders_v1_3_0.yaml` | optional field added | `low` |
| `orders_sneaky_patch.yaml` | field dropped but shipped as a *patch*: RippleRack warns that the version is too low | `high` |
| `orders_v2.yaml` | field renamed with a type change, so the break cascades | `critical` |

Add `--fail-on-breaking` to exit with code `2` whenever a consumer breaks. You
can use it as a gate in CI.

#### Diagram of the impact

`--format mermaid` draws the whole graph with the impact highlighted: the changed pipeline
(purple), the consumers that break (red), everything downstream of them that is at risk
(orange), and the arrows along the way. This is the `orders_v2.yaml` change from above:

```mermaid
flowchart LR
  %% mini-datacenter
  %% impact of changing orders-ingest: critical
  subgraph rack_rack_a["rack-a"]
    subgraph srv_srv_a1["srv-a1"]
      svc_postgres("postgres")
      svc_kafka("kafka")
    end
    subgraph srv_srv_a2["srv-a2"]
      svc_spark("spark")
    end
  end
  subgraph rack_rack_b["rack-b"]
    subgraph srv_srv_b1["srv-b1"]
      svc_api("api")
      svc_dashboard("dashboard")
    end
  end
  subgraph grp_pipelines["pipelines"]
    pl_orders_ingest{{"orders-ingest<br/>schema 1.2.0"}}
    pl_orders_enriched{{"orders-enriched<br/>schema 1.0.0"}}
    pl_revenue_daily{{"revenue-daily<br/>schema 2.1.0"}}
    pl_customer_360{{"customer-360<br/>schema 0.4.0"}}
  end
  svc_postgres -->|runs| pl_customer_360
  svc_postgres -->|runtime| svc_api
  svc_kafka -->|runs| pl_orders_ingest
  svc_kafka -->|network| svc_spark
  svc_spark -->|runs| pl_orders_enriched
  svc_spark -->|runs| pl_revenue_daily
  pl_orders_ingest -->|feeds| pl_orders_enriched
  pl_orders_ingest -->|feeds| pl_customer_360
  pl_orders_enriched -->|feeds| pl_revenue_daily
  pl_revenue_daily -->|data| svc_dashboard
  pl_customer_360 -->|data| svc_api
  classDef service fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
  class svc_postgres,svc_kafka,svc_spark service
  classDef changed fill:#ede7f6,stroke:#4527a0,stroke-width:4px,color:#311b92
  class pl_orders_ingest changed
  classDef broken fill:#ffcdd2,stroke:#c62828,stroke-width:3px,color:#b71c1c
  class pl_orders_enriched,pl_customer_360 broken
  classDef atRisk fill:#ffe0b2,stroke:#ef6c00,stroke-width:2px,color:#e65100
  class svc_api,svc_dashboard,pl_revenue_daily atRisk
  style srv_srv_a1 fill:#e8eaf6,stroke:#283593,color:#1a237e
  style srv_srv_a2 fill:#e8eaf6,stroke:#283593,color:#1a237e
  style rack_rack_a fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c
  style srv_srv_b1 fill:#e8eaf6,stroke:#283593,color:#1a237e
  style rack_rack_b fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c
  linkStyle 6,7 stroke:#c62828,stroke-width:3px
  linkStyle 8,9,10 stroke:#ef6c00,stroke-width:3px
```

#### JSON output for CI

`--format json` (`-F json`) prints a stable, versioned JSON document instead of
tables, ready for `jq` or any CI tooling:

```bash
uv run ripplerack impact examples/mini_datacenter.yaml -p orders-ingest \
  -s examples/changes/orders_v2.yaml --format json \
  | jq -c '{severity, broken: [.brokenConsumers[].pipeline]}'
```

```json
{"severity":"critical","broken":["customer-360","orders-enriched"]}
```

Every document starts with an envelope (`schemaVersion`, `tool`, `command`) and
all keys are camelCase. If the command fails, stdout stays empty and stderr gets a
JSON error with a stable `error.code`, such as `file_not_found` or
`unknown_pipeline`. The full contract, the error codes and the exit codes are
documented in [`docs/output-formats.md`](docs/output-formats.md).

### `diff`: what does this change do to my datacenter?

```bash
uv run ripplerack diff examples/mini_datacenter.yaml examples/mini_datacenter_v2.yaml
```

Compares two datacenter files and reports what was added, removed and modified, which
dependencies changed, and the impact of every schema change on the pipelines that read
it. Components are matched by `id`, so reordering a file is not a change.

```text
──────────── Diff examples/mini_datacenter.yaml → examples/mini_datacenter_v2.yaml ─────────────
mini-datacenter → mini-datacenter
2 added · 0 removed · 3 modified · 1 schema change(s) · 1 broken consumer(s)
Components
┏━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃   ┃ kind     ┃ id              ┃ details                                      ┃
┡━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ + │ service  │ redis           │ on srv-b1                                    │
│ + │ pipeline │ orders-audit    │ runs on postgres                             │
│ ~ │ server   │ srv-b1          │ memory_gb: 96 → 64                           │
│ ~ │ pipeline │ orders-enriched │ inputs: orders-ingest: -amount +amount_cents │
│ ~ │ pipeline │ orders-ingest   │ schema.version: 1.2.0 → 2.0.0                │
│   │          │                 │ schema.fields: changed (see below)           │
└───┴──────────┴─────────────────┴──────────────────────────────────────────────┘
Dependencies
┏━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃   ┃ dependency    ┃ kind           ┃
┡━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ + │ api → redis   │ runtime        │
│ ~ │ spark → kafka │ network → data │
└───┴───────────────┴────────────────┘

orders-ingest
Schema orders 1.2.0 → 2.0.0   change: major   suggested version: 2.0.0
Schema changes
┏━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ level ┃ kind          ┃ detail                              ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ major │ field_removed │ field 'amount' removed              │
│ major │ field_added   │ required field 'amount_cents' added │
└───────┴───────────────┴─────────────────────────────────────┘
Broken consumers
┏━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ pipeline     ┃ fields ┃ reason                 ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ customer-360 │ amount │ field 'amount' removed │
└──────────────┴────────┴────────────────────────┘
At risk: api
Severity:  HIGH
```

Here `orders-enriched` was updated in the same change to read `amount_cents`, so it is
fine. `customer-360` was not touched and reads every field, so it breaks, and `api`,
which depends on it, is at risk. `orders-audit` is new and was written against the new
schema, so it is never reported.

Add `--format json` for the [documented JSON](docs/output-formats.md#diff) or
`--fail-on-breaking` to exit with code `2` when a consumer breaks, which makes the
command a good pull request gate:

```bash
git show main:datacenter.yaml > /tmp/base.yaml
uv run ripplerack diff /tmp/base.yaml datacenter.yaml --fail-on-breaking
```

### `import`: write the schema from a JSON Schema

```bash
uv run ripplerack import examples/schemas/orders_v2.schema.json --from json-schema --version 2.0.0
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

The output is a schema file, so nobody has to write it by hand and it goes straight into
`impact`. This one is exactly `examples/changes/orders_v2.yaml`, so the report is the same
`critical` one as above:

```bash
uv run ripplerack impact examples/mini_datacenter.yaml --pipeline orders-ingest \
  --schema <(uv run ripplerack import examples/schemas/orders_v2.schema.json --from json-schema --version 2.0.0)
```

Properties that `required` lists become required fields and the others become `nullable`;
references inside the file are followed; objects and arrays become `json` fields. What cannot
be represented is an error, or with `--lenient` a `json` field and a warning, and
`additionalProperties: false` is reported as a warning. The
[import guide](docs/import.md) has the translation rules and the
[known limitations](docs/import.md#known-limitations).

### `simulate`: load surges and failures

```bash
uv run ripplerack simulate examples/mini_datacenter.yaml --load 1.5
uv run ripplerack simulate examples/mini_datacenter.yaml --load 1.5 --fail srv-a2
```

`--load` scales every service's CPU/memory demand and every server's power draw.
`--fail` (repeatable) takes a component down along with everything that depends
on it. Each rack and server is then reported as `ok`, `warning` (≥ 80%),
`overloaded` (> 100%) or `failed`.

## How it works

```mermaid
flowchart LR
  yaml[/"datacenter.yaml<br/>(one or two files)"/] --> parse["parse and validate<br/>Pydantic models"]
  parse --> dag["dependency graph<br/>NetworkX"]
  jsonschema[/"JSON Schema"/] -->|"import"| schema
  schema[/"new schema.yaml"/] --> semver["schema SemVer diff<br/>patch, minor, major"]
  dag --> impact["impact<br/>blast radius, broken consumers, severity"]
  semver --> impact
  dag --> diff["diff<br/>added, removed, modified, impact"]
  semver --> diff
  dag --> simulate["simulate<br/>load and failures"]
  impact --> out(["tables, JSON, Mermaid"])
  diff --> out
  simulate --> out
```

Each module has one job; the [concepts guide](docs/concepts.md) explains the ideas behind them.

| module | responsibility |
|--------|----------------|
| `models.py` | Pydantic v2 models (`Datacenter`, `Rack`, `Server`, `Service`, `Pipeline`, `Schema`, `SchemaField`, `Dependency`) and reference validation |
| `parser.py` | YAML loading, user-facing errors, cycle detection |
| `graph.py` | Graph construction plus DOT/JSON export |
| `mermaid.py` | Mermaid flowchart export, with optional impact highlighting |
| `semver.py` | Schema diff, change levels, version bumping |
| `impact.py` | Blast radius, broken consumers, severity |
| `diff.py` | Comparison of two datacenter files: components, dependencies, schema impact |
| `importers/` | Schema importers (JSON Schema today) and the YAML writer for what they read |
| `report.py` | Versioned JSON documents for CI (impact and diff results, errors) |
| `simulate.py` | Capacity and failure simulation |
| `cli.py` | Typer + Rich command line |

## Development

```bash
uv sync
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format --check .   # formatting ("uv run ruff format ." fixes it)
uv run mypy src tests   # strict type checking
```

CI runs all of the above on Python 3.11, 3.12 and 3.13.

## Roadmap

- Import schemas from Avro and SQL DDL (JSON Schema is supported)
- Throughput and latency modelling for pipelines
- Markdown reports for CI comments
- Web UI to explore the graph

Ideas and contributions are welcome. Please open an issue to discuss them.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and
[CHANGELOG.md](CHANGELOG.md) for release notes. Everyone taking part is expected to follow
the [Code of Conduct](CODE_OF_CONDUCT.md); please report vulnerabilities privately, as
described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
