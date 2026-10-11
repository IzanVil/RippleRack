"""Load and validate RippleRack YAML documents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import yaml
from pydantic import ValidationError

from ripplerack.graph import build_graph, find_cycles
from ripplerack.models import Datacenter, Schema


class RippleRackError(Exception):
    """User-facing error raised for invalid input files."""


@dataclass(frozen=True)
class LoadedDatacenter:
    """A validated datacenter together with its dependency graph."""

    datacenter: Datacenter
    graph: nx.DiGraph[str]


def load_yaml(path: Path) -> Any:
    """Read a YAML file, converting I/O and syntax problems into ``RippleRackError``."""
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise RippleRackError(f"file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise RippleRackError(f"invalid YAML in {path}: {exc}") from exc


def parse_datacenter(data: Any, source: str = "<data>") -> LoadedDatacenter:
    """Validate raw data, build the graph and reject dependency cycles."""
    if not isinstance(data, dict):
        raise RippleRackError(f"{source}: top-level document must be a mapping")
    try:
        datacenter = Datacenter.model_validate(data)
    except ValidationError as exc:
        raise RippleRackError(f"{source}: {_format_validation_error(exc)}") from exc

    graph = build_graph(datacenter)
    cycles = find_cycles(graph)
    if cycles:
        rendered = "; ".join(" -> ".join([*cycle, cycle[0]]) for cycle in cycles)
        raise RippleRackError(f"{source}: dependency cycle detected: {rendered}")
    return LoadedDatacenter(datacenter=datacenter, graph=graph)


def load_datacenter(path: Path) -> LoadedDatacenter:
    """Load, validate and build the graph for the datacenter described in ``path``."""
    return parse_datacenter(load_yaml(path), source=str(path))


def load_schema(path: Path) -> Schema:
    """Load a standalone schema file (``name``, ``version``, ``fields``).

    A file containing a top-level ``schema:`` key is also accepted.
    """
    data = load_yaml(path)
    if isinstance(data, dict) and "schema" in data:
        data = data["schema"]
    try:
        return Schema.model_validate(data)
    except ValidationError as exc:
        raise RippleRackError(f"{path}: {_format_validation_error(exc)}") from exc


def _format_validation_error(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        messages.append(f"{location}: {error['msg']}" if location else error["msg"])
    return "\n  ".join(["validation failed:", *messages])
