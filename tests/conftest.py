from __future__ import annotations

from pathlib import Path

import pytest

from ripplerack.models import Schema
from ripplerack.parser import LoadedDatacenter, load_datacenter

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


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
