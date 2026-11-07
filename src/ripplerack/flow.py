"""How much data flows through the pipelines, and what each one makes of it.

Like the rest of the simulation this is static and deterministic. The pipelines that read no other
one receive ``arrival`` records per second (times the load factor); each pipeline processes at most
``throughput`` of what it is offered, and what it processes (times ``output_ratio``) is what the
pipelines that read it are offered. What a pipeline cannot process piles up as a queue and never
reaches the next one, so a bottleneck shows where it is and does not spread downstream.

Latency adds up along the way: a pipeline delivers ``latency`` seconds after the slowest of the
pipelines it reads, so the figure of each pipeline is the time since the data entered the origin of
its slowest path.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, replace

from ripplerack.capacity import ResourceUsage, Status, classify
from ripplerack.models import Datacenter, Pipeline


@dataclass(frozen=True)
class PipelineFlow:
    """What one pipeline is offered and what it makes of it (``None`` is not known)."""

    id: str
    offered: float | None
    processed: float | None
    capacity: float | None
    utilization: float | None
    status: Status | None
    latency: float | None = None


@dataclass(frozen=True)
class SlowestPath:
    """The pipelines a record crosses from the origin of the slowest path, and the seconds."""

    pipelines: list[str]
    seconds: float


@dataclass(frozen=True)
class FlowReport:
    """The flow of every pipeline, in the order the data flows, and what stands out."""

    pipelines: list[PipelineFlow]
    bottleneck: PipelineFlow | None = None
    slowest_path: SlowestPath | None = None

    @property
    def overloaded(self) -> list[str]:
        """Ids of the pipelines offered more than they can process."""
        return [flow.id for flow in self.pipelines if flow.status is Status.OVERLOADED]


def analyze_flow(
    datacenter: Datacenter, load_factor: float, down: Collection[str]
) -> FlowReport | None:
    """The flow of the pipelines under ``load_factor`` with the components in ``down`` failed.

    ``None`` when no pipeline declares anything about its flow.
    """
    if not any(_declares_flow(pipeline) for pipeline in datacenter.pipelines):
        return None
    ordered = _in_flow_order(datacenter.pipelines)
    emitted: dict[str, float | None] = {}
    flows: list[PipelineFlow] = []
    for pipeline in ordered:
        flow, emitted[pipeline.id] = _flow_of(pipeline, load_factor, pipeline.id in down, emitted)
        flows.append(flow)
    reached = _latencies(ordered, down)
    flows = [
        replace(flow, latency=reached[flow.id][0]) if flow.id in reached else flow for flow in flows
    ]
    return FlowReport(flows, _bottleneck(flows), _slowest_path(flows, reached))


def _declares_flow(pipeline: Pipeline) -> bool:
    numbers = (pipeline.arrival, pipeline.throughput, pipeline.latency, pipeline.output_ratio)
    return any(number is not None for number in numbers)


def _in_flow_order(pipelines: list[Pipeline]) -> list[Pipeline]:
    """The pipelines with what each one reads before it, otherwise in the order declared."""
    by_id = {pipeline.id: pipeline for pipeline in pipelines}
    ordered: list[Pipeline] = []
    seen: set[str] = set()

    def visit(pipeline: Pipeline) -> None:
        if pipeline.id in seen:
            return
        seen.add(pipeline.id)
        for item in pipeline.inputs:
            visit(by_id[item.pipeline])
        ordered.append(pipeline)

    for pipeline in pipelines:
        visit(pipeline)
    return ordered


def _flow_of(
    pipeline: Pipeline,
    load_factor: float,
    is_down: bool,
    emitted: dict[str, float | None],
) -> tuple[PipelineFlow, float | None]:
    """The flow of ``pipeline`` and the rate it emits, given what the ones before it emit."""
    if is_down:
        return PipelineFlow(pipeline.id, None, None, pipeline.throughput, None, Status.FAILED), 0.0
    offered = _offered(pipeline, load_factor, emitted)
    capacity = pipeline.throughput
    processed = offered if offered is None or capacity is None else min(offered, capacity)
    utilization = status = None
    if offered is not None and capacity is not None:
        usage = ResourceUsage(offered, capacity)
        utilization, status = usage.ratio, classify(usage)
    ratio = 1.0 if pipeline.output_ratio is None else pipeline.output_ratio
    emits = None if processed is None else _scaled(processed, ratio)
    return PipelineFlow(pipeline.id, offered, processed, capacity, utilization, status), emits


def _offered(
    pipeline: Pipeline, load_factor: float, emitted: dict[str, float | None]
) -> float | None:
    """What reaches ``pipeline``: its arrival if it reads no other one, else what those emit."""
    if not pipeline.inputs:
        return None if pipeline.arrival is None else _scaled(pipeline.arrival, load_factor)
    total = 0.0
    for upstream in dict.fromkeys(item.pipeline for item in pipeline.inputs):
        rate = emitted[upstream]
        if rate is None:
            return None
        total += rate
    return total


def _scaled(rate: float, factor: float) -> float:
    """``rate * factor``, where nothing times anything, even infinity, is nothing."""
    return 0.0 if rate == 0 or factor == 0 else rate * factor


def _latencies(
    pipelines: list[Pipeline], down: Collection[str]
) -> dict[str, tuple[float, str | None]]:
    """For each pipeline still up, the seconds since its slowest path began and the pipeline before.

    A pipeline delivers ``latency`` seconds after the slowest of the pipelines it reads; when two
    are equally slow, the one declared first is the one before.
    """
    reached: dict[str, tuple[float, str | None]] = {}
    for pipeline in pipelines:
        if pipeline.id in down:
            continue
        before, via = 0.0, None
        for upstream in dict.fromkeys(item.pipeline for item in pipeline.inputs):
            if upstream in reached and (via is None or reached[upstream][0] > before):
                before, via = reached[upstream][0], upstream
        reached[pipeline.id] = ((pipeline.latency or 0.0) + before, via)
    return reached


def _bottleneck(flows: list[PipelineFlow]) -> PipelineFlow | None:
    """The pipeline using the largest part of its capacity, the first one if several tie."""
    busiest: PipelineFlow | None = None
    for flow in flows:
        if flow.utilization is None or flow.status is Status.FAILED:
            continue
        if busiest is None or (busiest.utilization or 0.0) < flow.utilization:
            busiest = flow
    return busiest


def _slowest_path(
    flows: list[PipelineFlow], reached: dict[str, tuple[float, str | None]]
) -> SlowestPath | None:
    """The slowest path to any pipeline still up; ``None`` when nothing adds any latency."""
    last: str | None = None
    for flow in flows:
        if flow.latency is not None and (last is None or reached[last][0] < flow.latency):
            last = flow.id
    if last is None or reached[last][0] <= 0:
        return None
    path = [last]
    while (before := reached[path[-1]][1]) is not None:
        path.append(before)
    return SlowestPath(path[::-1], reached[last][0])
