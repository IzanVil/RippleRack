"""Semantic comparison of two datacenter descriptions.

Components are matched across the two files by ``id``. A component whose id changes
is reported as removed plus added: renames are never inferred silently, but when a
removed and an added component are identical apart from their id a hint is added to
``possible_renames``.

Schema changes reuse the SemVer and impact engines. Impact is evaluated in the *head*
datacenter: a consumer counts as broken when, in head, it still reads a field that the
change breaks. Consumers that exist only in head were written against the new schema
and are never reported as broken.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from enum import StrEnum

from ripplerack.graph import NodeKind
from ripplerack.impact import ImpactReport, Severity, analyze_diff
from ripplerack.models import Datacenter, DependencyKind, Pipeline, Rack, Server, Service
from ripplerack.parser import LoadedDatacenter
from ripplerack.semver import ChangeLevel, SchemaDiff, diff_schemas

_KIND_ORDER = {NodeKind.RACK: 0, NodeKind.SERVER: 1, NodeKind.SERVICE: 2, NodeKind.PIPELINE: 3}


class WarningCode(StrEnum):
    """Identifiers of the non-fatal findings a comparison can report."""

    SCHEMA_VERSION_TOO_LOW = "schema_version_too_low"
    COMPONENT_KIND_CHANGED = "component_kind_changed"
    DATACENTER_NAME_CHANGED = "datacenter_name_changed"


@dataclass(frozen=True)
class AttributeChange:
    """An attribute whose value differs between base and head."""

    attribute: str
    before: object
    after: object


@dataclass(frozen=True)
class ComponentRef:
    """A component that exists in only one of the two files."""

    id: str
    kind: NodeKind
    parent: str | None


@dataclass(frozen=True)
class ComponentChange:
    """A component present in both files whose attributes differ."""

    id: str
    kind: NodeKind
    changes: list[AttributeChange]


@dataclass(frozen=True)
class DependencyRef:
    """An explicit dependency that exists in only one of the two files."""

    source: str
    target: str
    kind: DependencyKind


@dataclass(frozen=True)
class DependencyChange:
    """An explicit dependency whose kind differs between the two files."""

    source: str
    target: str
    before: DependencyKind
    after: DependencyKind


@dataclass(frozen=True)
class RemovedWithDependents:
    """A removed component that something still in head used to depend on."""

    id: str
    kind: NodeKind
    dependents: list[str]


@dataclass(frozen=True)
class PossibleRename:
    """A removed and an added component that are identical apart from their id."""

    kind: NodeKind
    old: str
    new: str


@dataclass(frozen=True)
class DiffWarning:
    """A non-fatal finding that deserves a reviewer's attention."""

    code: WarningCode
    message: str


@dataclass(frozen=True)
class DatacenterDiff:
    """Result of comparing a base datacenter with a head datacenter."""

    base_name: str
    head_name: str
    metadata: list[AttributeChange] = field(default_factory=list)
    added: list[ComponentRef] = field(default_factory=list)
    removed: list[ComponentRef] = field(default_factory=list)
    modified: list[ComponentChange] = field(default_factory=list)
    dependencies_added: list[DependencyRef] = field(default_factory=list)
    dependencies_removed: list[DependencyRef] = field(default_factory=list)
    dependencies_modified: list[DependencyChange] = field(default_factory=list)
    schema_impacts: list[ImpactReport] = field(default_factory=list)
    removed_with_dependents: list[RemovedWithDependents] = field(default_factory=list)
    possible_renames: list[PossibleRename] = field(default_factory=list)
    warnings: list[DiffWarning] = field(default_factory=list)
    severity: Severity = Severity.NONE

    @property
    def has_differences(self) -> bool:
        """Whether the two files differ at all (warnings alone do not count)."""
        return bool(
            self.metadata
            or self.added
            or self.removed
            or self.modified
            or self.dependencies_added
            or self.dependencies_removed
            or self.dependencies_modified
            or self.schema_impacts
        )

    @property
    def broken_consumers(self) -> list[str]:
        """Distinct pipelines broken by at least one schema change, sorted."""
        return sorted({c.pipeline for r in self.schema_impacts for c in r.broken_consumers})


