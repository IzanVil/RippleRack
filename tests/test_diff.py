from __future__ import annotations

from typing import Any

import pytest

from ripplerack.diff import (
    AttributeChange,
    ComponentRef,
    DatacenterDiff,
    DependencyChange,
    DependencyRef,
    PossibleRename,
    RemovedWithDependents,
    WarningCode,
    diff_datacenters,
)
from ripplerack.graph import NodeKind
from ripplerack.impact import Severity
from ripplerack.models import DependencyKind
from ripplerack.parser import LoadedDatacenter, load_datacenter
from ripplerack.semver import ChangeLevel, diff_schemas
from tests.helpers import (
    EXAMPLES,
    load_variant,
    pipeline_of,
    rack_of,
    rename_kafka,
    server_of,
    set_orders_schema,
)


def changes_of(diff: DatacenterDiff, component_id: str) -> dict[str, tuple[object, object]]:
    """Attribute changes of a modified component as ``{attribute: (before, after)}``."""
    for component in diff.modified:
        if component.id == component_id:
            return {c.attribute: (c.before, c.after) for c in component.changes}
    raise AssertionError(f"{component_id} is not reported as modified")


def warning_codes(diff: DatacenterDiff) -> list[WarningCode]:
    return [warning.code for warning in diff.warnings]


# --- mutations of the raw mini datacenter ---------------------------------------------


def add_service(data: dict[str, Any]) -> None:
    server_of(data, "srv-b1")["services"].append(
        {"id": "redis", "cpu_cores": 2, "memory_gb": 8, "description": "Session cache"}
    )


def remove_dashboard(data: dict[str, Any]) -> None:
    server = server_of(data, "srv-b1")
    server["services"] = [s for s in server["services"] if s["id"] != "dashboard"]
    data["dependencies"] = [d for d in data["dependencies"] if d["source"] != "dashboard"]


def retype_amount(data: dict[str, Any]) -> None:
    schema = pipeline_of(data, "orders-ingest")["schema"]
    schema["version"] = "2.0.0"
    for field in schema["fields"]:
        if field["name"] == "amount":
            field["type"] = "integer"


def shuffle(data: dict[str, Any]) -> None:
    data["racks"].reverse()
    for rack in data["racks"]:
        rack["servers"].reverse()
        for server in rack["servers"]:
            server["services"].reverse()
    data["pipelines"].reverse()
    data["dependencies"].reverse()
    pipeline_of(data, "orders-enriched")["inputs"][0]["fields"].reverse()


class TestIdenticalInputs:
    def test_a_file_has_no_differences_with_itself(self, mini_dc: LoadedDatacenter) -> None:
        diff = diff_datacenters(mini_dc, mini_dc)
        assert not diff.has_differences
        assert diff.severity is Severity.NONE
        assert diff.warnings == []
        assert diff.broken_consumers == []

    def test_reordering_is_not_a_difference(self, mini_dc: LoadedDatacenter) -> None:
        diff = diff_datacenters(mini_dc, load_variant(shuffle))
        assert not diff.has_differences
        assert diff.severity is Severity.NONE


