"""Draw the terminal screenshots of the README from the real output of the commands.

Each screenshot is made by running the command it shows, with colours forced on and a fixed
width, and drawing what it prints as an SVG terminal window. Nothing is typed in by hand, so an
image cannot show anything the tool does not print, and ``tests/test_readme_images.py`` fails
when an image no longer matches the output of its command.

From the root of the repository::

    uv run python docs/images/generate.py

Only Rich is needed, which RippleRack already depends on.
"""

from __future__ import annotations

import io
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import TerminalTheme
from rich.text import Text

ROOT = Path(__file__).resolve().parents[2]
IMAGES = Path(__file__).resolve().parent
WIDTH = 100  # columns of the terminal; the tables of the commands are drawn for it

# A dark terminal, so that the colours of the output keep their meaning on any page theme.
THEME = TerminalTheme(
    (13, 17, 23),
    (201, 209, 217),
    [
        (33, 38, 45),
        (248, 81, 73),
        (63, 185, 80),
        (210, 153, 34),
        (88, 166, 255),
        (188, 140, 255),
        (57, 197, 207),
        (255, 255, 255),
    ],
    [
        (110, 118, 129),
        (255, 123, 114),
        (86, 211, 100),
        (227, 179, 65),
        (121, 192, 255),
        (210, 168, 255),
        (86, 212, 221),
        (255, 255, 255),
    ],
)


@dataclass(frozen=True)
class Shot:
    """One screenshot: the name of its file and the arguments given to ``ripplerack``."""

    name: str
    arguments: tuple[str, ...]


SHOTS = (
    Shot("validate", ("validate", "examples/mini_datacenter.yaml")),
    Shot("graph", ("graph", "examples/mini_datacenter.yaml")),
    Shot(
        "impact",
        (
            "impact",
            "examples/mini_datacenter.yaml",
            "-p",
            "orders-ingest",
            "-s",
            "examples/changes/orders_v2.yaml",
        ),
    ),
    Shot(
        "simulate",
        ("simulate", "examples/mini_datacenter.yaml", "--load", "1.5", "--fail", "srv-a2"),
    ),
)


def run(shot: Shot) -> str:
    """What the command prints, with its colours, as the terminal would receive it."""
    executable = shutil.which("ripplerack", path=str(Path(sys.executable).parent))
    if executable is None:
        raise SystemExit("ripplerack is not installed next to this Python: run `uv sync` first")
    environment = {key: value for key, value in os.environ.items() if key != "NO_COLOR"}
    environment.update(
        FORCE_COLOR="1",
        COLUMNS=str(WIDTH),
        TERM="xterm-256color",
        COLORTERM="truecolor",
        PYTHONUTF8="1",
    )
    done = subprocess.run(
        [executable, *shot.arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return done.stdout


def command_lines(arguments: tuple[str, ...]) -> list[str]:
    """The command as it would be typed, broken before an option when it is too long.

    An option stays with its value, so ``-s file`` is never split across two lines.
    """
    units: list[list[str]] = [["ripplerack"]]
    for word in map(shlex.quote, arguments):
        if word.startswith("-"):
            units.append([word])
        else:
            units[-1].append(word)
    lines: list[str] = []
    current = ""
    for unit in units:
        text = " ".join(unit)
        candidate = f"{current} {text}" if current else text
        if current and len(candidate) + 4 > WIDTH:  # room for the prompt and for " \\"
            lines.append(current)
            current = text
        else:
            current = candidate
    lines.append(current)
    return lines


def draw(shot: Shot, output: str) -> str:
    """The SVG of a terminal window that shows the command and its output."""
    console = Console(
        record=True,
        width=WIDTH,
        file=io.StringIO(),
        force_terminal=True,
        color_system="truecolor",
        legacy_windows=False,
    )
    lines = command_lines(shot.arguments)
    for index, line in enumerate(lines):
        prompt = ("$ ", "bold green") if index == 0 else ("  ", "")
        console.print(
            Text.assemble(prompt, (line + (" \\" if index < len(lines) - 1 else ""), "bold"))
        )
    console.print(Text.from_ansi(output.rstrip("\n")), soft_wrap=True)
    console.print()  # a margin under the last line
    return console.export_svg(title="ripplerack", theme=THEME, unique_id=f"ripplerack-{shot.name}")


def render_all() -> dict[str, str]:
    """Every screenshot, by file name, drawn from the output of its command."""
    return {f"{shot.name}.svg": draw(shot, run(shot)) for shot in SHOTS}


def main() -> None:
    for name, svg in render_all().items():
        (IMAGES / name).write_text(svg, encoding="utf-8")
        print(f"wrote docs/images/{name} ({len(svg) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
