"""The glue between GitHub Actions and the ``ripplerack`` command.

Everything RippleRack knows about a datacenter stays in the command. This file installs it, asks it
to compare two versions of a file in the two formats an action needs (JSON for the outputs and
Markdown for people) and carries the result to GitHub: the outputs of the step, the summary of the
job and one comment on the pull request, which every later run updates instead of adding another.

It uses only the standard library, because the first thing it does is install RippleRack.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MINIMUM_PYTHON = (3, 11)
PAGE_SIZE = 100
PULL_REQUEST_EVENTS = ("pull_request", "pull_request_target")
GATE_EXIT_CODE = 2  # what ``ripplerack`` exits with when a consumer breaks and it was asked to

# The inputs of action.yml and the variable that carries each one to this file.
INPUT_VARIABLES = {
    "head": "RR_HEAD",
    "base": "RR_BASE",
    "fail-on-breaking": "RR_FAIL_ON_BREAKING",
    "comment-on-pr": "RR_COMMENT_ON_PR",
    "github-token": "RR_TOKEN",
    "max-items": "RR_MAX_ITEMS",
    "diagram": "RR_DIAGRAM",
}
OUTPUT_NAMES = ("severity", "broken-count", "at-risk-count", "report-path")


class ActionError(Exception):
    """A problem that ends the step, with the message to show and the exit code to give."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def annotate(level: str, message: str) -> None:
    """Print a workflow command that GitHub shows as a notice, a warning or an error."""
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level}::{escaped}", flush=True)