@dataclass(frozen=True)
class _Component:
    """A component as it is compared: its kind, what it hangs from and its attributes."""

    kind: NodeKind
    parent: str | None
    attributes: dict[str, object]


def diff_datacenters(base: LoadedDatacenter, head: LoadedDatacenter) -> DatacenterDiff:
    """Compare ``base`` with ``head`` and assess the impact of the differences."""
    base_dc, head_dc = base.datacenter, head.datacenter
    base_index, head_index = _index(base_dc), _index(head_dc)

    metadata, name_warnings = _metadata_changes(base_dc, head_dc)
    kind_changed = _kind_changed(base_index, head_index)
    added, removed, modified = _component_changes(base_index, head_index, kind_changed)
    dependencies_added, dependencies_removed, dependencies_modified = _dependency_changes(
        base_dc, head_dc
    )
    schema_changes = _schema_changes(base_dc, head_dc)

    diff = DatacenterDiff(
        base_name=base_dc.name,
        head_name=head_dc.name,
        metadata=metadata,
        added=added,
        removed=removed,
        modified=modified,
        dependencies_added=dependencies_added,
        dependencies_removed=dependencies_removed,
        dependencies_modified=dependencies_modified,
        schema_impacts=_schema_impacts(head, schema_changes, _new_pipelines(base_dc, head_dc)),
        removed_with_dependents=_removed_with_dependents(base, head_index, removed),
        possible_renames=_possible_renames(removed, added, base_index, head_index),
        warnings=[
            *name_warnings,
            *_kind_change_warnings(kind_changed, base_index, head_index),
            *_version_warnings(schema_changes),
        ],
    )
    return _with_severity(diff)


def _with_severity(diff: DatacenterDiff) -> DatacenterDiff:
    """Return ``diff`` with its overall severity filled in.

    Any difference is at least ``low``; a removed component that something in head
    depended on is at least ``medium``; schema changes contribute the severity computed
    by the impact engine. The result is the highest of these.
    """
    severity = Severity.LOW if diff.has_differences else Severity.NONE
    if diff.removed_with_dependents:
        severity = max(severity, Severity.MEDIUM)
    for report in diff.schema_impacts:
        severity = max(severity, report.severity)
    return replace(diff, severity=severity)


# ------------------------------------------------------------------ the datacenter itself


def _metadata_changes(
    base_dc: Datacenter, head_dc: Datacenter
) -> tuple[list[AttributeChange], list[DiffWarning]]:
    """The name and the description when they differ, and a warning if the name does."""
    changes: list[AttributeChange] = []
    warnings: list[DiffWarning] = []
    if base_dc.name != head_dc.name:
        changes.append(AttributeChange("name", base_dc.name, head_dc.name))
        warnings.append(
            DiffWarning(
                WarningCode.DATACENTER_NAME_CHANGED,
                f"datacenter name changed from '{base_dc.name}' to '{head_dc.name}': "
                "are you comparing different datacenters?",
            )
        )
    if base_dc.description != head_dc.description:
        changes.append(AttributeChange("description", base_dc.description, head_dc.description))
    return changes, warnings


# ----------------------------------------------------------------------- the components


def _kind_changed(
    base_index: dict[str, _Component], head_index: dict[str, _Component]
) -> list[str]:
    """Ids that are in both files but belong to a component of another kind, sorted."""
    return sorted(
        i for i in base_index.keys() & head_index.keys() if base_index[i].kind != head_index[i].kind
    )


def _kind_change_warnings(
    kind_changed: list[str], base_index: dict[str, _Component], head_index: dict[str, _Component]
) -> list[DiffWarning]:
    """A warning for each id that is now a component of another kind."""
    return [
        DiffWarning(
            WarningCode.COMPONENT_KIND_CHANGED,
            f"'{component_id}' changed from {base_index[component_id].kind} to "
            f"{head_index[component_id].kind}; it is reported as removed and added",
        )
        for component_id in kind_changed
    ]


