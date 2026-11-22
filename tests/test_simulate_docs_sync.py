"""The JSON of ``simulate`` as ``docs/output-formats.md`` says it.

The guide lists the top-level keys of the document in a table. A key added to the document and
left out of the table, or a row left in it after its key is gone, makes the guide lie about the
contract, and so does an exit code that forgets the gate.
"""

from __future__ import annotations

import re

from ripplerack.parser import load_datacenter
from ripplerack.report import simulate_to_dict
from ripplerack.simulate import simulate
from tests.markdown import ROOT

GUIDE = (ROOT / "docs" / "output-formats.md").read_text(encoding="utf-8")
SECTION = re.compile(r"^## Simulate\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
KEYS = re.compile(r"^### Top-level keys\n(.*?)(?=^### |\Z)", re.MULTILINE | re.DOTALL)
ROW = re.compile(r"^\| `([a-zA-Z]+)`", re.MULTILINE)
ENVELOPE = 3  # schemaVersion, tool and command are described with the other documents


def test_the_documented_keys_are_the_ones_of_the_document_in_its_order() -> None:
    loaded = load_datacenter(ROOT / "examples" / "mini_datacenter.yaml")
    report = simulate(loaded.datacenter, loaded.graph)
    payload = simulate_to_dict(loaded.datacenter.name, report)
    [section] = SECTION.findall(GUIDE)
    [table] = KEYS.findall(section)
    assert ROW.findall(table) == list(payload)[ENVELOPE:]


def test_the_exit_codes_name_the_gate() -> None:
    codes = GUIDE[GUIDE.index("## Exit codes") : GUIDE.index("## Graph JSON export")]
    assert "--fail-on-overloaded" in codes
