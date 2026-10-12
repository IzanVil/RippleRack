"""Pytest fixtures. Plain helpers that tests call live in ``tests/helpers.py``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ripplerack.models import Schema
from ripplerack.parser import LoadedDatacenter, load_datacenter
from tests.helpers import EXAMPLES, raw_datacenter


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES


@pytest.fixture
def mini_dc() -> LoadedDatacenter:
    return load_datacenter(EXAMPLES / "mini_datacenter.yaml")


@pytest.fixture
def orders_schema(mini_dc: LoadedDatacenter) -> Schema:
    return mini_dc.datacenter.pipeline("orders-ingest").schema_


@pytest.fixture
def raw_mini() -> dict[str, Any]:
    """The mini datacenter as raw YAML data, fresh for every test."""
    return raw_datacenter()
