# Concepts

## The impact graph

RippleRack turns a datacenter file into a directed graph (NetworkX `DiGraph`).
Edges point in the direction an impact travels, from provider to dependent:

| relation  | edge                                          |
|-----------|-----------------------------------------------|
| `hosts`   | rack → server, server → service               |
| `runs`    | service → pipeline running on it              |
| `feeds`   | upstream pipeline → downstream pipeline       |
| `runtime`, `data`, `network` | explicit dependency target → source |

The *blast radius* of a component is the set of nodes reachable from it.

## Schema SemVer rules

Every elementary change gets a level; the schema change level is the highest one.

| change                                  | level | breaks readers of the field? |
|-----------------------------------------|-------|------------------------------|
| field removed                           | major | yes |
| field type changed                      | major | yes |
| required field made nullable            | major | yes (readers may now get nulls) |
| required field added                    | major | no (but old data/producers can't satisfy it) |
| optional field added                    | minor | no |
| nullable field made required            | minor | no |
| description changed, fields reordered   | patch | no |

RippleRack also suggests the next version and warns when the declared version
is lower than the required bump (e.g. a breaking change shipped as `1.2.1`).

A rename is detected as *remove + add*, which is correctly a major change.

## Impact severity

Given a pipeline and its new schema:

1. Diff the old and new schema.
2. Collect every downstream component (blast radius) with its distance and path.
3. A **direct consumer breaks** when it reads a field touched by a
   reader-breaking change. Consumers that list `fields` are only affected by
   changes to those fields; consumers without a list read everything.
4. Everything downstream of a broken consumer is **at risk**.

| severity   | condition |
|------------|-----------|
| `none`     | no schema change |
| `low`      | patch or minor change |
| `medium`   | major change, but no consumer reads the broken fields |
| `high`     | at least one direct consumer breaks |
| `critical` | a broken consumer feeds further pipelines (cascading break) |

## Capacity simulation

`ripplerack simulate` multiplies every service's CPU and memory request (and
every server's power draw) by `--load`, then compares them with capacity:
`ok` < 80% ≤ `warning` ≤ 100% < `overloaded`. Components passed with `--fail`
are taken down together with their whole blast radius; their resources are
released.
