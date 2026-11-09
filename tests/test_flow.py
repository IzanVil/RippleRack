"""How much data flows through the pipelines, and what each one makes of it.

The numbers of the example are the ones of ``docs/concepts.md``: 400 records per second enter
``orders-ingest``, which feeds ``orders-enriched`` and ``customer-360``, and ``orders-enriched``
feeds ``revenue-daily``. Everything else is built from small datacenters of a few pipelines.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ripplerack.capacity import Status
from ripplerack.flow import FlowReport, PipelineFlow, SlowestPath, analyze_flow
from ripplerack.models import Datacenter
from ripplerack.parser import parse_datacenter
from tests.helpers import without_flow


def example(raw_mini: dict[str, Any], drop: tuple[str, ...] = ()) -> Datacenter:
    """The mini datacenter with the numbers of the example, minus the fields in ``drop``."""
    data = copy.deepcopy(raw_mini)
    if drop:
        without_flow(data, *drop)
    return parse_datacenter(data).datacenter


def small(*pipelines: dict[str, Any]) -> Datacenter:
    """A datacenter of one service and the given pipelines (``id`` and what they declare)."""
    data = {
        "name": "small",
        "racks": [
            {
                "id": "rack",
                "power_capacity_kw": 10,
                "servers": [
                    {
                        "id": "server",
                        "cpu_cores": 8,
                        "memory_gb": 8,
                        "power_kw": 1,
                        "services": [{"id": "service", "cpu_cores": 1, "memory_gb": 1}],
                    }
                ],
            }
        ],
        "pipelines": [
            {"runs_on": "service", "schema": {"name": p["id"], "version": "1.0.0"}, **p}
            for p in pipelines
        ],
    }
    return parse_datacenter(data).datacenter


def flows(
    datacenter: Datacenter, load: float = 1.0, down: tuple[str, ...] = ()
) -> dict[str, PipelineFlow]:
    report = analyze_flow(datacenter, load, down)
    assert report is not None
    return {flow.id: flow for flow in report.pipelines}


def test_example_at_nominal_load(raw_mini: dict[str, Any]) -> None:
    result = flows(example(raw_mini))
    assert [flow.offered for flow in result.values()] == [400, 400, 400, 400]
    assert [flow.processed for flow in result.values()] == [400, 400, 400, 400]
    assert [flow.utilization for flow in result.values()] == pytest.approx(
        [0.8, 400 / 450, 400 / 600, 0.5]
    )
    assert [flow.status for flow in result.values()] == [
        Status.WARNING,
        Status.WARNING,
        Status.OK,
        Status.OK,
    ]


def test_example_under_surge(raw_mini: dict[str, Any]) -> None:
    result = flows(example(raw_mini), load=1.5)
    assert [flow.offered for flow in result.values()] == [600, 500, 450, 500]
    assert [flow.processed for flow in result.values()] == [500, 450, 450, 500]
    assert [flow.status for flow in result.values()] == [
        Status.OVERLOADED,
        Status.OVERLOADED,
        Status.OK,
        Status.OK,
    ]


def test_nothing_declared_gives_no_report(raw_mini: dict[str, Any]) -> None:
    data = copy.deepcopy(raw_mini)
    without_flow(data)
    assert analyze_flow(parse_datacenter(data).datacenter, 1.0, ()) is None


def test_the_pipelines_come_in_the_order_the_data_flows(raw_mini: dict[str, Any]) -> None:
    data = copy.deepcopy(raw_mini)
    data["pipelines"].reverse()
    report = analyze_flow(parse_datacenter(data).datacenter, 1.0, ())
    assert report is not None
    ids = [flow.id for flow in report.pipelines]
    assert ids.index("orders-ingest") < ids.index("orders-enriched") < ids.index("revenue-daily")
    assert ids.index("orders-ingest") < ids.index("customer-360")


def test_an_unknown_rate_propagates(raw_mini: dict[str, Any]) -> None:
    result = flows(example(raw_mini, drop=("arrival",)))
    for flow in result.values():
        assert (flow.offered, flow.processed, flow.utilization, flow.status) == (None,) * 4


def test_fan_in_sums_and_fan_out_copies() -> None:
    fan_in = flows(
        small(
            {"id": "a", "arrival": 100},
            {"id": "b", "arrival": 50},
            {"id": "c", "inputs": ["a", "b"]},
        )
    )
    assert fan_in["c"].offered == 150
    fan_out = flows(
        small(
            {"id": "a", "arrival": 100},
            {"id": "b", "inputs": ["a"]},
            {"id": "c", "inputs": ["a"]},
        )
    )
    assert (fan_out["b"].offered, fan_out["c"].offered) == (100, 100)


def test_a_diamond_adds_what_arrives_by_both_paths() -> None:
    result = flows(
        small(
            {"id": "source", "arrival": 100},
            {"id": "left", "inputs": ["source"]},
            {"id": "right", "inputs": ["source"]},
            {"id": "sink", "inputs": ["left", "right"]},
        )
    )
    assert result["sink"].offered == 200


def test_the_same_input_listed_twice_counts_once() -> None:
    result = flows(
        small({"id": "a", "arrival": 100}, {"id": "b", "inputs": ["a", "a"]}),
    )
    assert result["b"].offered == 100


def test_an_aggregation_emits_fewer_records_than_it_reads() -> None:
    result = flows(
        small(
            {"id": "a", "arrival": 400, "output_ratio": 0.001},
            {"id": "b", "inputs": ["a"]},
        )
    )
    assert result["b"].offered == pytest.approx(0.4)


def test_an_output_ratio_of_zero_is_a_known_zero_not_an_unknown() -> None:
    result = flows(
        small(
            {"id": "a", "arrival": 400, "output_ratio": 0},
            {"id": "b", "inputs": ["a"], "throughput": 10},
        )
    )
    assert result["b"].offered == 0
    assert result["b"].utilization == 0
    assert result["b"].status is Status.OK


def test_a_bottleneck_does_not_spread_downstream() -> None:
    result = flows(
        small(
            {"id": "a", "arrival": 100, "throughput": 40},
            {"id": "b", "inputs": ["a"], "throughput": 1000},
        )
    )
    assert (result["a"].offered, result["a"].processed) == (100, 40)
    assert result["a"].status is Status.OVERLOADED
    assert result["b"].offered == 40


def test_a_failed_pipeline_emits_nothing_and_the_others_are_still_computed(
    raw_mini: dict[str, Any],
) -> None:
    result = flows(example(raw_mini), down=("orders-enriched", "revenue-daily"))
    for failed in ("orders-enriched", "revenue-daily"):
        flow = result[failed]
        assert flow.status is Status.FAILED
        assert (flow.offered, flow.processed, flow.utilization) == (None, None, None)
    assert result["orders-enriched"].capacity == 450
    assert result["orders-ingest"].offered == 400
    assert result["customer-360"].offered == 400


def test_what_reads_a_failed_pipeline_is_offered_nothing() -> None:
    result = flows(
        small({"id": "a", "arrival": 100}, {"id": "b", "inputs": ["a"], "throughput": 10}),
        down=("a",),
    )
    assert result["a"].status is Status.FAILED
    assert result["b"].offered == 0
    assert result["b"].utilization == 0


def test_no_load_is_a_known_zero() -> None:
    result = flows(small({"id": "a", "arrival": 100, "throughput": 50}), load=0)
    assert (result["a"].offered, result["a"].utilization) == (0, 0)
    assert result["a"].status is Status.OK


def test_an_infinite_load_does_not_turn_a_zero_into_nan() -> None:
    result = flows(
        small(
            {"id": "idle", "arrival": 0, "throughput": 5},
            {"id": "busy", "arrival": 1, "output_ratio": 0},
            {"id": "after", "inputs": ["busy"]},
        ),
        load=math.inf,
    )
    assert result["idle"].offered == 0
    assert result["after"].offered == 0
    assert result["busy"].offered == math.inf


def test_a_pipeline_without_throughput_has_no_capacity_and_passes_everything() -> None:
    flow = flows(small({"id": "a", "arrival": 100}))["a"]
    assert (flow.capacity, flow.utilization, flow.status) == (None, None, None)
    assert flow.processed == flow.offered == 100


def reported(datacenter: Datacenter, load: float = 1.0, down: tuple[str, ...] = ()) -> FlowReport:
    report = analyze_flow(datacenter, load, down)
    assert report is not None
    return report


def test_end_to_end_latency_of_the_example(raw_mini: dict[str, Any]) -> None:
    report = reported(example(raw_mini))
    assert [flow.latency for flow in report.pipelines] == [2, 32, 332, 7]
    assert report.slowest_path == SlowestPath(
        ["orders-ingest", "orders-enriched", "revenue-daily"], 332
    )


def test_latency_does_not_need_any_rate() -> None:
    report = reported(small({"id": "a", "latency": 3}, {"id": "b", "inputs": ["a"], "latency": 4}))
    assert [flow.latency for flow in report.pipelines] == [3, 7]
    assert [flow.offered for flow in report.pipelines] == [None, None]
    assert report.bottleneck is None
    assert report.slowest_path == SlowestPath(["a", "b"], 7)


def test_a_diamond_takes_the_longest_path() -> None:
    report = reported(
        small(
            {"id": "source", "latency": 1},
            {"id": "left", "inputs": ["source"], "latency": 10},
            {"id": "right", "inputs": ["source"], "latency": 40},
            {"id": "sink", "inputs": ["left", "right"], "latency": 1},
        )
    )
    assert report.slowest_path == SlowestPath(["source", "right", "sink"], 42)


def test_a_tie_goes_to_the_input_declared_first() -> None:
    report = reported(
        small(
            {"id": "a", "latency": 5},
            {"id": "b", "latency": 5},
            {"id": "c", "inputs": ["a", "b"], "latency": 1},
        )
    )
    assert report.slowest_path == SlowestPath(["a", "c"], 6)


def test_the_slowest_path_leaves_out_what_failed(raw_mini: dict[str, Any]) -> None:
    report = reported(example(raw_mini), down=("orders-enriched", "revenue-daily"))
    assert report.slowest_path == SlowestPath(["orders-ingest", "customer-360"], 7)
    latencies = {flow.id: flow.latency for flow in report.pipelines}
    assert latencies["orders-enriched"] is None
    assert latencies["revenue-daily"] is None


def test_without_latency_there_is_no_slowest_path() -> None:
    report = reported(small({"id": "a", "arrival": 10, "throughput": 20}))
    assert report.slowest_path is None


def test_the_bottleneck_is_the_busiest_pipeline(raw_mini: dict[str, Any]) -> None:
    datacenter = example(raw_mini)
    nominal = reported(datacenter).bottleneck
    assert nominal is not None
    assert nominal.id == "orders-enriched"
    surge = reported(datacenter, load=1.5).bottleneck
    assert surge is not None
    assert surge.id == "orders-ingest"
    assert surge.utilization == pytest.approx(1.2)


def test_with_every_pipeline_down_there_is_nothing_to_point_at(raw_mini: dict[str, Any]) -> None:
    report = reported(example(raw_mini), down=tuple(p["id"] for p in raw_mini["pipelines"]))
    assert report.bottleneck is None
    assert report.slowest_path is None
    assert {flow.status for flow in report.pipelines} == {Status.FAILED}


# ----------------------------------------------------------------------------- properties

RATE = st.floats(min_value=0, max_value=1e6)
CAPACITY = st.none() | st.floats(min_value=1e-3, max_value=1e6)
RATIO = st.none() | st.floats(min_value=0, max_value=10)
STAGES = st.lists(st.tuples(CAPACITY, RATIO), min_size=1, max_size=5)


def chain(arrival: float, stages: list[tuple[float | None, float | None]]) -> Datacenter:
    """A line of pipelines, each reading the one before; the first one receives ``arrival``."""
    pipelines: list[dict[str, Any]] = []
    for index, (throughput, ratio) in enumerate(stages):
        pipeline: dict[str, Any] = {"id": f"p{index}"}
        if index == 0:
            pipeline["arrival"] = arrival
        else:
            pipeline["inputs"] = [f"p{index - 1}"]
        if throughput is not None:
            pipeline["throughput"] = throughput
        if ratio is not None:
            pipeline["output_ratio"] = ratio
        pipelines.append(pipeline)
    return small(*pipelines)


def report_of(datacenter: Datacenter, load: float) -> FlowReport:
    report = analyze_flow(datacenter, load, ())
    assert report is not None
    return report


@given(arrival=RATE, stages=STAGES, load=st.floats(min_value=0, max_value=100))
def test_a_pipeline_never_processes_more_than_it_is_offered_or_can(
    arrival: float, stages: list[tuple[float | None, float | None]], load: float
) -> None:
    for flow in report_of(chain(arrival, stages), load).pipelines:
        assert flow.offered is not None
        assert flow.processed is not None
        assert flow.processed <= flow.offered
        if flow.capacity is not None:
            assert flow.processed <= flow.capacity


@given(
    arrival=RATE,
    stages=STAGES,
    loads=st.tuples(st.floats(min_value=0, max_value=100), st.floats(min_value=0, max_value=100)),
)
def test_more_load_never_offers_less(
    arrival: float, stages: list[tuple[float | None, float | None]], loads: tuple[float, float]
) -> None:
    low, high = sorted(loads)
    datacenter = chain(arrival, stages)
    for before, after in zip(
        report_of(datacenter, low).pipelines, report_of(datacenter, high).pipelines, strict=True
    ):
        assert before.offered is not None
        assert after.offered is not None
        assert before.offered <= after.offered


@given(latencies=st.lists(st.floats(min_value=0, max_value=1e4), min_size=1, max_size=6))
def test_latency_never_drops_below_the_own_one_or_the_one_of_an_input(
    latencies: list[float],
) -> None:
    pipelines: list[dict[str, Any]] = [
        {"id": f"p{index}", "latency": seconds, **({"inputs": [f"p{index - 1}"]} if index else {})}
        for index, seconds in enumerate(latencies)
    ]
    reached = [flow.latency for flow in reported(small(*pipelines)).pipelines]
    for index, seconds in enumerate(latencies):
        latency = reached[index]
        assert latency is not None
        assert latency >= seconds
        if index:
            before = reached[index - 1]
            assert before is not None
            assert latency >= before