def _component_changes(
    base_index: dict[str, _Component],
    head_index: dict[str, _Component],
    kind_changed: list[str],
) -> tuple[list[ComponentRef], list[ComponentRef], list[ComponentChange]]:
    """The components added, removed and modified; one that changed kind is removed and added."""
    removed_ids = (base_index.keys() - head_index.keys()) | set(kind_changed)
    added_ids = (head_index.keys() - base_index.keys()) | set(kind_changed)
    added = sorted(
        (ComponentRef(i, head_index[i].kind, head_index[i].parent) for i in added_ids),
        key=_by_kind_then_id,
    )
    removed = sorted(
        (ComponentRef(i, base_index[i].kind, base_index[i].parent) for i in removed_ids),
        key=_by_kind_then_id,
    )
    kept = sorted((base_index.keys() & head_index.keys()) - set(kind_changed))
    changes = (_compare(i, base_index[i], head_index[i]) for i in kept)
    modified = sorted((change for change in changes if change is not None), key=_by_kind_then_id)
    return added, removed, modified


def _removed_with_dependents(
    base: LoadedDatacenter, head_index: dict[str, _Component], removed: list[ComponentRef]
) -> list[RemovedWithDependents]:
    """Only direct dependents are listed: the closest removed provider is the one to blame."""
    result: list[RemovedWithDependents] = []
    for ref in removed:
        dependents = sorted(n for n in base.graph.successors(ref.id) if n in head_index)
        if dependents:
            result.append(RemovedWithDependents(ref.id, ref.kind, dependents))
    return result


# --------------------------------------------------------------------- the dependencies


def _dependency_changes(
    base_dc: Datacenter, head_dc: Datacenter
) -> tuple[list[DependencyRef], list[DependencyRef], list[DependencyChange]]:
    """The explicit dependencies added, removed and whose kind changed, sorted."""
    before = {(d.source, d.target): d.kind for d in base_dc.dependencies}
    after = {(d.source, d.target): d.kind for d in head_dc.dependencies}
    modified = [
        DependencyChange(source, target, before[(source, target)], kind)
        for (source, target), kind in sorted(after.items())
        if (source, target) in before and before[(source, target)] != kind
    ]
    return _only_in(after, before), _only_in(before, after), modified


def _only_in(
    dependencies: dict[tuple[str, str], DependencyKind],
    others: dict[tuple[str, str], DependencyKind],
) -> list[DependencyRef]:
    """The dependencies that ``others`` does not have, sorted."""
    return [
        DependencyRef(source, target, kind)
        for (source, target), kind in sorted(dependencies.items())
        if (source, target) not in others
    ]


# ------------------------------------------------------------------------- the schemas


def _schema_changes(base_dc: Datacenter, head_dc: Datacenter) -> list[tuple[str, SchemaDiff]]:
    """The comparison of the schema of every pipeline that both files have, by pipeline id."""
    before = {p.id: p.schema_ for p in base_dc.pipelines}
    after = {p.id: p.schema_ for p in head_dc.pipelines}
    return [
        (pipeline_id, diff_schemas(before[pipeline_id], after[pipeline_id]))
        for pipeline_id in sorted(before.keys() & after.keys())
    ]


def _new_pipelines(base_dc: Datacenter, head_dc: Datacenter) -> set[str]:
    """Pipelines that exist only in head: they were written against the new schemas."""
    return {p.id for p in head_dc.pipelines} - {p.id for p in base_dc.pipelines}


def _version_warnings(schema_changes: list[tuple[str, SchemaDiff]]) -> list[DiffWarning]:
    """A warning for each schema whose declared version is lower than its changes require."""
    return [
        _version_warning(pipeline_id, schema_diff)
        for pipeline_id, schema_diff in schema_changes
        if not schema_diff.version_is_consistent
    ]


def _version_warning(pipeline_id: str, schema_diff: SchemaDiff) -> DiffWarning:
    if schema_diff.level is ChangeLevel.NONE:
        detail = f"version went backwards from {schema_diff.old.version}"
    else:
        detail = (
            f"is too low for a {schema_diff.level} change "
            f"(expected >= {schema_diff.suggested_version})"
        )
    return DiffWarning(
        WarningCode.SCHEMA_VERSION_TOO_LOW,
        f"pipeline '{pipeline_id}': declared version {schema_diff.new.version} {detail}",
    )


def _schema_impacts(
    head: LoadedDatacenter, schema_changes: list[tuple[str, SchemaDiff]], new_pipelines: set[str]
) -> list[ImpactReport]:
    """The impact, in head, of every schema that changed."""
    return [
        analyze_diff(
            head.datacenter, head.graph, pipeline_id, schema_diff, ignore_consumers=new_pipelines
        )
        for pipeline_id, schema_diff in schema_changes
        if schema_diff.changes
    ]