class TestComponents:
    def test_added_component(self, mini_dc: LoadedDatacenter) -> None:
        diff = diff_datacenters(mini_dc, load_variant(add_service))
        assert diff.added == [ComponentRef("redis", NodeKind.SERVICE, "srv-b1")]
        assert diff.removed == []
        assert diff.modified == []
        assert diff.severity is Severity.LOW

    def test_removed_component_takes_its_dependency_with_it(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        diff = diff_datacenters(mini_dc, load_variant(remove_dashboard))
        assert diff.removed == [ComponentRef("dashboard", NodeKind.SERVICE, "srv-b1")]
        assert diff.dependencies_removed == [
            DependencyRef("dashboard", "revenue-daily", DependencyKind.DATA)
        ]
        assert diff.removed_with_dependents == []
        assert diff.severity is Severity.LOW

    def test_modified_attributes_report_before_and_after(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            rack_of(data, "rack-a")["power_capacity_kw"] = 3.2
            server_of(data, "srv-a1")["cpu_cores"] = 64
            server_of(data, "srv-a1")["services"][1]["description"] = "Message bus"
            pipeline_of(data, "customer-360")["runs_on"] = "spark"

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.added == []
        assert diff.removed == []
        assert [(c.id, c.kind) for c in diff.modified] == [
            ("rack-a", NodeKind.RACK),
            ("srv-a1", NodeKind.SERVER),
            ("kafka", NodeKind.SERVICE),
            ("customer-360", NodeKind.PIPELINE),
        ]
        assert changes_of(diff, "rack-a") == {"power_capacity_kw": (2.8, 3.2)}
        assert changes_of(diff, "srv-a1") == {"cpu_cores": (32.0, 64.0)}
        assert changes_of(diff, "kafka") == {"description": ("Event broker", "Message bus")}
        assert changes_of(diff, "customer-360") == {"runs_on": ("postgres", "spark")}

    def test_moving_a_server_to_another_rack_is_a_modification(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        def mutate(data: dict[str, Any]) -> None:
            moved = rack_of(data, "rack-a")["servers"].pop(1)
            rack_of(data, "rack-b")["servers"].append(moved)

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.added == diff.removed == []
        assert changes_of(diff, "srv-a2") == {"rack": ("rack-a", "rack-b")}
        assert [c.id for c in diff.modified] == ["srv-a2"]

    def test_changed_inputs_are_modifications_but_their_order_is_not(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        def mutate(data: dict[str, Any]) -> None:
            fields = pipeline_of(data, "orders-enriched")["inputs"][0]["fields"]
            fields.remove("currency")

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        before, after = changes_of(diff, "orders-enriched")["inputs"]
        assert before == [
            {
                "pipeline": "orders-ingest",
                "fields": ["amount", "created_at", "currency", "customer_id", "order_id"],
            }
        ]
        assert after == [
            {
                "pipeline": "orders-ingest",
                "fields": ["amount", "created_at", "customer_id", "order_id"],
            }
        ]

    def test_an_id_that_changes_kind_is_removed_and_added(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            server = server_of(data, "srv-b1")
            server["services"] = [s for s in server["services"] if s["id"] != "dashboard"]
            data["pipelines"].append(
                {
                    "id": "dashboard",
                    "runs_on": "spark",
                    "schema": {"name": "dash", "version": "1.0.0", "fields": []},
                }
            )

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.removed == [ComponentRef("dashboard", NodeKind.SERVICE, "srv-b1")]
        assert diff.added == [ComponentRef("dashboard", NodeKind.PIPELINE, "spark")]
        assert diff.modified == []
        assert warning_codes(diff) == [WarningCode.COMPONENT_KIND_CHANGED]

    def test_results_are_ordered_by_kind_then_id(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            add_service(data)
            rack_of(data, "rack-b")["servers"].append(
                {"id": "srv-b0", "cpu_cores": 1, "memory_gb": 1, "power_kw": 0}
            )
            data["pipelines"].append(
                {
                    "id": "aaa-pipeline",
                    "runs_on": "spark",
                    "schema": {"name": "a", "version": "1.0.0", "fields": []},
                }
            )

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert [(r.kind, r.id) for r in diff.added] == [
            (NodeKind.SERVER, "srv-b0"),
            (NodeKind.SERVICE, "redis"),
            (NodeKind.PIPELINE, "aaa-pipeline"),
        ]


class TestMetadata:
    def test_description_change(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["description"] = "Something else."

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.metadata == [
            AttributeChange(
                "description",
                "Two racks running an e-commerce order analytics stack.",
                "Something else.",
            )
        ]
        assert diff.warnings == []
        assert diff.severity is Severity.LOW

    def test_name_change_warns_that_different_datacenters_may_be_compared(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["name"] = "another-datacenter"

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.metadata == [AttributeChange("name", "mini-datacenter", "another-datacenter")]
        assert warning_codes(diff) == [WarningCode.DATACENTER_NAME_CHANGED]
        assert (diff.base_name, diff.head_name) == ("mini-datacenter", "another-datacenter")


class TestDependencies:
    def test_added_removed_and_modified(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["dependencies"].append({"source": "api", "target": "kafka", "kind": "network"})
            data["dependencies"] = [d for d in data["dependencies"] if d["source"] != "dashboard"]
            for dependency in data["dependencies"]:
                if dependency["source"] == "spark":
                    dependency["kind"] = "data"

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.dependencies_added == [DependencyRef("api", "kafka", DependencyKind.NETWORK)]
        assert diff.dependencies_removed == [
            DependencyRef("dashboard", "revenue-daily", DependencyKind.DATA)
        ]
        assert diff.dependencies_modified == [
            DependencyChange("spark", "kafka", DependencyKind.NETWORK, DependencyKind.DATA)
        ]
        assert diff.severity is Severity.LOW


def add_servers(*ids: str) -> Any:
    def mutate(data: dict[str, Any]) -> None:
        for server_id in ids:
            rack_of(data, "rack-b")["servers"].append(
                {"id": server_id, "cpu_cores": 8, "memory_gb": 32, "power_kw": 0.5}
            )

    return mutate


class TestRenameHints:
    def test_unambiguous_rename_is_hinted_but_still_reported_as_remove_and_add(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        diff = diff_datacenters(mini_dc, load_variant(rename_kafka))
        assert [r.id for r in diff.removed] == ["kafka"]
        assert [r.id for r in diff.added] == ["broker"]
        assert diff.possible_renames == [PossibleRename(NodeKind.SERVICE, "kafka", "broker")]
        assert changes_of(diff, "orders-ingest") == {"runs_on": ("kafka", "broker")}
        assert diff.dependencies_removed == [
            DependencyRef("spark", "kafka", DependencyKind.NETWORK)
        ]
        assert diff.dependencies_added == [DependencyRef("spark", "broker", DependencyKind.NETWORK)]

    def test_a_renamed_component_is_still_flagged_for_review(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        diff = diff_datacenters(mini_dc, load_variant(rename_kafka))
        assert diff.removed_with_dependents == [
            RemovedWithDependents("kafka", NodeKind.SERVICE, ["orders-ingest", "spark"])
        ]
        assert diff.severity is Severity.MEDIUM

    def test_a_single_identical_pair_is_hinted(self) -> None:
        diff = diff_datacenters(
            load_variant(add_servers("srv-x1")), load_variant(add_servers("srv-y1"))
        )
        assert diff.possible_renames == [PossibleRename(NodeKind.SERVER, "srv-x1", "srv-y1")]

    def test_ambiguous_candidates_are_not_paired(self) -> None:
        diff = diff_datacenters(
            load_variant(add_servers("srv-x1", "srv-x2")),
            load_variant(add_servers("srv-y1", "srv-y2")),
        )
        assert len(diff.removed) == len(diff.added) == 2
        assert diff.possible_renames == []

    def test_different_specs_are_not_paired(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            remove_dashboard(data)
            server_of(data, "srv-b1")["services"].append(
                {"id": "dashboard-v2", "cpu_cores": 99, "memory_gb": 8}
            )

        assert diff_datacenters(mini_dc, load_variant(mutate)).possible_renames == []


class TestSchemaChanges:
    @pytest.fixture
    def v2(self) -> LoadedDatacenter:
        return load_datacenter(EXAMPLES / "mini_datacenter_v2.yaml")

    def test_schema_comparison_is_the_semver_engine(
        self, mini_dc: LoadedDatacenter, v2: LoadedDatacenter
    ) -> None:
        diff = diff_datacenters(mini_dc, v2)
        [report] = diff.schema_impacts
        old = mini_dc.datacenter.pipeline("orders-ingest").schema_
        new = v2.datacenter.pipeline("orders-ingest").schema_
        assert report.diff.changes == diff_schemas(old, new).changes
        assert report.diff.level is ChangeLevel.MAJOR

    def test_consumer_adapted_in_head_is_fine_but_untouched_reader_breaks(
        self, mini_dc: LoadedDatacenter, v2: LoadedDatacenter
    ) -> None:
        diff = diff_datacenters(mini_dc, v2)
        assert diff.broken_consumers == ["customer-360"]
        [report] = diff.schema_impacts
        assert report.at_risk == ["api"]
        assert report.severity is Severity.HIGH
        assert diff.severity is Severity.HIGH

    def test_consumers_added_in_head_are_never_broken(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            set_orders_schema(data, "2.0.0", drop="amount")
            pipeline_of(data, "orders-enriched")["inputs"][0]["fields"].remove("amount")
            data["pipelines"].append(
                {
                    "id": "audit",
                    "runs_on": "postgres",
                    "inputs": ["orders-ingest"],  # reads everything, written against the new schema
                    "schema": {"name": "audit", "version": "1.0.0", "fields": []},
                }
            )

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.broken_consumers == ["customer-360"]
        [report] = diff.schema_impacts
        assert "audit" in {node.id for node in report.affected}

    def test_consumers_removed_in_head_are_not_broken(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            set_orders_schema(data, "2.0.0", drop="amount")
            pipeline_of(data, "orders-enriched")["inputs"][0]["fields"].remove("amount")
            data["pipelines"] = [p for p in data["pipelines"] if p["id"] != "customer-360"]
            data["dependencies"] = [
                d for d in data["dependencies"] if d["target"] != "customer-360"
            ]

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.broken_consumers == []
        assert diff.schema_impacts[0].severity is Severity.MEDIUM

    def test_changing_fields_marks_the_pipeline_as_modified_even_without_a_version_bump(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        def mutate(data: dict[str, Any]) -> None:
            set_orders_schema(data, "1.2.0", name="sales_channel", nullable=True)

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert set(changes_of(diff, "orders-ingest")) == {"schema.fields"}
        assert len(diff.schema_impacts) == 1
        assert warning_codes(diff) == [WarningCode.SCHEMA_VERSION_TOO_LOW]

    def test_a_version_only_bump_is_a_difference_without_schema_changes(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        def mutate(data: dict[str, Any]) -> None:
            pipeline_of(data, "orders-ingest")["schema"]["version"] = "1.2.1"

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert changes_of(diff, "orders-ingest") == {"schema.version": ("1.2.0", "1.2.1")}
        assert diff.schema_impacts == []
        assert diff.warnings == []
        assert diff.severity is Severity.LOW

    def test_an_understated_version_warns(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            set_orders_schema(data, "1.2.1", drop="coupon_code")

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        [warning] = diff.warnings
        assert warning.code is WarningCode.SCHEMA_VERSION_TOO_LOW
        assert "orders-ingest" in warning.message
        assert "2.0.0" in warning.message

    def test_a_version_that_goes_backwards_warns(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            pipeline_of(data, "orders-ingest")["schema"]["version"] = "1.1.0"

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        [warning] = diff.warnings
        assert warning.code is WarningCode.SCHEMA_VERSION_TOO_LOW
        assert "backwards" in warning.message

    def test_the_head_topology_decides_what_is_downstream(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            set_orders_schema(data, "1.3.0", name="sales_channel", nullable=True)
            data["dependencies"] = [
                d for d in data["dependencies"] if d["target"] != "customer-360"
            ]

        [report] = diff_datacenters(mini_dc, load_variant(mutate)).schema_impacts
        assert "api" not in {node.id for node in report.affected}


class TestSeverity:
    def test_compatible_schema_change_is_low(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            set_orders_schema(data, "1.3.0", name="sales_channel", nullable=True)

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.schema_impacts[0].diff.level is ChangeLevel.MINOR
        assert diff.severity is Severity.LOW

    def test_breaking_contract_without_broken_consumers_is_medium(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        def mutate(data: dict[str, Any]) -> None:
            set_orders_schema(data, "2.0.0", name="tenant_id")

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.broken_consumers == []
        assert diff.severity is Severity.MEDIUM

    def test_removing_a_component_that_others_still_use_is_medium(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        def mutate(data: dict[str, Any]) -> None:
            pipeline_of(data, "orders-ingest")["runs_on"] = "spark"
            server = server_of(data, "srv-a1")
            server["services"] = [s for s in server["services"] if s["id"] != "kafka"]
            data["dependencies"] = [d for d in data["dependencies"] if d["target"] != "kafka"]

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert diff.removed_with_dependents == [
            RemovedWithDependents("kafka", NodeKind.SERVICE, ["orders-ingest", "spark"])
        ]
        assert diff.severity is Severity.MEDIUM

    def test_removing_a_whole_branch_does_not_flag_what_went_with_it(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        def mutate(data: dict[str, Any]) -> None:
            remove_dashboard(data)
            data["pipelines"] = [p for p in data["pipelines"] if p["id"] != "revenue-daily"]

        diff = diff_datacenters(mini_dc, load_variant(mutate))
        assert {r.id for r in diff.removed} == {"dashboard", "revenue-daily"}
        assert diff.removed_with_dependents == []
        assert diff.severity is Severity.LOW

    def test_a_breaking_change_that_cascades_is_critical(self, mini_dc: LoadedDatacenter) -> None:
        diff = diff_datacenters(mini_dc, load_variant(retype_amount))
        assert diff.broken_consumers == ["customer-360", "orders-enriched"]
        assert diff.severity is Severity.CRITICAL

    def test_severity_is_the_highest_of_its_parts(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            add_service(data)  # low on its own
            retype_amount(data)  # critical on its own

        assert diff_datacenters(mini_dc, load_variant(mutate)).severity is Severity.CRITICAL

    def test_every_file_in_the_examples_folder_is_valid(self) -> None:
        for path in sorted(EXAMPLES.glob("mini_datacenter*.yaml")):
            assert load_datacenter(path).datacenter.name == "mini-datacenter"
