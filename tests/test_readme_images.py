"""The screenshots in the README must show what the commands print today.

``docs/images/generate.py`` runs each command and draws its output as an SVG terminal window.
This test draws them again and compares, the way the golden files pin the JSON output, so a change
to what a command prints cannot leave a stale picture in the README.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"
README = ROOT / "README.md"
REGENERATE = "run `uv run python docs/images/generate.py` and commit the images"
IMAGE_LINK = re.compile(r"!\[([^\]]*)\]\((docs/images/[^)\s]+)\)")


def load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("readme_images_generate", IMAGES / "generate.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass looks its own module up here
    spec.loader.exec_module(module)
    return module


GENERATOR = load_generator()
SCREENSHOTS = [f"{shot.name}.svg" for shot in GENERATOR.SHOTS]


@pytest.fixture(scope="module")
def drawn() -> dict[str, str]:
    """Every screenshot drawn afresh from its command, once for the whole module."""
    screenshots: dict[str, str] = GENERATOR.render_all()
    return screenshots


@pytest.mark.parametrize("name", SCREENSHOTS)
def test_a_screenshot_shows_what_its_command_prints_today(name: str, drawn: dict[str, str]) -> None:
    if (IMAGES / name).read_text(encoding="utf-8") != drawn[name]:
        pytest.fail(f"docs/images/{name} is out of date: {REGENERATE}")


def test_the_screenshots_are_the_ones_the_generator_makes() -> None:
    on_disk = sorted(path.name for path in IMAGES.glob("*.svg"))
    assert on_disk == sorted(SCREENSHOTS), f"unknown or missing images in docs/images: {REGENERATE}"


def test_the_readme_shows_every_screenshot_with_a_description() -> None:
    links = IMAGE_LINK.findall(README.read_text(encoding="utf-8"))
    assert sorted(path for _, path in links) == sorted(f"docs/images/{n}" for n in SCREENSHOTS)
    for alt, path in links:
        assert len(alt) >= 60, f"{path} needs a description that says what the terminal shows"
