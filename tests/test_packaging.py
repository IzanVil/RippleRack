"""What PyPI shows of the package: the links of its page and the links to the project.

PyPI shows ``README.md`` as the page of the package and does not know where the repository is, so
a relative link or image is a broken one there. The README therefore points to the files on
GitHub with absolute addresses, and the package names where the project lives. These tests keep
both true, and keep every such link pointing at a file and a heading that exist.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tests.markdown import REPO_URL, ROOT, anchors, links, project_file, targets

PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
README = ROOT / "README.md"
URL_NAMES = {"Homepage", "Documentation", "Source", "Issues", "Changelog"}


def test_the_readme_is_the_page_of_the_package() -> None:
    assert PROJECT["readme"] == "README.md"


def test_the_package_names_where_the_project_lives() -> None:
    urls = PROJECT["urls"]
    assert set(urls) == URL_NAMES
    assert all(url.startswith(REPO_URL) for url in urls.values())


def test_the_addresses_of_the_package_name_files_that_exist() -> None:
    urls = PROJECT["urls"]
    assert (ROOT / str(project_file(urls["Changelog"]))).is_file()
    assert (ROOT / str(project_file(urls["Documentation"]))).is_dir()
    assert urls["Issues"] == f"{REPO_URL}/issues"


@pytest.mark.parametrize("target", sorted(set(targets(README))))
def test_every_link_and_image_of_the_readme_has_an_absolute_address(target: str) -> None:
    assert target.startswith("https://"), f"{target} is a broken link on the page of PyPI"


def test_every_link_of_the_readme_to_the_repository_finds_its_file_and_heading() -> None:
    found = links(README)
    assert len(found) >= 25
    for file, anchor in found:
        target = (README.parent / file).resolve()
        assert target.exists(), f"README.md links to {file}, which does not exist"
        if anchor and target.suffix == ".md":
            assert anchor in anchors(target), f"README.md: no heading #{anchor} in {file}"


def test_the_other_guides_keep_their_relative_links() -> None:
    """The other guides are read on GitHub, where a relative link is the right one."""
    guide = Path(ROOT / "docs" / "ci.md")
    assert any(not target.startswith("https://") for target in targets(guide))
