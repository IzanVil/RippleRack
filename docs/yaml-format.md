# Datacenter file format

A RippleRack datacenter is a single YAML document. Infrastructure is nested
(racks → servers → services) while pipelines and explicit dependencies live at
the top level and reference components by `id`.

Unknown keys are rejected, so typos are caught by `ripplerack validate`.

```yaml
name: my-datacenter          # required
description: optional text

racks:
  - id: rack-a               # ids must be unique across the whole document
    power_capacity_kw: 6.0
    servers:
      - id: srv-1
        cpu_cores: 32
        memory_gb: 128
        power_kw: 1.2        # draw at nominal load (scales with --load)
        services:
          - id: kafka
            cpu_cores: 8     # resources requested by the service
            memory_gb: 32
            description: optional

pipelines:
  - id: orders-ingest
    runs_on: kafka           # must be a service id
    schema:
      name: orders
      version: 1.2.0         # MAJOR.MINOR.PATCH
      fields:
        - name: order_id
          type: integer      # string | integer | float | boolean | timestamp | date | json
          nullable: false    # default; true means the field may be null (optional)
          description: optional

  - id: orders-enriched
    runs_on: spark
    inputs:
      - pipeline: orders-ingest
        fields: [order_id, amount]   # optional: fields actually read
    schema: { ... }

  - id: customer-360
    runs_on: postgres
    inputs: [orders-ingest]  # shorthand: reads every field

dependencies:
  - source: api              # `source` depends on `target`
    target: postgres
    kind: runtime            # runtime | data | network
```

## Schema fields

| key           | meaning |
|---------------|---------|
| `name`        | The field name; unique within its schema. |
| `type`        | One of `string`, `integer`, `float`, `boolean`, `timestamp`, `date` or `json`. |
| `nullable`    | `false` (the default) makes the field *required*: it holds a value of type `T`. `true` makes it *optional*: it holds either a `T` value or `None`. |
| `description` | Free text. |

`nullable` is the only way a schema says that a field is optional. Changing it, like every
other change to a schema, is classified by the
[SemVer rules](concepts.md#schema-semver-rules).

## Validation rules

* All ids (racks, servers, services, pipelines) are unique.
* `runs_on` references an existing service.
* `inputs[].pipeline` references an existing pipeline and every listed field
  exists in that pipeline's schema.
* Dependencies reference existing components and are not self-referencing.
* The resulting graph has no cycles.

## Standalone schema files

`ripplerack impact --schema` takes a file containing just a schema
(`name`, `version`, `fields`), or a document with a top-level `schema:` key.

You do not have to write one by hand: `ripplerack import` generates it from a JSON Schema
(see [import.md](import.md)).
