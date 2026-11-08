"""What fraction of its capacity something uses, and how that reads.

The thresholds are shared by everything the simulation measures against a capacity: servers, racks
and, for the data that flows through them, pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

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


def classify(*usages: ResourceUsage) -> Status:
    """Return the worst status among the given resource usages."""
    worst = max((usage.ratio for usage in usages), default=0.0)
    if worst > 1.0:
        return Status.OVERLOADED
    if worst >= WARNING_THRESHOLD:
        return Status.WARNING
    return Status.OK
