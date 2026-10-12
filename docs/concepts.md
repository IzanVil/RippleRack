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

A schema field is *required* unless it declares `nullable: true`, in which case it is
*optional* (see [yaml-format.md](yaml-format.md#schema-fields)). Seen as a type, a required
field holds a value of type `T` and an optional one holds `T | None`.

RippleRack decides the level of a change from the two schemas alone; it never looks at the
data. Every elementary change gets a level, and the level of a schema change is the highest
of them. Each change also says whether it **breaks readers**: the pipelines that consume the
affected field.

| change | level | breaks readers? | why |
|--------|-------|-----------------|-----|
| field removed | major | yes | readers of that field lose it |
| field type changed | major | yes | readers receive a value of another type |
| nullability widened (required → optional) | major | yes | readers may now receive a null they never had to handle |
| required field added | major | no | no reader is affected, but every record must now carry a value that earlier records do not have |
| optional field added | minor | no | nothing is demanded and no reader is affected |
| nullability narrowed (optional → required) | minor | no | readers get a stronger guarantee |
| description changed or fields reordered | patch | no | no structural change |

RippleRack also suggests the next version and warns when the declared version
is lower than the required bump (e.g. a breaking change shipped as `1.2.1`).

A rename is detected as *remove + add*, which is correctly a major change.

### Widening and narrowing nullability

Making a field nullable *widens* the values it can hold (`T` → `T | None`); making it
required *narrows* them (`T | None` → `T`). The two directions are classified differently on
purpose:

* **Widening is major.** A reader written for `T` has no code for `None`, so a null that
  appears where there never was one can break it.
* **Narrowing is minor.** A reader written for `T | None` already copes with a field that is
  never null, so a stronger guarantee cannot break it.

This is a design decision, not an oversight. RippleRack takes the point of view of the
pipelines that read a schema: the pipeline that owns a schema produces the data and the
others consume it. Two consequences follow:

* Adding a **required** field is still major although no reader breaks, because it changes
  what every record must contain: records written before the change cannot satisfy it.
* Narrowing an optional field is **not** treated the same way. RippleRack does not inspect
  the data, so it cannot know whether earlier records hold nulls, and what readers receive
  only gets stronger. If your history does contain nulls, plan for them when you tighten a
  field.

Other ecosystems see the same change from the same two sides:

* **TypeScript.** `T` is assignable to `T | null`, not the other way round. For a value that
  is *read* (a function result, a property), widening breaks callers under
  `strictNullChecks` and narrowing is compatible; for a value that is *written* (a
  parameter) it is the reverse. A schema field is read by its consumers, so RippleRack
  follows the first case.
* **Rust.** `T` and `Option<T>` are unrelated types with no implicit conversion, so changing
  a public type in either direction breaks callers. RippleRack is more permissive when
  narrowing, because a data pipeline has no compiler and a stronger guarantee cannot break
  a reader.
* **JSON Schema.** Adding `null` to the accepted types *loosens* the schema and removing it
  *tightens* it. Which direction counts as breaking depends on who relies on the schema:
  loosening affects consumers that assumed non-null values, tightening affects producers and
  existing documents. RippleRack reports from the consumers' side.

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
