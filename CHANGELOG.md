# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `ripplerack diff BASE HEAD`: compares two datacenter files and reports added,
  removed and modified components, changed dependencies, schema changes (through the
  SemVer and impact engines, evaluated against the head datacenter), possible renames,
  warnings and an overall severity. Supports `--format json` and `--fail-on-breaking`.
- `examples/mini_datacenter_v2.yaml`, a revised version of the mini datacenter to try
  `diff` with.
- `impact --format json` (`-F json`): machine-readable output with a versioned
  envelope (`schemaVersion`, `tool`, `command`), documented in
  `docs/output-formats.md`.
- With `--format json`, errors are reported as JSON documents on stderr with stable
  `error.code` values (`file_not_found`, `io_error`, `invalid_yaml`,
  `invalid_document`, `validation_failed`, `dependency_cycle`, `unknown_pipeline`).
- `docs/output-formats.md`: JSON conventions, stability policy, error codes, exit codes
  and the difference between `schemaVersion` and `dataSchemaVersion`.

### Changed

- **BREAKING:** `graph --format json` now uses camelCase keys like every other JSON
  document. The pipeline node attribute `schema_version` is now `dataSchemaVersion`, the
  version of the data schema the pipeline produces. It is not the JSON contract version
  `schemaVersion`, which versions the envelope (see `docs/output-formats.md`). Consumers
  must read `dataSchemaVersion` instead of `schema_version`. The in-memory NetworkX node
  attribute is renamed too, to `data_schema_version`.
- The CI workflow runs on pushes to any branch, not only `main`.

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
