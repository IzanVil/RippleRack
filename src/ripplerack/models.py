"""Pydantic models describing a RippleRack datacenter.

The YAML layout is hierarchical for readability (racks contain servers, servers
contain services) while pipelines and explicit dependencies live at the top level.
Cross-references between entities are validated by :class:`Datacenter`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SEMVER_PATTERN = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[A-Za-z0-9_.\-]+$"),
]
SemVerString = Annotated[str, StringConstraints(strip_whitespace=True, pattern=SEMVER_PATTERN)]


class StrictModel(BaseModel):
    """Base model that rejects unknown keys so typos in YAML are reported.

    Infinite and NaN numbers are rejected too: they make no sense for capacities and
    cannot be represented in the JSON documents the CLI produces.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FieldType(StrEnum):
    """Primitive data types supported in pipeline schemas."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    TIMESTAMP = "timestamp"
    DATE = "date"
    JSON = "json"


class SchemaField(StrictModel):
    """A single column/attribute of a data schema."""

    name: Identifier
    type: FieldType
    nullable: bool = False
    description: str = ""


class Schema(StrictModel):
    """A versioned data schema produced by a pipeline."""

    name: Identifier
    version: SemVerString
    fields: list[SchemaField] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_field_names(self) -> Schema:
        duplicates = _duplicates(f.name for f in self.fields)
        if duplicates:
            raise ValueError(f"schema '{self.name}' has duplicate fields: {', '.join(duplicates)}")
        return self

    def field_map(self) -> dict[str, SchemaField]:
        """Return fields indexed by name."""
        return {f.name: f for f in self.fields}


class Service(StrictModel):
    """A workload running on a server (database, broker, API...)."""

    id: Identifier
    cpu_cores: float = Field(ge=0)
    memory_gb: float = Field(ge=0)
    description: str = ""


class Server(StrictModel):
    """A physical or virtual machine mounted in a rack."""

    id: Identifier
    cpu_cores: float = Field(gt=0)
    memory_gb: float = Field(gt=0)
    power_kw: float = Field(ge=0)
    services: list[Service] = Field(default_factory=list)


class Rack(StrictModel):
    """A rack with a power budget containing servers."""

    id: Identifier
    power_capacity_kw: float = Field(gt=0)
    servers: list[Server] = Field(default_factory=list)


class PipelineInput(StrictModel):
    """An upstream pipeline consumed by another pipeline.

    ``fields`` lists the upstream fields actually read. When omitted, the consumer
    is assumed to depend on every field of the upstream schema.
    """

    pipeline: Identifier
    fields: list[Identifier] | None = None


class Pipeline(StrictModel):
    """A data pipeline that runs on a service and produces a schema."""

    id: Identifier
    runs_on: Identifier
    schema_: Schema = Field(alias="schema")
    inputs: list[PipelineInput] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _normalize_inputs(cls, data: Any) -> Any:
        """Allow ``inputs: [a, b]`` as shorthand for ``[{pipeline: a}, {pipeline: b}]``."""
        if isinstance(data, dict) and isinstance(data.get("inputs"), list):
            data = dict(data)
            data["inputs"] = [
                {"pipeline": item} if isinstance(item, str) else item for item in data["inputs"]
            ]
        return data


class DependencyKind(StrEnum):
    """Nature of an explicit dependency between two components."""

    RUNTIME = "runtime"
    DATA = "data"
    NETWORK = "network"


class Dependency(StrictModel):
    """Explicit dependency: ``source`` depends on ``target``.

    A change or failure in ``target`` ripples to ``source``.
    """

    source: Identifier
    target: Identifier
    kind: DependencyKind = DependencyKind.RUNTIME


class Datacenter(StrictModel):
    """Root document: a complete datacenter description."""

    name: str = Field(min_length=1)
    description: str = ""
    racks: list[Rack] = Field(default_factory=list)
    pipelines: list[Pipeline] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)

    def iter_servers(self) -> Iterator[tuple[Rack, Server]]:
        """Yield every ``(rack, server)`` pair."""
        for rack in self.racks:
            for server in rack.servers:
                yield rack, server

    def iter_services(self) -> Iterator[tuple[Server, Service]]:
        """Yield every ``(server, service)`` pair."""
        for _, server in self.iter_servers():
            for service in server.services:
                yield server, service

    def pipeline(self, pipeline_id: str) -> Pipeline:
        """Return the pipeline with ``pipeline_id`` or raise ``KeyError``."""
        for pipeline in self.pipelines:
            if pipeline.id == pipeline_id:
                return pipeline
        raise KeyError(pipeline_id)

    def all_ids(self) -> list[str]:
        """Return every component id in declaration order."""
        ids: list[str] = []
        for rack in self.racks:
            ids.append(rack.id)
            for server in rack.servers:
                ids.append(server.id)
                ids.extend(service.id for service in server.services)
        ids.extend(p.id for p in self.pipelines)
        return ids

    @model_validator(mode="after")
    def _check_references(self) -> Datacenter:
        ids = self.all_ids()
        duplicates = _duplicates(ids)
        if duplicates:
            raise ValueError(f"duplicate component ids: {', '.join(duplicates)}")
        errors = [*self._pipeline_errors(), *self._dependency_errors(set(ids))]
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def _pipeline_errors(self) -> Iterator[str]:
        """What is wrong with where the pipelines run and with what they read."""
        service_ids = {service.id for _, service in self.iter_services()}
        pipelines = {pipeline.id: pipeline for pipeline in self.pipelines}
        for pipeline in self.pipelines:
            if pipeline.runs_on not in service_ids:
                yield f"pipeline '{pipeline.id}' runs on unknown service '{pipeline.runs_on}'"
            for item in pipeline.inputs:
                yield from _input_errors(pipeline, item, pipelines.get(item.pipeline))

    def _dependency_errors(self, known: set[str]) -> Iterator[str]:
        """What is wrong with the explicit dependencies: unknown components, and itself."""
        for dep in self.dependencies:
            for endpoint in (dep.source, dep.target):
                if endpoint not in known:
                    yield f"dependency {dep.source} -> {dep.target} references unknown '{endpoint}'"
            if dep.source == dep.target:
                yield f"component '{dep.source}' cannot depend on itself"


def _input_errors(
    pipeline: Pipeline, item: PipelineInput, upstream: Pipeline | None
) -> Iterator[str]:
    """What is wrong with one input of ``pipeline``, given the pipeline it names (or none)."""
    if upstream is None:
        yield f"pipeline '{pipeline.id}' consumes unknown pipeline '{item.pipeline}'"
        return
    available = upstream.schema_.field_map()
    missing = [name for name in item.fields or [] if name not in available]
    if missing:
        yield (
            f"pipeline '{pipeline.id}' reads fields missing from "
            f"'{upstream.id}': {', '.join(missing)}"
        )


def _duplicates(values: Iterator[str] | list[str]) -> list[str]:
    return sorted(name for name, count in Counter(values).items() if count > 1)
