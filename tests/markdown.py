"""Reading what the documentation says: its tables, its headings and its links.

The tests that check the documentation against the code share these, so that all of them read a
Markdown file in the same way.
"""

from __future__ import annotations

import re
from pathlib import Path


def unwrap(cell: str) -> str:
    """The text of a table cell that is written as code."""
    return cell.strip("`")


def table_under(text: str, heading: str) -> list[tuple[str, ...]]:
    """The rows of the first table after ``heading``, without its header, as tuples of cells.

    The line of dashes under the header is not a row. The search stops at the next heading.
    """
    lines = text.splitlines()
    rows: list[tuple[str, ...]] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("#"):
            break
        if not line.startswith("|"):
            if rows:
                break  # the table has ended
            continue
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if not set(cells[0]) <= {"-", ":", " "}:
            rows.append(cells)
    return rows[1:]


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower().replace("`", ""))
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    """The anchor of every heading of a file that is outside code blocks."""
    found: set[str] = set()
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and (match := re.match(r"#{1,6}\s+(.*?)\s*$", line)):
            found.add(slug(match.group(1)))
    return found


def links(path: Path) -> list[tuple[str, str]]:
    """The ``(file, anchor)`` of every relative link outside code blocks."""
    found: list[tuple[str, str]] = []
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code:
            for target in re.findall(r"\]\(([^)\s]+)\)", line):
                if not re.match(r"[a-z]+:", target):
                    file, _, anchor = target.partition("#")
                    found.append((file, anchor))
    return found
