"""Reading what the documentation says: its tables, its headings and its links.

The tests that check the documentation against the code share these, so that all of them read a
Markdown file in the same way.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/IzanVil/RippleRack"
RAW_URL = "https://raw.githubusercontent.com/IzanVil/RippleRack/main"
PROJECT_PATH = re.compile(
    rf"(?:{re.escape(REPO_URL)}/(?:blob|tree)/main|{re.escape(RAW_URL)})/(?P<path>[^#\s]*)"
)


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


def targets(path: Path) -> list[str]:
    """Where every link and image of a file points, as written, outside code blocks."""
    found: list[str] = []
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code:
            found.extend(re.findall(r"\]\(([^)\s]+)\)", line))
    return found


def project_file(target: str) -> str | None:
    """The path in the repository that a link to the project's files on GitHub names, if it does."""
    match = PROJECT_PATH.match(target)
    return match.group("path") if match else None


def links(path: Path) -> list[tuple[str, str]]:
    """The ``(file, anchor)`` of every link to a file of the repository, outside code blocks.

    A link is relative to the document or, as in the README that PyPI shows, absolute to the
    project's files on GitHub. Both are given as a path relative to the document, so that a test
    reads them the same way; links to anywhere else are not listed.
    """
    found: list[tuple[str, str]] = []
    for target in targets(path):
        file, _, anchor = target.partition("#")
        if (name := project_file(file)) is not None:
            found.append((os.path.relpath(ROOT / name, path.parent), anchor))
        elif not re.match(r"[a-z]+:", target):
            found.append((file, anchor))
    return found
