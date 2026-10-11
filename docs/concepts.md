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

## Comparing two datacenters

`ripplerack diff BASE HEAD` answers "what does this change do to my datacenter?". It
compares two files and reports the differences between them, together with the impact
of every schema change.

**Identity.** Components are matched by `id`, which is unique across the whole file.
The order in which things are written never matters. A component that exists in only
one file is *added* or *removed*; one that exists in both with different attributes is
*modified*. Explicit dependencies are matched by `(source, target)`; a different `kind`
is a modification. The compared attributes are listed in
[output-formats.md](output-formats.md#components).

**Renames are not guessed.** An id that changes is a removal plus an addition, so the
severity is never silently understated. When a removed and an added component are
identical apart from their id, and no other component looks the same, the report adds
a *possible rename* hint. A removed component that something still in head depended
on is also flagged, so a rename always draws a reviewer's attention.

**Impact is judged in head.** For every pipeline whose schema fields changed, the
SemVer rules above decide which changes break readers, and the impact rules decide
which consumers break. This is done on the *head* datacenter, because that is the one
that will run:

* a consumer that was adapted in the same change (it no longer lists the removed field)
  is fine;
* a consumer that was not touched and still reads a broken field, or reads every field,
  is broken;
* a consumer that exists only in head was written against the new schema and is never
  reported;
* a consumer removed in head cannot break.

The YAML does not describe what a pipeline *does* with its inputs, so "adapted" is
inferred from the fields it declares. When in doubt the comparison errs on the side of
reporting a break.

**Severity.** The overall severity is the highest of:

| severity   | condition |
|------------|-----------|
| `none`     | the two files are equivalent |
| `low`      | any difference at all: additions, attribute edits, dependency changes, or a patch or minor schema change |
| `medium`   | a major schema change that breaks no consumer, or a removed component that something in head used to depend on |
| `high`     | at least one direct consumer breaks |
| `critical` | a broken consumer feeds further pipelines |

**Warnings.** A declared schema version that is lower than the change requires, an id
that changed kind, and two files with different datacenter names are reported as
warnings. They do not change the severity.
