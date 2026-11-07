"""The numbers a pipeline can declare about its flow, as the documentation says them.

``docs/yaml-format.md`` lists them in a table. A field added to the model and left out of the
table, or a row left in the table after its field is gone, makes the guide lie about the format.
"""

from __future__ import annotations

import re

from ripplerack.models import Pipeline
from tests.markdown import ROOT

BASE = {"id", "runs_on", "schema_", "inputs"}
SECTION = re.compile(r"^## Pipeline flow\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
ROW = re.compile(r"^\| `([a-z_]+)`", re.MULTILINE)


def test_the_documented_flow_fields_are_the_ones_of_the_model() -> None:
    text = (ROOT / "docs" / "yaml-format.md").read_text(encoding="utf-8")
    [section] = SECTION.findall(text)
    assert set(ROW.findall(section)) == set(Pipeline.model_fields) - BASE
