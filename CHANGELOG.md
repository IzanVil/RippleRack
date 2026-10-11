# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
