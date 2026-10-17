# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The name of a schema taken from a title, an `$id` or a file name tells the words of a
  CamelCase name apart: `OrderEvent` becomes `order_event` and no longer `orderevent`.

## [0.2.1] - 2026-10-17

### Added

- `ripplerack import FILE --from json-schema`: reads a JSON Schema and writes the RippleRack
  schema it describes as YAML, a schema file that `impact --schema` reads as it is.
  Properties that `required` lists become required fields and the others `nullable`;
  references inside the file and a single-member `allOf` are followed, `allOf` at the root
  merges its members, and objects and arrays become `json` fields. `FILE` may be `-` for
  standard input and `-o FILE` writes a file, which is never overwritten without `--force`.
  `--name` and `--version` name and version the schema.
- Strict by default: a construct that decides which fields exist or what type they have, but
  has no equivalent (a `oneOf` of several types, a reference to another file...), is an error
  that says where. With `--lenient` a property that cannot be typed becomes a `json` field and a
  warning.
- Warnings on standard error as `warning[code] pointer: message`, with the stable codes
  `additional_properties_ignored` (for `additionalProperties: false` and
  `unevaluatedProperties: false`, in both modes),
  `degraded_to_json` and `undeclared_required`.
- Error codes `invalid_json`, `invalid_json_schema`, `unsupported_json_schema` and
  `output_exists`, listed in `docs/output-formats.md`.
- `docs/import.md`, with the translation rules and the known limitations of an imported
  schema, and `examples/schemas/orders_v2.schema.json`, a JSON Schema equivalent to
  `examples/changes/orders_v2.yaml`.
- Screenshots of `validate`, `graph`, `impact` and `simulate` in the README, drawn from the real
  output of the commands by `docs/images/generate.py`. A test fails when one is out of date.

### Changed

- `ripplerack import` refuses a root `oneOf`, `anyOf`, `then`, `else`, `dependentSchemas` or
  `dependencies` whose alternatives declare properties that the schema itself does not, in
  strict mode and with `--lenient`, instead of importing the schema without those fields. A
  schema that is a family of variants cannot be imported as one schema yet; alternatives that
  only constrain properties the schema declares are still ignored.
- The tests include properties checked with Hypothesis, now a development dependency.

## [0.2.0] - 2026-10-15

### Added

- `impact --format json` (`-F json`): machine-readable output with a versioned
  envelope (`schemaVersion`, `tool`, `command`), documented in
  `docs/output-formats.md`.
- With `--format json`, errors are reported as JSON documents on stderr with stable
  `error.code` values (`file_not_found`, `io_error`, `invalid_yaml`,
  `invalid_document`, `validation_failed`, `dependency_cycle`, `unknown_pipeline`).
- `docs/output-formats.md`: JSON conventions, stability policy, error codes, exit codes
  and the difference between `schemaVersion` and `dataSchemaVersion`.
- `ripplerack diff BASE HEAD`: compares two datacenter files and reports added,
  removed and modified components, changed dependencies, schema changes (through the
  SemVer and impact engines, evaluated against the head datacenter), possible renames,
  warnings and an overall severity. Supports `--format json` and `--fail-on-breaking`.
- `examples/mini_datacenter_v2.yaml`, a revised version of the mini datacenter to try
  `diff` with.
- `graph --format mermaid`: exports the dependency graph as a Mermaid flowchart with racks
  and servers as nested subgraphs and arrows labelled by relation.
- `impact --format mermaid`: the same diagram with the impact highlighted: the changed
  pipeline, broken consumers, components at risk and the arrows along the impact paths.
- Community files: a Code of Conduct (Contributor Covenant 2.1), a security policy, issue
  templates for bug reports and feature requests, and a pull request template.

### Changed

- **BREAKING:** `graph --format json` now uses camelCase keys like every other JSON
  document. The pipeline node attribute `schema_version` is now `dataSchemaVersion`, the
  version of the data schema the pipeline produces. It is not the JSON contract version
  `schemaVersion`, which versions the envelope (see `docs/output-formats.md`). Consumers
  must read `dataSchemaVersion` instead of `schema_version`. The in-memory NetworkX node
  attribute is renamed too, to `data_schema_version`.
- **BREAKING (Python API):** `ripplerack.parser.RippleRackError` now takes a second argument,
  `code`, one of the new `ripplerack.parser.ErrorCode` values. Code that only catches the
  exception keeps working; code that raises it must pass a code. The command line is not
  affected.
- CI runs on every push to any branch, not only `main`, and on pull requests from forks. A
  pull request from a branch of this repository is no longer run a second time, and runs
  made obsolete by a newer push to the same branch are cancelled (never on `main`).

### Fixed

- Infinite and NaN numbers (`.inf`, `.nan`) in a datacenter file are rejected instead of
  being accepted as capacities.
- Text-mode error messages no longer lose text that looks like Rich markup, such as
  `[abc]` in a file path.
- Files that cannot be read (permissions, invalid UTF-8) now produce a regular error
  instead of a traceback.

## [0.1.0] - 2026-10-11

### Added

- Pydantic v2 models for datacenters, racks, servers, services, pipelines,
  schemas, fields and dependencies, with validation of ids and cross-references.
- YAML parser with readable validation errors and dependency cycle detection.
- NetworkX dependency graph with DOT and JSON export.
- Semantic schema diff engine that classifies changes as patch, minor or major,
  suggests the next version and flags understated version bumps.
- Impact engine that computes the blast radius of a schema change, the direct
  consumers that break, the downstream components at risk and an overall severity.
- Capacity and failure simulation with load scaling and cascading outages.
- `ripplerack` CLI built with Typer and Rich: `validate`, `impact`, `simulate`
  and `graph`.
- `examples/mini_datacenter.yaml` and sample schema changes in `examples/changes/`.
- Documentation: README, file format reference and concepts guide.
- GitHub Actions CI running ruff, mypy and pytest on Python 3.11, 3.12 and 3.13.
- MIT license.
