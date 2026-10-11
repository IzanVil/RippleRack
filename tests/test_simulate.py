from __future__ import annotations

import pytest

from ripplerack.parser import LoadedDatacenter
from ripplerack.simulate import ResourceUsage, Status, classify, simulate


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


def test_load_surge_overloads(mini_dc: LoadedDatacenter) -> None:
    report = simulate(mini_dc.datacenter, mini_dc.graph, load_factor=1.5)
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