def short_hash(text: str) -> str:
    """Twelve characters that tell one head file from another and are safe in a file name."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


# --------------------------------------------------------------------------------- settings


@dataclass(frozen=True)
class Settings:
    """What the step was asked to do, and where it runs."""

    head: str
    head_name: str  # the head file as git knows it: relative to the workspace
    base: str
    fail_on_breaking: bool
    comment_on_pr: bool
    token: str
    max_items: str
    diagram: bool
    command: list[str]
    workspace: Path
    temp: Path
    event_name: str
    event_path: Path | None
    repository: str
    api_url: str
    output: Path | None
    summary: Path | None

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> Settings:
        """Read the inputs of the step, which ``action.yml`` puts in ``RR_*`` variables."""
        temp = Path(env.get("RUNNER_TEMP") or "/tmp")

        def read(name: str) -> str:
            return env.get(INPUT_VARIABLES[name], "").strip()

        def flag(name: str) -> bool:
            value = read(name).lower()
            if value not in ("true", "false"):
                raise ActionError(f"the input {name} must be true or false, not {read(name)!r}")
            return value == "true"

        if not read("head"):
            raise ActionError("the input head is empty")
        workspace = Path(env.get("GITHUB_WORKSPACE") or ".").resolve()
        return cls(
            head=read("head"),
            head_name=relative_name(workspace, read("head")),
            base=read("base"),
            fail_on_breaking=flag("fail-on-breaking"),
            comment_on_pr=flag("comment-on-pr"),
            token=env.get(INPUT_VARIABLES["github-token"], ""),
            max_items=read("max-items") or "25",
            diagram=flag("diagram"),
            command=shlex.split(env.get("RR_COMMAND", ""))
            or [str(venv_executable(temp, "ripplerack"))],
            workspace=workspace,
            temp=temp,
            event_name=env.get("GITHUB_EVENT_NAME", ""),
            event_path=_path(env.get("GITHUB_EVENT_PATH")),
            repository=env.get("GITHUB_REPOSITORY", ""),
            api_url=(env.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/"),
            output=_path(env.get("GITHUB_OUTPUT")),
            summary=_path(env.get("GITHUB_STEP_SUMMARY")),
        )

    @property
    def head_file(self) -> Path:
        return self.workspace / self.head

    def pull_request(self) -> dict[str, Any]:
        """The ``pull_request`` object of the event; empty outside a pull request."""
        if self.event_name not in PULL_REQUEST_EVENTS or self.event_path is None:
            return {}
        payload = json.loads(self.event_path.read_text(encoding="utf-8"))
        found = payload.get("pull_request")
        return found if isinstance(found, dict) else {}


def _path(value: str | None) -> Path | None:
    return Path(value) if value else None


def relative_name(workspace: Path, head: str) -> str:
    """The head file relative to the workspace, as one text however it was written.

    ``./a//b.yaml``, ``a/b.yaml`` and the absolute path of the file are all ``a/b.yaml``.
    """
    absolute = Path(os.path.normpath(workspace / head))
    try:
        return absolute.relative_to(workspace).as_posix()
    except ValueError:
        raise ActionError(f"the input head names {head}, which is not inside {workspace}") from None


# ---------------------------------------------------------------------------------- install


def venv_executable(temp: Path, name: str) -> Path:
    """Where the virtual environment of the step keeps a program."""
    folder, suffix = ("Scripts", ".exe") if os.name == "nt" else ("bin", "")
    return temp / "ripplerack-venv" / folder / f"{name}{suffix}"


def check_python() -> None:
    if sys.version_info < MINIMUM_PYTHON:
        found = ".".join(str(part) for part in sys.version_info[:3])
        raise ActionError(
            f"RippleRack needs Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer and the "
            f"runner has {found}: add actions/setup-python before this step"
        )


def install(env: Mapping[str, str]) -> int:
    """Install the RippleRack that this action comes with, in a virtual environment."""
    check_python()
    temp = Path(env.get("RUNNER_TEMP") or "/tmp")
    root = Path(__file__).resolve().parent.parent
    if not (root / "pyproject.toml").is_file():
        raise ActionError(f"{root} is not a RippleRack checkout: the action was moved out of it")
    print("::group::Install RippleRack", flush=True)
    try:
        subprocess.run([sys.executable, "-m", "venv", str(temp / "ripplerack-venv")], check=True)
        python = str(venv_executable(temp, "python"))
        pip = [python, "-m", "pip", "install", "--disable-pip-version-check", "--quiet"]
        subprocess.run([*pip, str(root)], check=True)
    except subprocess.CalledProcessError as error:
        raise ActionError(
            f"could not install RippleRack ({shlex.join(error.cmd)} exited with {error.returncode})"
        ) from error
    finally:
        print("::endgroup::", flush=True)
    return 0


# ------------------------------------------------------------------------------ the two files


def git(settings: Settings, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Run git in the workspace. Its messages depend on the language, so only codes are read."""
    return subprocess.run(["git", *args], cwd=settings.workspace, capture_output=True, check=False)


def resolve_base(settings: Settings) -> Path | None:
    """The file to compare with: the one given, or the head file as the pull request found it.

    ``None`` means that the pull request adds the file, so there is nothing to compare it with.
    """
    if settings.base:
        base = settings.workspace / settings.base
        if not base.is_file():
            raise ActionError(f"the input base names {settings.base}, which is not a file")
        return base
    sha = settings.pull_request().get("base", {}).get("sha")
    if not isinstance(sha, str) or not sha:
        raise ActionError(
            "the input base is needed when the workflow does not run on a pull request: "
            "there is no base commit to read the file from"
        )
    return file_at(settings, sha)


