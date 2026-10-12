from __future__ import annotations

from pathlib import Path

import pytest

from ripplerack.impact import (
    ImpactReport,
    Severity,
    analyze_diff,
    analyze_schema_change,
    blast_radius,
)
from ripplerack.models import Schema
from ripplerack.parser import LoadedDatacenter, load_schema
from ripplerack.semver import ChangeLevel, diff_schemas


def run(mini_dc: LoadedDatacenter, schema: Schema, pipeline: str = "orders-ingest") -> ImpactReport:
    return analyze_schema_change(mini_dc.datacenter, mini_dc.graph, pipeline, schema)


def with_changes(
    schema: Schema, *, version: str, drop: str | None = None, **extra: object
) -> Schema:
    fields = [f.model_dump() for f in schema.fields if f.name != drop]
    if extra:
        fields.append({"type": "string", **extra})
    return Schema.model_validate({"name": schema.name, "version": version, "fields": fields})


class TestBlastRadius:
    def test_rack_failure_reaches_everything_hosted(self, mini_dc: LoadedDatacenter) -> None:
        ids = {node.id for node in blast_radius(mini_dc.graph, "rack-b")}
        assert ids == {"srv-b1", "api", "dashboard"}

    def test_sorted_by_distance_with_paths(self, mini_dc: LoadedDatacenter) -> None:
        nodes = blast_radius(mini_dc.graph, "orders-ingest")
        distances = [node.distance for node in nodes]
        assert distances == sorted(distances)
        dashboard = next(node for node in nodes if node.id == "dashboard")
        assert dashboard.path == ["orders-ingest", "orders-enriched", "revenue-daily", "dashboard"]
        assert dashboard.kind == "service"

    def test_leaf_has_no_impact(self, mini_dc: LoadedDatacenter) -> None:
        assert blast_radius(mini_dc.graph, "dashboard") == []

    def test_unknown_node(self, mini_dc: LoadedDatacenter) -> None:
        with pytest.raises(KeyError):
            blast_radius(mini_dc.graph, "ghost")


class TestAnalyzeSchemaChange:
    def test_no_change(self, mini_dc: LoadedDatacenter, orders_schema: Schema) -> None:
        report = run(mini_dc, orders_schema)
        assert report.severity is Severity.NONE
        assert report.broken_consumers == []
        assert {n.id for n in report.affected} == {
            "orders-enriched",
            "customer-360",
            "revenue-daily",
            "api",
            "dashboard",
        }

    def test_compatible_addition_is_low(
        self, mini_dc: LoadedDatacenter, orders_schema: Schema
    ) -> None:
        new = with_changes(orders_schema, version="1.3.0", name="channel", nullable=True)
        report = run(mini_dc, new)
        assert report.diff.level is ChangeLevel.MINOR
        assert report.severity is Severity.LOW
        assert report.broken_consumers == []

    def test_required_addition_breaks_nobody(
        self, mini_dc: LoadedDatacenter, orders_schema: Schema
    ) -> None:
        new = with_changes(orders_schema, version="2.0.0", name="tenant_id")
        report = run(mini_dc, new)
        assert report.has_breaking_changes
        assert report.broken_consumers == []
        assert report.severity is Severity.MEDIUM

    def test_unread_field_only_breaks_full_readers(
        self, mini_dc: LoadedDatacenter, orders_schema: Schema
    ) -> None:
        # orders-enriched lists its fields and does not read coupon_code;
        # customer-360 reads everything, so it breaks. Its only dependent is a service.
        new = with_changes(orders_schema, version="2.0.0", drop="coupon_code")
        report = run(mini_dc, new)
        assert report.broken_ids == {"customer-360"}
        assert report.broken_consumers[0].fields == ["coupon_code"]
        assert report.at_risk == ["api"]
        assert report.severity is Severity.HIGH

    def test_cascading_break_is_critical(
        self, mini_dc: LoadedDatacenter, orders_schema: Schema
    ) -> None:
        new = with_changes(orders_schema, version="2.0.0", drop="amount")
        report = run(mini_dc, new)
        assert report.broken_ids == {"orders-enriched", "customer-360"}
        assert set(report.at_risk) == {"revenue-daily", "dashboard", "api"}
        assert report.severity is Severity.CRITICAL

    def test_change_on_leaf_pipeline(self, mini_dc: LoadedDatacenter) -> None:
        schema = mini_dc.datacenter.pipeline("revenue-daily").schema_
        new = with_changes(schema, version="3.0.0", drop="revenue_eur")
        report = run(mini_dc, new, pipeline="revenue-daily")
        assert [n.id for n in report.affected] == ["dashboard"]
        assert report.broken_consumers == []
        assert report.severity is Severity.MEDIUM

    def test_unknown_pipeline(self, mini_dc: LoadedDatacenter, orders_schema: Schema) -> None:
        with pytest.raises(KeyError):
            run(mini_dc, orders_schema, pipeline="ghost")

    @pytest.mark.parametrize(
        ("file", "severity", "consistent"),
        [
            ("orders_v1_3_0.yaml", Severity.LOW, True),
            ("orders_v2.yaml", Severity.CRITICAL, True),
            ("orders_sneaky_patch.yaml", Severity.HIGH, False),
        ],
    )
    def test_example_changes(
        self,
        mini_dc: LoadedDatacenter,
        examples_dir: Path,
        file: str,
        severity: Severity,
        consistent: bool,
    ) -> None:
        report = run(mini_dc, load_schema(examples_dir / "changes" / file))
        assert report.severity is severity
        assert report.diff.version_is_consistent is consistent


class TestAnalyzeDiff:
    @pytest.mark.parametrize(
        "change", ["orders_v1_3_0.yaml", "orders_v2.yaml", "orders_sneaky_patch.yaml"]
    )
    def test_gives_the_same_result_as_analyze_schema_change(
        self, mini_dc: LoadedDatacenter, examples_dir: Path, change: str
    ) -> None:
        new = load_schema(examples_dir / "changes" / change)
        old = mini_dc.datacenter.pipeline("orders-ingest").schema_
        expected = run(mini_dc, new)
        actual = analyze_diff(
            mini_dc.datacenter, mini_dc.graph, "orders-ingest", diff_schemas(old, new)
        )
        assert actual == expected

    def test_ignored_consumers_are_never_broken(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        new = load_schema(examples_dir / "changes" / "orders_v2.yaml")
        old = mini_dc.datacenter.pipeline("orders-ingest").schema_
        report = analyze_diff(
            mini_dc.datacenter,
            mini_dc.graph,
            "orders-ingest",
            diff_schemas(old, new),
            ignore_consumers={"customer-360"},
        )
        assert report.broken_ids == {"orders-enriched"}
        # api is only downstream of the ignored consumer, so it is no longer at risk.
        assert set(report.at_risk) == {"revenue-daily", "dashboard"}
        assert report.severity is Severity.CRITICAL
        # Ignoring a consumer does not hide it from the blast radius.
        assert "customer-360" in {node.id for node in report.affected}
