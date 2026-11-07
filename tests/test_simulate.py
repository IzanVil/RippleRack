from __future__ import annotations

import pytest

from ripplerack.capacity import ResourceUsage, Status, classify
from ripplerack.parser import LoadedDatacenter
from ripplerack.simulate import simulate
from tests.helpers import load_variant, without_flow


@pytest.mark.parametrize(
    ("used", "status"),
    [
        (0, Status.OK),
        (79, Status.OK),
        (80, Status.WARNING),
        (100, Status.WARNING),
        (101, Status.OVERLOADED),
    ],
)
def test_classify_thresholds(used: float, status: Status) -> None:
    assert classify(ResourceUsage(used, 100)) is status


def test_nominal_load_is_healthy(mini_dc: LoadedDatacenter) -> None:
    report = simulate(mini_dc.datacenter, mini_dc.graph)
    assert report.healthy
    srv_a1 = next(s for s in report.servers if s.id == "srv-a1")
    assert srv_a1.cpu.used == 20
    assert srv_a1.memory.used == 80


def test_load_surge_overloads() -> None:
    without = load_variant(without_flow)
    report = simulate(without.datacenter, without.graph, load_factor=1.5)
    assert set(report.overloaded) == {"rack-a", "srv-a2"}
    assert not report.healthy


def test_failure_cascades_and_frees_capacity(mini_dc: LoadedDatacenter) -> None:
    report = simulate(mini_dc.datacenter, mini_dc.graph, load_factor=1.5, failures=["srv-a2"])
    assert {n.id for n in report.unavailable} == {
        "spark",
        "orders-enriched",
        "revenue-daily",
        "dashboard",
    }
    statuses = {s.id: s.status for s in report.servers}
    assert statuses["srv-a2"] is Status.FAILED
    rack_a = next(r for r in report.racks if r.id == "rack-a")
    assert rack_a.power.used == pytest.approx(1.8)
    assert rack_a.status is Status.OK


def test_failed_service_frees_server_resources(mini_dc: LoadedDatacenter) -> None:
    report = simulate(mini_dc.datacenter, mini_dc.graph, failures=["kafka"])
    srv_a1 = next(s for s in report.servers if s.id == "srv-a1")
    assert srv_a1.cpu.used == 12
    assert "orders-ingest" in {n.id for n in report.unavailable}


def test_unknown_failure(mini_dc: LoadedDatacenter) -> None:
    with pytest.raises(KeyError):
        simulate(mini_dc.datacenter, mini_dc.graph, failures=["ghost"])


def test_negative_load(mini_dc: LoadedDatacenter) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        simulate(mini_dc.datacenter, mini_dc.graph, load_factor=-1)


def test_no_flow_without_declared_fields() -> None:
    without = load_variant(without_flow)
    assert simulate(without.datacenter, without.graph).flow is None


def test_flow_follows_the_load_and_the_failures(mini_dc: LoadedDatacenter) -> None:
    flowing = mini_dc
    surge = simulate(flowing.datacenter, flowing.graph, load_factor=1.5).flow
    assert surge is not None
    assert {flow.id: flow.status for flow in surge.pipelines}["orders-ingest"] is Status.OVERLOADED
    report = simulate(flowing.datacenter, flowing.graph, failures=["srv-a2"])
    assert report.flow is not None
    failed = {flow.id for flow in report.flow.pipelines if flow.status is Status.FAILED}
    assert failed == {"orders-enriched", "revenue-daily"}
    assert failed <= {node.id for node in report.unavailable}


def test_overloaded_pipelines_make_the_report_unhealthy(mini_dc: LoadedDatacenter) -> None:
    flowing = mini_dc
    report = simulate(flowing.datacenter, flowing.graph, load_factor=1.5)
    assert report.overloaded == ["rack-a", "srv-a2", "orders-ingest", "orders-enriched"]
    assert not report.healthy


def test_a_pipeline_at_warning_is_still_healthy(mini_dc: LoadedDatacenter) -> None:
    flowing = mini_dc
    report = simulate(flowing.datacenter, flowing.graph)
    assert report.flow is not None
    assert Status.WARNING in {flow.status for flow in report.flow.pipelines}
    assert report.healthy