def file_at(settings: Settings, sha: str) -> Path | None:
    """The head file as it was in commit ``sha``, in a temporary file; ``None`` if it was not."""
    if git(settings, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        fetched = git(settings, "fetch", "--no-tags", "--depth=1", "origin", sha)
        if fetched.returncode != 0:
            raise ActionError(f"could not fetch the base commit {sha[:12]} from origin")
    spec = f"{sha}:./{settings.head_name}"
    if git(settings, "cat-file", "-e", spec).returncode != 0:
        return None
    shown = git(settings, "show", spec)
    if shown.returncode != 0:
        raise ActionError(f"could not read {settings.head_name} in the base commit {sha[:12]}")
    target = settings.temp / f"ripplerack-base-{short_hash(settings.head_name)}.yaml"
    target.write_bytes(shown.stdout)
    return target


# ---------------------------------------------------------------------------- the comparison


@dataclass(frozen=True)
class Comparison:
    """What ``ripplerack diff`` found, as the step reports it."""

    severity: str
    broken: int
    at_risk: int
    report: str
    gate_failed: bool


def execute(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
    )


def checked(result: subprocess.CompletedProcess[str]) -> str:
    """The output of a ``diff`` that worked. Exit code 2 with an output is a breaking change."""
    if result.returncode not in (0, GATE_EXIT_CODE) or not result.stdout.strip():
        detail = error_text(result.stderr) or f"exit code {result.returncode}"
        raise ActionError(f"ripplerack diff failed: {detail}")
    return result.stdout


def error_text(stderr: str) -> str:
    """What ``ripplerack`` said went wrong: the code and the message of its JSON error document."""
    try:
        error = json.loads(stderr)["error"]
        return f"{error['code']}: {error['message']}"
    except (ValueError, KeyError, TypeError):
        return stderr.strip()


def at_risk_count(document: Mapping[str, Any]) -> int:
    """The components that something breaks under, leaving out the ones another change breaks."""
    changes = document["schemaChanges"]
    broken = {c["pipeline"] for change in changes for c in change["brokenConsumers"]}
    at_risk = {name for change in changes for name in change["atRisk"]}
    return len(at_risk - broken)


def summarize(document: Mapping[str, Any]) -> tuple[str, int, int]:
    """The severity, the broken consumers and the components at risk of a ``diff`` document."""
    return document["severity"], document["summary"]["brokenConsumers"], at_risk_count(document)


def compare(settings: Settings, base: Path) -> Comparison:
    """Compare ``base`` with the head file, once for the outputs and once for people."""
    command = [*settings.command, "diff", str(base), str(settings.head_file)]
    gate = ["--fail-on-breaking"] if settings.fail_on_breaking else []
    as_json = execute([*command, "-F", "json", *gate], settings.workspace)
    severity, broken, at_risk = summarize(json.loads(checked(as_json)))
    options = ["--max-items", settings.max_items, *([] if settings.diagram else ["--no-diagram"])]
    as_markdown = execute([*command, "-F", "markdown", *options, *gate], settings.workspace)
    return Comparison(
        severity=severity,
        broken=broken,
        at_risk=at_risk,
        report=checked(as_markdown),
        gate_failed=as_json.returncode == GATE_EXIT_CODE,
    )


# ------------------------------------------------------------------------------- the comment


class GitHub:
    """The few calls of the GitHub API that the comment needs."""

    def __init__(self, api_url: str, token: str) -> None:
        self._api_url = api_url
        self._token = token

    def request(self, method: str, path: str, payload: object | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self._api_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ripplerack-action",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)


def marker_for(head_name: str) -> str:
    """The first line of the comment of a file, which is how a later run finds it."""
    return f"<!-- ripplerack-action:{short_hash(head_name)} -->"


def comments_with(github: GitHub, repository: str, issue: int, marker: str) -> Iterator[Any]:
    """The comments of the pull request that start with ``marker``, oldest first."""
    page = 1
    while True:
        path = f"/repos/{repository}/issues/{issue}/comments?per_page={PAGE_SIZE}&page={page}"
        comments = github.request("GET", path)
        yield from (c for c in comments if str(c.get("body", "")).startswith(marker))
        if len(comments) < PAGE_SIZE:
            return
        page += 1


def upsert_comment(github: GitHub, repository: str, issue: int, marker: str, report: str) -> str:
    """Update the comment that ``marker`` finds, or add it if there is none; say which."""
    body = f"{marker}\n{report}"
    for comment in comments_with(github, repository, issue, marker):
        try:
            github.request(
                "PATCH", f"/repos/{repository}/issues/comments/{comment['id']}", {"body": body}
            )
        except urllib.error.HTTPError as error:
            if error.code in (403, 404):  # a comment that is not ours to edit
                continue
            raise
        return "updated"
    github.request("POST", f"/repos/{repository}/issues/{issue}/comments", {"body": body})
    return "created"


def comment(settings: Settings, report: str) -> None:
    """Put the report in the pull request. A comment that cannot be posted is only a warning."""
    pull_request = settings.pull_request()
    if not pull_request:
        annotate("notice", "comment-on-pr is true, but this is not a pull request: no comment")
        return
    if not settings.token:
        annotate("warning", "the comment was not posted: github-token is empty")
        return
    github = GitHub(settings.api_url, settings.token)
    marker = marker_for(settings.head_name)
    try:
        done = upsert_comment(github, settings.repository, pull_request["number"], marker, report)
    except (OSError, ValueError) as error:  # URLError and HTTPError are OSErrors
        reason = f"HTTP {error.code}" if isinstance(error, urllib.error.HTTPError) else error
        annotate(
            "warning",
            f"the comment was not posted ({reason}). The token needs pull-requests: write, and "
            "a pull request from a fork gets a token that can only read.",
        )
        return
    print(f"The comment on the pull request was {done}.", flush=True)


# ------------------------------------------------------------------------------- the results


def write_outputs(settings: Settings, values: Mapping[str, str]) -> None:
    """Add the outputs of the step to the file that GitHub reads them from."""
    assert tuple(values) == OUTPUT_NAMES
    if settings.output is None:
        return
    with settings.output.open("a", encoding="utf-8") as handle:
        for name, value in values.items():
            handle.write(f"{name}={value}\n")


def write_summary(settings: Settings, text: str) -> None:
    """Add a report to the summary of the job."""
    if settings.summary is None:
        return
    with settings.summary.open("a", encoding="utf-8") as handle:
        handle.write(text.rstrip("\n") + "\n")


def run(env: Mapping[str, str]) -> int:
    """Compare the two files, publish the result and give the exit code the gate asks for."""
    settings = Settings.from_environment(env)
    if not settings.head_file.is_file():
        raise ActionError(f"the input head names {settings.head}, which is not a file")
    base = resolve_base(settings)
    if base is None:
        return skip_new_file(settings)
    result = compare(settings, base)
    report_path = settings.temp / f"ripplerack-report-{short_hash(settings.head_name)}.md"
    report_path.write_text(result.report, encoding="utf-8")
    write_summary(settings, result.report)
    if settings.comment_on_pr:
        comment(settings, result.report)
    outputs = [result.severity, str(result.broken), str(result.at_risk), str(report_path)]
    write_outputs(settings, dict(zip(OUTPUT_NAMES, outputs, strict=True)))
    if result.gate_failed:
        raise ActionError(
            f"{result.broken} consumer(s) would break and fail-on-breaking is on", GATE_EXIT_CODE
        )
    return 0


def skip_new_file(settings: Settings) -> int:
    """A file the pull request adds has no earlier version: say so and report nothing broken."""
    message = f"{settings.head_name} is new in this pull request, so there is nothing to compare"
    annotate("notice", message)
    write_summary(settings, f"## RippleRack\n\n{message}.")
    write_outputs(settings, dict(zip(OUTPUT_NAMES, ["none", "0", "0", ""], strict=True)))
    return 0


def main(argv: Sequence[str], env: Mapping[str, str]) -> int:
    commands = {"install": install, "run": run}
    if len(argv) != 1 or argv[0] not in commands:
        print("usage: rr_action.py install|run", file=sys.stderr)
        return 2
    try:
        check_python()
        return commands[argv[0]](env)
    except ActionError as error:
        annotate("error", str(error))
        return error.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
