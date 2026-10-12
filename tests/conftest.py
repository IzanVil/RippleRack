from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from ripplerack.models import Schema
from ripplerack.parser import LoadedDatacenter, load_datacenter, parse_datacenter

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
GOLDEN = Path(__file__).resolve().parent / "golden"
VERSION_PLACEHOLDER = "<version>"


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES


@pytest.fixture
def mini_dc() -> LoadedDatacenter:
    return load_datacenter(EXAMPLES / "mini_datacenter.yaml")


@pytest.fixture
def orders_schema(mini_dc: LoadedDatacenter) -> Schema:
    return mini_dc.datacenter.pipeline("orders-ingest").schema_


def make_schema(version: str, *fields: dict[str, object], name: str = "orders") -> Schema:
    """Build a schema from compact field dicts (``type`` defaults to ``string``)."""
    return Schema.model_validate(
        {"name": name, "version": version, "fields": [{"type": "string", **f} for f in fields]}
    )


def assert_text_golden(name: str, actual: str) -> None:
    """Compare ``actual`` with ``tests/golden/<name>``; see :func:`assert_json_golden`."""
    path = GOLDEN / name
    if os.environ.get("RIPPLERACK_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert actual == path.read_text(encoding="utf-8"), f"{name} differs"


def assert_json_golden(name: str, payload: dict[str, Any]) -> None:
    """Compare ``payload`` with ``tests/golden/<name>``.

    The tool version is replaced by a placeholder so releases do not invalidate the
    files. Run the tests with ``RIPPLERACK_UPDATE_GOLDEN=1`` to rewrite them, then
    review the diff: golden files are the visible form of the JSON contract.
    """
    actual = copy.deepcopy(payload)
    actual["tool"]["version"] = VERSION_PLACEHOLDER
    path = GOLDEN / name
    if os.environ.get("RIPPLERACK_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
    assert actual == json.loads(path.read_text(encoding="utf-8")), f"{name} differs"


def load_variant(mutate: Callable[[dict[str, Any]], None]) -> LoadedDatacenter:
    """Load the mini datacenter after applying ``mutate`` to its raw YAML data."""
    data: dict[str, Any] = yaml.safe_load((EXAMPLES / "mini_datacenter.yaml").read_text())
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
