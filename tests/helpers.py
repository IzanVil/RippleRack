"""Plain helpers shared by the test modules.

Fixtures live in ``conftest.py``; everything a test *calls* lives here, so tests import
from one place and never from ``conftest``. The golden-file helpers raise
``AssertionError`` with a unified diff themselves because pytest only rewrites ``assert``
statements in test modules and ``conftest.py``, not in plain helper modules.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ripplerack.impact import ImpactReport, analyze_schema_change
from ripplerack.importers.base import ImportResult
from ripplerack.models import Schema
from ripplerack.parser import LoadedDatacenter, RippleRackError, load_schema, parse_datacenter

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
GOLDEN = Path(__file__).resolve().parent / "golden"
SCHEMAS = Path(__file__).resolve().parent / "schemas"
VERSION_PLACEHOLDER = "<version>"


def raw_datacenter() -> dict[str, Any]:
    """The mini datacenter as raw YAML data; every call returns a fresh copy to mutate."""
    data: dict[str, Any] = yaml.safe_load((EXAMPLES / "mini_datacenter.yaml").read_text())
    return data


def load_variant(mutate: Callable[[dict[str, Any]], None]) -> LoadedDatacenter:
    """Load the mini datacenter after applying ``mutate`` to its raw YAML data."""
    data = raw_datacenter()
    mutate(data)
    return parse_datacenter(data)


def rack_of(data: dict[str, Any], rack_id: str) -> dict[str, Any]:
    """Find a rack in raw datacenter data."""
    found: dict[str, Any] = next(r for r in data["racks"] if r["id"] == rack_id)
    return found


def server_of(data: dict[str, Any], server_id: str) -> dict[str, Any]:
    """Find a server in raw datacenter data."""
    for rack in data["racks"]:
        for server in rack["servers"]:
            if server["id"] == server_id:
                found: dict[str, Any] = server
                return found
    raise KeyError(server_id)


def pipeline_of(data: dict[str, Any], pipeline_id: str) -> dict[str, Any]:
    """Find a pipeline in raw datacenter data."""
    found: dict[str, Any] = next(p for p in data["pipelines"] if p["id"] == pipeline_id)
    return found


def rename_kafka(data: dict[str, Any]) -> None:
    """Rename the service ``kafka`` to ``broker``; what pointed at it follows."""
    for service in server_of(data, "srv-a1")["services"]:
        if service["id"] == "kafka":
            service["id"] = "broker"
    pipeline_of(data, "orders-ingest")["runs_on"] = "broker"
    for dependency in data["dependencies"]:
        if dependency["target"] == "kafka":
            dependency["target"] = "broker"


def set_orders_schema(
    data: dict[str, Any], version: str, drop: str | None = None, **new_field: object
) -> None:
    """Give ``orders-ingest`` this version, without the field ``drop`` and with ``new_field``."""
    schema = pipeline_of(data, "orders-ingest")["schema"]
    schema["version"] = version
    schema["fields"] = [f for f in schema["fields"] if f["name"] != drop]
    if new_field:
        schema["fields"].append({"type": "string", **new_field})


def make_schema(version: str, *fields: dict[str, object], name: str = "orders") -> Schema:
    """Build a schema from compact field dicts (``type`` defaults to ``string``)."""
    return Schema.model_validate(
        {"name": name, "version": version, "fields": [{"type": "string", **f} for f in fields]}
    )


def impact_report(
    loaded: LoadedDatacenter, change: str = "orders_v2", pipeline: str = "orders-ingest"
) -> ImpactReport:
    """The impact of applying ``examples/changes/<change>.yaml`` to ``pipeline``."""
    new_schema = load_schema(EXAMPLES / "changes" / f"{change}.yaml")
    return analyze_schema_change(loaded.datacenter, loaded.graph, pipeline, new_schema)


def outcome(read: Callable[[], ImportResult]) -> tuple[Any, ...]:
    """What reading a document gave, in a form two readings can be compared by."""
    try:
        result = read()
    except RippleRackError as error:
        return ("refused", error.code, str(error))
    return ("imported", result.schema, result.issues)


def assert_text_golden(name: str, actual: str) -> None:
    """Compare ``actual`` with ``tests/golden/<name>``; see :func:`assert_json_golden`."""
    __tracebackhide__ = True
    path = GOLDEN / name
    if os.environ.get("RIPPLERACK_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        raise AssertionError(_golden_diff(name, expected, actual))


def assert_json_golden(name: str, payload: dict[str, Any]) -> None:
    """Compare ``payload`` with ``tests/golden/<name>``.

    The tool version is replaced by a placeholder so releases do not invalidate the
    files. Run the tests with ``RIPPLERACK_UPDATE_GOLDEN=1`` to rewrite them, then
    review the diff: golden files are the visible form of the JSON contract.
    """
    __tracebackhide__ = True
    actual = copy.deepcopy(payload)
    actual["tool"]["version"] = VERSION_PLACEHOLDER
    path = GOLDEN / name
    if os.environ.get("RIPPLERACK_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
    expected = json.loads(path.read_text(encoding="utf-8"))
    if actual != expected:
        raise AssertionError(
            _golden_diff(name, json.dumps(expected, indent=2), json.dumps(actual, indent=2))
        )


def _golden_diff(name: str, expected: str, actual: str) -> str:
    diff = difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), f"golden/{name}", "actual", lineterm=""
    )
    return (
        f"{name} differs from its golden file "
        "(RIPPLERACK_UPDATE_GOLDEN=1 rewrites it):\n" + "\n".join(diff)
    )
