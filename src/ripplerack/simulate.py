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
from ripplerack.models import Datacenter, Rack, Server

WARNING_THRESHOLD = 0.8


class Status(StrEnum):
    """How a component fares under the simulation."""

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
    """The load on one server and how it fares."""

    id: str
    rack: str
    cpu: ResourceUsage
    memory: ResourceUsage
    status: Status


@dataclass(frozen=True)
class RackReport:
    """The power drawn from one rack and how it fares."""

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

    down, unavailable = _cascade(graph, failures)
    return SimulationReport(
        load_factor=load_factor,
        servers=[
            _server_report(rack, server, down, load_factor)
            for rack, server in datacenter.iter_servers()
        ],
        racks=[_rack_report(rack, down, load_factor) for rack in datacenter.racks],
        failed=list(failures),
        unavailable=sorted(unavailable.values(), key=lambda item: (item.distance, item.id)),
    )


def _cascade(
    graph: nx.DiGraph[str], failures: list[str]
) -> tuple[set[str], dict[str, AffectedNode]]:
    """Everything that is down because of ``failures``, and what was lost as a consequence.

    The second part keeps, for each component that did not fail itself, the path from the
    closest failure.
    """
    failed = set(failures)
    down = set(failed)
    unavailable: dict[str, AffectedNode] = {}
    for node in failures:
        for affected in blast_radius(graph, node):
            down.add(affected.id)
            if affected.id in failed:
                continue
            closest = unavailable.get(affected.id)
            if closest is None or affected.distance < closest.distance:
                unavailable[affected.id] = affected
    return down, unavailable


def _server_report(rack: Rack, server: Server, down: set[str], load_factor: float) -> ServerReport:
    """Usage of a server by the services that are still running on it."""
    running = [service for service in server.services if service.id not in down]
    cpu = ResourceUsage(sum(s.cpu_cores for s in running) * load_factor, server.cpu_cores)
    memory = ResourceUsage(sum(s.memory_gb for s in running) * load_factor, server.memory_gb)
    status = Status.FAILED if server.id in down else classify(cpu, memory)
    return ServerReport(server.id, rack.id, cpu, memory, status)


def _rack_report(rack: Rack, down: set[str], load_factor: float) -> RackReport:
    """Power drawn from a rack by the servers that are still up."""
    drawn = sum((s.power_kw * load_factor for s in rack.servers if s.id not in down), 0.0)
    power = ResourceUsage(drawn, rack.power_capacity_kw)
    status = Status.FAILED if rack.id in down else classify(power)
    return RackReport(rack.id, power, status)
