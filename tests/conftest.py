from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest

from ripplerack.models import Schema
from ripplerack.parser import LoadedDatacenter, load_datacenter

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
