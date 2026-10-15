"""Write a schema as YAML, in the shape ``impact --schema`` and a pipeline's ``schema:`` read."""

from __future__ import annotations

from typing import Any

import yaml

from ripplerack.models import Schema


class _Dumper(yaml.SafeDumper):
    """A SafeDumper that indents the items of a list under their key, like the examples."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Write a string as PyYAML would, except for text that holds a NEL (U+0085).

    PyYAML writes a NEL bare or in single quotes and reads it back as a space, because YAML
    1.1 counts it as a line break. Escaping it in double quotes keeps it.
    """
    style = '"' if "\x85" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _represent_str)


def render_schema_yaml(schema: Schema) -> str:
    """Return ``schema`` as a YAML document with ``name``, ``version`` and ``fields``.

    The text is generated from scratch, so there are no comments to preserve, and it is
    deterministic: the same schema always gives the same bytes. Fields keep their order and
    each takes one line. ``nullable`` and ``description`` are written only when they differ
    from their defaults, as in a hand-written file. Quoting is left to PyYAML, so names and
    descriptions that YAML would otherwise read as something else (``no``, ``2024-01-01``,
    ``a: b``) come back as the same text when the document is loaded.
    """
    fields: list[dict[str, Any]] = []
    for field in schema.fields:
        item: dict[str, Any] = {"name": field.name, "type": field.type.value}
        if field.nullable:
            item["nullable"] = True
        if field.description:
            item["description"] = field.description
        fields.append(item)
    document = {"name": schema.name, "version": schema.version, "fields": fields}
    text: str = yaml.dump(
        document,
        Dumper=_Dumper,
        sort_keys=False,
        default_flow_style=None,
        allow_unicode=True,
        width=2**31 - 1,  # never wrap a field over several lines
    )
    return text
