"""Capacity and failure simulation.

The simulation is deliberately static and deterministic: it scales service
resource demands by a load factor, compares them with server and rack capacity,
and optionally marks components as failed to see what goes down with them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import networkx as nx

from ripplerack.impact import AffectedNode, blast_radius
from ripplerack.models import Datacenter

WARNING_THRESHOLD = 0.8


class Status(StrEnum):
    OK = "ok"
    WARNING = "warning"
    OVERLOADED = "overloaded"
    FAILED = "failed"


@dataclass(frozen=True)
class ResourceUsage:
    """Usage of one resource against its capacity."""

    used: float
    capacity: float

    @property
    def ratio(self) -> float:
        return self.used / self.capacity if self.capacity else 0.0


@dataclass(frozen=True)
class ServerReport:
    id: str
    rack: str
    cpu: ResourceUsage
    memory: ResourceUsage
    status: Status


@dataclass(frozen=True)
class RackReport:
    id: str
    power: ResourceUsage
    status: Status


@dataclass(frozen=True)
class SimulationReport:
    """Outcome of a simulation run."""

    load_factor: float
    servers: list[ServerReport] = field(default_factory=list)
    racks: list[RackReport] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    unavailable: list[AffectedNode] = field(default_factory=list)

    @property
    def overloaded(self) -> list[str]:
        """Ids of servers and racks running above capacity."""
        racks = [rack.id for rack in self.racks if rack.status is Status.OVERLOADED]
        servers = [server.id for server in self.servers if server.status is Status.OVERLOADED]
        return racks + servers

    @property
    def healthy(self) -> bool:
        return not self.overloaded and not self.failed


def classify(*usages: ResourceUsage) -> Status:
    """Return the worst status among the given resource usages."""
    worst = max((usage.ratio for usage in usages), default=0.0)
    if worst > 1.0:
        return Status.OVERLOADED
    if worst >= WARNING_THRESHOLD:
        return Status.WARNING
    return Status.OK


def simulate(
    datacenter: Datacenter,
    graph: nx.DiGraph[str],
    load_factor: float = 1.0,
    failures: list[str] | None = None,
) -> SimulationReport:
    """Simulate resource usage under ``load_factor`` with optional component ``failures``.

    ``Server.power_kw`` is treated as the draw at nominal load (factor 1.0) and
    scales linearly with ``load_factor``. Failed servers draw no power.
    """
    if load_factor < 0:
        raise ValueError("load_factor must be non-negative")
    failures = failures or []
    unknown = [node for node in failures if node not in graph]
    if unknown:
        raise KeyError(", ".join(unknown))

    down: set[str] = set(failures)
    unavailable: dict[str, AffectedNode] = {}
    for node in failures:
        for affected in blast_radius(graph, node):
            down.add(affected.id)
            current = unavailable.get(affected.id)
            if affected.id not in failures and (
                current is None or affected.distance < current.distance
            ):
                unavailable[affected.id] = affected

    server_reports: list[ServerReport] = []
    rack_power: dict[str, float] = {rack.id: 0.0 for rack in datacenter.racks}
    for rack, server in datacenter.iter_servers():
        running = [service for service in server.services if service.id not in down]
        cpu = ResourceUsage(sum(s.cpu_cores for s in running) * load_factor, server.cpu_cores)
        memory = ResourceUsage(sum(s.memory_gb for s in running) * load_factor, server.memory_gb)
        status = Status.FAILED if server.id in down else classify(cpu, memory)
        server_reports.append(ServerReport(server.id, rack.id, cpu, memory, status))
        if server.id not in down:
            rack_power[rack.id] += server.power_kw * load_factor

    rack_reports = []
    for rack in datacenter.racks:
        power = ResourceUsage(rack_power[rack.id], rack.power_capacity_kw)
        status = Status.FAILED if rack.id in down else classify(power)
        rack_reports.append(RackReport(rack.id, power, status))

    return SimulationReport(
        load_factor=load_factor,
        servers=server_reports,
        racks=rack_reports,
        failed=list(failures),
        unavailable=sorted(unavailable.values(), key=lambda item: (item.distance, item.id)),
    )
