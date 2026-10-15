"""Pytest fixtures and settings. Plain helpers that tests call live in ``tests/helpers.py``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hypothesis import settings

from ripplerack.models import Schema
from ripplerack.parser import LoadedDatacenter, load_datacenter
from tests.helpers import EXAMPLES, raw_datacenter

# A property-based test must reach the same verdict on every run and on every machine, or a
# red CI run could not be told from a flaky one. ``derandomize`` derives the examples from the
# test itself, so they are the same each time; ``deadline=None`` stops a slow runner from
# failing a test that is only slow. Both keep the tests reproducible, not weaker.
settings.register_profile("ripplerack", derandomize=True, deadline=None)
settings.load_profile("ripplerack")


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