# ----------------------------------------------------- how a component is described


def _index(datacenter: Datacenter) -> dict[str, _Component]:
    """Describe every component by kind, parent and the attributes that are compared."""
    index: dict[str, _Component] = {}
    for rack in datacenter.racks:
        index[rack.id] = _rack_component(rack)
        for server in rack.servers:
            index[server.id] = _server_component(rack, server)
            for service in server.services:
                index[service.id] = _service_component(server, service)
    for pipeline in datacenter.pipelines:
        index[pipeline.id] = _pipeline_component(pipeline)
    return index


def _rack_component(rack: Rack) -> _Component:
    return _Component(NodeKind.RACK, None, {"power_capacity_kw": rack.power_capacity_kw})


def _server_component(rack: Rack, server: Server) -> _Component:
    return _Component(
        NodeKind.SERVER,
        rack.id,
        {
            "rack": rack.id,
            "cpu_cores": server.cpu_cores,
            "memory_gb": server.memory_gb,
            "power_kw": server.power_kw,
        },
    )


def _service_component(server: Server, service: Service) -> _Component:
    return _Component(
        NodeKind.SERVICE,
        server.id,
        {
            "server": server.id,
            "cpu_cores": service.cpu_cores,
            "memory_gb": service.memory_gb,
            "description": service.description,
        },
    )


def _pipeline_component(pipeline: Pipeline) -> _Component:
    return _Component(
        NodeKind.PIPELINE,
        pipeline.runs_on,
        {
            "runs_on": pipeline.runs_on,
            "inputs": _canonical_inputs(pipeline),
            "schema.name": pipeline.schema_.name,
            "schema.version": pipeline.schema_.version,
            "schema.fields": [
                {
                    "name": f.name,
                    "type": str(f.type),
                    "nullable": f.nullable,
                    "description": f.description,
                }
                for f in pipeline.schema_.fields
            ],
        },
    )


def _canonical_inputs(pipeline: Pipeline) -> list[dict[str, object]]:
    """List a pipeline's inputs in an order that does not depend on how they were written."""
    items = sorted(
        pipeline.inputs,
        key=lambda i: (i.pipeline, i.fields is not None, sorted(i.fields or [])),
    )
    return [
        {"pipeline": i.pipeline, "fields": sorted(i.fields) if i.fields is not None else None}
        for i in items
    ]


def _compare(component_id: str, before: _Component, after: _Component) -> ComponentChange | None:
    """The attributes that differ between the two versions of a component; none if none does."""
    changes = [
        AttributeChange(name, value, after.attributes[name])
        for name, value in before.attributes.items()
        if value != after.attributes[name]
    ]
    return ComponentChange(component_id, before.kind, changes) if changes else None


def _by_kind_then_id(item: ComponentRef | ComponentChange) -> tuple[int, str]:
    """The order components are reported in: racks, servers, services, pipelines; then by id."""
    return (_KIND_ORDER[item.kind], item.id)


def _possible_renames(
    removed: list[ComponentRef],
    added: list[ComponentRef],
    base_index: dict[str, _Component],
    head_index: dict[str, _Component],
) -> list[PossibleRename]:
    """Pair removed and added components that are identical except for their id.

    Only unambiguous one-to-one matches are reported; if several components share
    the same description, none of them is paired.
    """
    removed_by_signature = _ids_by_signature(removed, base_index)
    added_by_signature = _ids_by_signature(added, head_index)
    renames = [
        PossibleRename(base_index[old[0]].kind, old[0], added_by_signature[key][0])
        for key, old in removed_by_signature.items()
        if len(old) == 1 and len(added_by_signature.get(key, [])) == 1
    ]
    return sorted(renames, key=lambda r: (_KIND_ORDER[r.kind], r.old))


def _ids_by_signature(
    refs: list[ComponentRef], index: dict[str, _Component]
) -> dict[str, list[str]]:
    """The ids of these components grouped by everything about them except the id."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for ref in refs:
        component = index[ref.id]
        signature = repr((component.kind, component.parent, sorted(component.attributes.items())))
        grouped[signature].append(ref.id)
    return grouped
