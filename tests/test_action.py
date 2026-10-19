"""The glue of the GitHub Action, tested without GitHub.

``rr_action.py`` is run as the action runs it: with the variables that ``action.yml`` sets, in a git
repository that holds the two versions of a datacenter file, and against a copy of the GitHub API
that keeps its comments in memory. What ``ripplerack`` says about the files is tested elsewhere;
here it is what the step does with it: the outputs, the summary, the one comment that every push
updates, the gate, and the files and cases that are not the usual ones.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest
import yaml
from typer.testing import CliRunner

import rr_action
from ripplerack.cli import app
from tests.helpers import EXAMPLES, GOLDEN, assert_text_golden, pipeline_of, raw_datacenter
from tests.scenarios import SCENARIOS, write_files

runner = CliRunner()
TOKEN = "t0ken"
COMMAND = shlex.join([sys.executable, "-c", "from ripplerack.cli import app; app()"])
BASE_TEXT = (EXAMPLES / "mini_datacenter.yaml").read_text(encoding="utf-8")
HEAD_TEXT = (EXAMPLES / "mini_datacenter_v2.yaml").read_text(encoding="utf-8")


# ----------------------------------------------------------------------- the GitHub API


class FakeGitHub:
    """The part of the GitHub API that the action uses, with its comments kept in memory."""

    def __init__(self) -> None:
        self.comments: dict[int, dict[str, Any]] = {}
        self.calls: list[str] = []
        self.authorizations: set[str] = set()
        self.refuse: dict[str, int] = {}  # a method that answers with this status
        self.not_ours: set[int] = set()  # comments that the token may not edit
        self._next_id = 1
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # keep the test output clean
                pass

            def do_GET(self) -> None:
                owner.handle(self, "GET")

            def do_POST(self) -> None:
                owner.handle(self, "POST")

            def do_PATCH(self) -> None:
                owner.handle(self, "PATCH")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def add(self, issue: int, body: str, *, ours: bool = True) -> int:
        """A comment that was there before the action ran."""
        number = self._next_id
        self._next_id += 1
        self.comments[number] = {"id": number, "issue": issue, "body": body}
        if not ours:
            self.not_ours.add(number)
        return number

    def on(self, issue: int) -> list[dict[str, Any]]:
        return [c for c in self.comments.values() if c["issue"] == issue]

    def handle(self, request: BaseHTTPRequestHandler, method: str) -> None:
        self.calls.append(f"{method} {request.path}")
        self.authorizations.add(request.headers.get("Authorization", ""))
        length = int(request.headers.get("Content-Length") or 0)
        payload = json.loads(request.rfile.read(length)) if length else {}
        path, _, query = request.path.partition("?")
        if method in self.refuse:
            self._reply(request, self.refuse[method], {"message": "Resource not accessible"})
        elif found := re.fullmatch(r"/repos/o/r/issues/(\d+)/comments", path):
            issue = int(found.group(1))
            if method == "GET":
                self._reply(request, 200, self._page(issue, parse_qs(query)))
            else:
                number = self.add(issue, payload["body"])
                self._reply(request, 201, self.comments[number])
        elif found := re.fullmatch(r"/repos/o/r/issues/comments/(\d+)", path):
            number = int(found.group(1))
            if number in self.not_ours:
                self._reply(request, 403, {"message": "Forbidden"})
            else:
                self.comments[number]["body"] = payload["body"]
                self._reply(request, 200, self.comments[number])
        else:
            self._reply(request, 404, {"message": "Not Found"})

    def _page(self, issue: int, query: dict[str, list[str]]) -> list[dict[str, Any]]:
        size, page = int(query["per_page"][0]), int(query["page"][0])
        return self.on(issue)[(page - 1) * size : page * size]

    @staticmethod
    def _reply(request: BaseHTTPRequestHandler, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        request.send_response(status)
        request.send_header("Content-Type", "application/json")
        request.send_header("Content-Length", str(len(body)))
        request.end_headers()
        request.wfile.write(body)


@pytest.fixture
def github() -> Iterator[FakeGitHub]:
    fake = FakeGitHub()
    fake.start()
    yield fake
    fake.stop()


# -------------------------------------------------------------------------- the repository


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


class PullRequest:
    """A repository where a pull request moves ``dc.yaml`` to the second version of the example."""

    def __init__(self, folder: Path, number: int = 7) -> None:
        self.folder = folder / "work"
        self.folder.mkdir()
        self.temp = folder / "temp"
        self.temp.mkdir()
        self.number = number
        git(self.folder, "init", "-q")
        git(self.folder, "config", "user.name", "Test")
        git(self.folder, "config", "user.email", "test@example.com")
        self.write("dc.yaml", BASE_TEXT)
        self.write("other.yaml", BASE_TEXT)
        self.commit("the base of the pull request")
        self.base_sha = git(self.folder, "rev-parse", "HEAD")
        self.write("dc.yaml", HEAD_TEXT)
        self.write("other.yaml", HEAD_TEXT)
        self.commit("the head of the pull request")
        self.event = folder / "event.json"
        self.event.write_text(
            json.dumps({"pull_request": {"number": number, "base": {"sha": self.base_sha}}})
        )

    def write(self, name: str, text: str) -> None:
        (self.folder / name).write_text(text, encoding="utf-8")

    def commit(self, message: str) -> None:
        git(self.folder, "add", "-A")
        git(self.folder, "commit", "-q", "-m", message)

    def push(self, number: int, name: str = "dc.yaml") -> None:
        """A new commit on the branch: the head file says something else."""
        document = yaml.safe_load(HEAD_TEXT)
        document["description"] = f"Pushed {number} times"
        self.write(name, yaml.safe_dump(document, sort_keys=False))

    def environment(self, github: FakeGitHub | None = None, /, **inputs: str) -> dict[str, str]:
        """The variables that ``action.yml`` sets, with the inputs given instead of the defaults."""
        values = {
            "head": "dc.yaml",
            "base": "",
            "fail-on-breaking": "false",
            "comment-on-pr": "true",
            "github-token": TOKEN,
            "max-items": "25",
            "diagram": "true",
        }
        values.update({name.replace("_", "-"): value for name, value in inputs.items()})
        env = {rr_action.INPUT_VARIABLES[name]: value for name, value in values.items()}
        env.update(
            RR_COMMAND=COMMAND,
            GITHUB_WORKSPACE=str(self.folder),
            RUNNER_TEMP=str(self.temp),
            GITHUB_EVENT_NAME="pull_request",
            GITHUB_EVENT_PATH=str(self.event),
            GITHUB_REPOSITORY="o/r",
            GITHUB_API_URL=github.url if github else "http://127.0.0.1:9",
            GITHUB_OUTPUT=str(self.temp / "output"),
            GITHUB_STEP_SUMMARY=str(self.temp / "summary.md"),
        )
        return env

    def outputs(self) -> dict[str, str]:
        text = (self.temp / "output").read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.splitlines())

    def summary(self) -> str:
        return (self.temp / "summary.md").read_text(encoding="utf-8")


@pytest.fixture
def pr(tmp_path: Path) -> PullRequest:
    return PullRequest(tmp_path)


def run_step(env: dict[str, str]) -> int:
    return rr_action.main(["run"], env)


# ------------------------------------------------------------------------------- the usual run


def test_the_outputs_are_the_severity_and_the_counts(pr: PullRequest, github: FakeGitHub) -> None:
    assert run_step(pr.environment(github)) == 0
    outputs = pr.outputs()
    assert [outputs[name] for name in rr_action.OUTPUT_NAMES[:3]] == ["high", "1", "1"]
    report = Path(outputs["report-path"]).read_text(encoding="utf-8")
    assert report.startswith("## RippleRack · 🟠 HIGH\n")


def test_the_summary_of_the_job_holds_the_report(pr: PullRequest, github: FakeGitHub) -> None:
    run_step(pr.environment(github))
    assert pr.summary() == Path(pr.outputs()["report-path"]).read_text(encoding="utf-8")


def test_the_comment_starts_with_the_marker_and_holds_the_report(
    pr: PullRequest, github: FakeGitHub
) -> None:
    run_step(pr.environment(github))
    [comment] = github.on(7)
    report = Path(pr.outputs()["report-path"]).read_text(encoding="utf-8")
    assert comment["body"] == f"{rr_action.marker_for('dc.yaml')}\n{report}"
    assert github.authorizations == {f"Bearer {TOKEN}"}


def test_the_options_reach_the_report(pr: PullRequest, github: FakeGitHub) -> None:
    run_step(pr.environment(github, diagram="false", max_items="1"))
    report = Path(pr.outputs()["report-path"]).read_text(encoding="utf-8")
    assert "mermaid" not in report
    assert "_… and 1 more (use --max-items 0 to list all)_" in report


def test_the_file_can_be_named_in_other_ways(pr: PullRequest, github: FakeGitHub) -> None:
    (pr.folder / "sub").mkdir()
    assert run_step(pr.environment(github, head="./dc.yaml")) == 0
    assert run_step(pr.environment(github, head="sub/../dc.yaml")) == 0
    assert run_step(pr.environment(github, head=str(pr.folder / "dc.yaml"))) == 0
    assert pr.outputs()["severity"] == "high"  # the base was found for the absolute path too
    [comment] = github.on(7)  # both are the same file: one comment
    assert comment["body"].startswith(rr_action.marker_for("dc.yaml"))


def test_a_base_file_can_be_given_instead_of_the_commit(
    pr: PullRequest, github: FakeGitHub
) -> None:
    pr.write("before.yaml", BASE_TEXT)
    env = pr.environment(github, base="before.yaml", comment_on_pr="false")
    env["GITHUB_EVENT_NAME"] = "push"
    assert run_step(env) == 0
    assert pr.outputs()["severity"] == "high"
    assert github.calls == []


# ------------------------------------------------------------------------------------ the gate


def test_fail_on_breaking_fails_the_step_after_the_comment(
    pr: PullRequest, github: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_step(pr.environment(github, fail_on_breaking="true")) == 2
    assert len(github.on(7)) == 1  # the report is there for whoever reads why the check is red
    assert pr.outputs()["broken-count"] == "1"
    assert "::error::1 consumer(s) would break" in capsys.readouterr().out


def test_a_change_that_breaks_nothing_passes_the_gate(pr: PullRequest, github: FakeGitHub) -> None:
    pr.write("dc.yaml", BASE_TEXT)
    pr.write("before.yaml", BASE_TEXT)  # head is base: no difference at all
    env = pr.environment(github, base="before.yaml", fail_on_breaking="true")
    assert run_step(env) == 0
    assert [pr.outputs()[name] for name in rr_action.OUTPUT_NAMES[:3]] == ["none", "0", "0"]


# ------------------------------------------------------------------------- the cases that fail


def test_without_a_base_outside_a_pull_request_the_step_fails(
    pr: PullRequest, capsys: pytest.CaptureFixture[str]
) -> None:
    env = pr.environment(comment_on_pr="false")
    env["GITHUB_EVENT_NAME"] = "push"
    assert run_step(env) == 1
    assert "the input base is needed" in capsys.readouterr().out


def test_a_head_file_that_does_not_exist_fails_the_step(
    pr: PullRequest, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_step(pr.environment(head="nope.yaml")) == 1
    assert "the input head names nope.yaml" in capsys.readouterr().out


def test_a_head_file_outside_the_repository_fails_the_step(
    pr: PullRequest, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "outside.yaml").write_text(HEAD_TEXT)
    assert run_step(pr.environment(head=str(tmp_path / "outside.yaml"))) == 1
    assert "which is not inside" in capsys.readouterr().out


def test_a_base_file_that_does_not_exist_fails_the_step(
    pr: PullRequest, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_step(pr.environment(base="nope.yaml")) == 1
    assert "the input base names nope.yaml" in capsys.readouterr().out


def test_a_file_ripplerack_cannot_read_fails_the_step_with_its_message(
    pr: PullRequest, github: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    pr.write("dc.yaml", "name: [unclosed")
    assert run_step(pr.environment(github)) == 1
    out = capsys.readouterr().out
    assert "::error::ripplerack diff failed: invalid_yaml:" in out
    assert "dc.yaml" in out
    assert github.calls == []


def test_a_wrong_number_of_rows_is_a_usage_error_of_ripplerack(
    pr: PullRequest, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_step(pr.environment(max_items="-1")) == 1
    assert "ripplerack diff failed" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["fail-on-breaking", "comment-on-pr", "diagram"])
def test_a_flag_must_be_true_or_false(
    name: str, pr: PullRequest, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_step(pr.environment(**{name.replace("-", "_"): "maybe"})) == 1
    assert f"the input {name} must be true or false" in capsys.readouterr().out


def test_the_step_needs_a_python_that_ripplerack_can_run_on(
    pr: PullRequest, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 10, 4, "final", 0))
    assert rr_action.main(["run"], pr.environment()) == 1
    assert "needs Python 3.11 or newer and the runner has 3.10.4" in capsys.readouterr().out


def test_an_unknown_command_is_a_usage_error() -> None:
    assert rr_action.main(["nope"], {}) == 2
    assert rr_action.main([], {}) == 2


# --------------------------------------------------------------------- a file that is new


def test_a_file_that_the_pull_request_adds_has_nothing_to_compare(
    pr: PullRequest, github: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    pr.write("new.yaml", HEAD_TEXT)
    pr.commit("a datacenter that did not exist")
    assert run_step(pr.environment(github, head="new.yaml", fail_on_breaking="true")) == 0
    assert pr.outputs() == {
        "severity": "none",
        "broken-count": "0",
        "at-risk-count": "0",
        "report-path": "",
    }
    assert "::notice::new.yaml is new in this pull request" in capsys.readouterr().out
    assert "is new in this pull request" in pr.summary()
    assert github.calls == []


def test_the_base_commit_is_fetched_when_the_clone_is_shallow(
    pr: PullRequest, github: FakeGitHub, tmp_path: Path
) -> None:
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(pr.folder, "push", "-q", str(origin), "HEAD:refs/heads/main")
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth=1", "--branch", "main", f"file://{origin}", str(shallow))
    assert (
        subprocess.run(
            ["git", "cat-file", "-e", f"{pr.base_sha}^{{commit}}"], cwd=shallow, check=False
        ).returncode
        != 0
    ), "the clone is not shallow"
    env = pr.environment(github)
    env["GITHUB_WORKSPACE"] = str(shallow)
    assert run_step(env) == 0
    assert pr.outputs()["severity"] == "high"


def test_a_base_commit_that_cannot_be_fetched_fails_the_step(
    pr: PullRequest, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    alone = tmp_path / "alone"
    alone.mkdir()
    git(alone, "init", "-q")
    (alone / "dc.yaml").write_text(HEAD_TEXT)
    env = pr.environment()
    env["GITHUB_WORKSPACE"] = str(alone)
    assert run_step(env) == 1
    assert "could not fetch the base commit" in capsys.readouterr().out


# --------------------------------------------------------------------- the comment


def test_not_being_a_pull_request_leaves_no_comment(
    pr: PullRequest, github: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    pr.write("before.yaml", BASE_TEXT)
    env = pr.environment(github, base="before.yaml")
    env["GITHUB_EVENT_NAME"] = "workflow_dispatch"
    assert run_step(env) == 0
    assert (
        "::notice::comment-on-pr is true, but this is not a pull request" in capsys.readouterr().out
    )
    assert github.calls == []


def test_an_empty_token_is_a_warning_and_the_step_goes_on(
    pr: PullRequest, github: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_step(pr.environment(github, github_token="")) == 0
    assert "::warning::the comment was not posted: github-token is empty" in capsys.readouterr().out
    assert pr.outputs()["severity"] == "high"


@pytest.mark.parametrize("refused", ["GET", "POST"])
@pytest.mark.parametrize("fail", ["false", "true"])
def test_a_comment_that_cannot_be_posted_is_a_warning_and_never_changes_the_gate(
    fail: str,
    refused: str,
    pr: PullRequest,
    github: FakeGitHub,
    capsys: pytest.CaptureFixture[str],
) -> None:
    github.refuse = {refused: 403}  # what a pull request from a fork gets
    code = run_step(pr.environment(github, fail_on_breaking=fail))
    assert code == (2 if fail == "true" else 0)
    out = capsys.readouterr().out
    assert "::warning::the comment was not posted (HTTP 403)" in out
    assert pr.outputs()["severity"] == "high"
    assert pr.summary().startswith("## RippleRack")


def test_no_server_is_a_warning_too(pr: PullRequest, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_step(pr.environment(None)) == 0
    assert "::warning::the comment was not posted" in capsys.readouterr().out


def test_a_comment_that_is_not_ours_is_left_alone(pr: PullRequest, github: FakeGitHub) -> None:
    marker = rr_action.marker_for("dc.yaml")
    github.add(7, f"{marker}\nsomeone else wrote this", ours=False)
    run_step(pr.environment(github))
    bodies = [c["body"] for c in github.on(7)]
    assert bodies[0] == f"{marker}\nsomeone else wrote this"
    assert len(bodies) == 2
    assert bodies[1].startswith(f"{marker}\n## RippleRack")


def test_the_comment_is_found_on_a_later_page(
    pr: PullRequest, github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rr_action, "PAGE_SIZE", 2)
    for number in range(5):
        github.add(7, f"a comment {number}")
    mine = github.add(7, f"{rr_action.marker_for('dc.yaml')}\nold")
    github.add(7, "another one")
    run_step(pr.environment(github))
    assert len(github.on(7)) == 7
    assert github.comments[mine]["body"].endswith("\n" + pr.summary())


def test_the_comments_of_other_pull_requests_are_not_touched(
    pr: PullRequest, github: FakeGitHub
) -> None:
    other = github.add(8, f"{rr_action.marker_for('dc.yaml')}\nthe report of another pull request")
    run_step(pr.environment(github))
    assert github.comments[other]["body"].endswith("another pull request")
    assert len(github.on(7)) == 1


def test_three_pushes_leave_one_comment_for_each_file_and_it_is_the_latest(
    pr: PullRequest, github: FakeGitHub
) -> None:
    seen: dict[str, int] = {}
    for push in range(1, 4):
        for name in ("dc.yaml", "other.yaml"):
            pr.push(push, name)
            assert run_step(pr.environment(github, head=name)) == 0
            comments = [c for c in github.on(7) if c["body"].startswith(rr_action.marker_for(name))]
            assert len(comments) == 1, f"push {push}: {len(comments)} comments for {name}"
            assert f"Pushed {push} times" in comments[0]["body"]
            seen.setdefault(name, comments[0]["id"])
            assert comments[0]["id"] == seen[name]  # it is updated, never replaced
        assert len(github.on(7)) == 2  # one for each file, however many pushes
    assert [call.split()[0] for call in github.calls].count("POST") == 2


# ----------------------------------------------------------------------------- the install


def test_the_install_makes_a_virtual_environment_and_installs_this_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert rr_action.main(["install"], {"RUNNER_TEMP": str(tmp_path)}) == 0
    venv = tmp_path / "ripplerack-venv"
    assert commands[0] == [sys.executable, "-m", "venv", str(venv)]
    root = Path(rr_action.__file__).resolve().parent.parent
    assert commands[1][1:3] == ["-m", "pip"]
    assert commands[1][-1] == str(root)
    assert (root / "pyproject.toml").is_file()
    assert commands[1][0] == str(rr_action.venv_executable(tmp_path, "python"))


def test_a_failed_install_says_what_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", failing)
    assert rr_action.main(["install"], {"RUNNER_TEMP": str(tmp_path)}) == 1
    out = capsys.readouterr().out
    assert "::error::could not install RippleRack" in out
    assert "::endgroup::" in out  # the group is closed even then


# --------------------------------------------------------------------------- the counts


def diff_document(files: dict[str, Any], folder: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    write_files(files, folder)
    monkeypatch.chdir(folder)
    result = runner.invoke(app, ["diff", "base.yaml", "head.yaml", "-F", "json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def two_changes_one_under_the_other() -> dict[str, Any]:
    """A pipeline is at risk of one change and broken by another: customer-360 feeds a reader."""
    data = raw_datacenter()
    data["pipelines"].append(
        {
            "id": "profile-export",
            "runs_on": "spark",
            "inputs": [{"pipeline": "customer-360", "fields": ["lifetime_orders"]}],
            "schema": {
                "name": "export",
                "version": "1.0.0",
                "fields": [{"name": "x", "type": "string"}],
            },
        }
    )
    return data


def test_a_pipeline_broken_by_one_change_is_not_counted_as_at_risk_of_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = two_changes_one_under_the_other()
    head = two_changes_one_under_the_other()
    ingest = pipeline_of(head, "orders-ingest")["schema"]
    ingest["version"] = "2.0.0"
    ingest["fields"] = [f for f in ingest["fields"] if f["name"] != "amount"]
    ingest["fields"].append({"name": "amount_cents", "type": "integer"})
    pipeline_of(head, "orders-enriched")["inputs"][0]["fields"] = [
        "order_id",
        "customer_id",
        "amount_cents",
        "currency",
        "created_at",
    ]
    profile = pipeline_of(head, "customer-360")["schema"]
    profile["version"] = "1.0.0"
    profile["fields"][1]["type"] = "string"  # lifetime_orders
    document = diff_document({"base.yaml": base, "head.yaml": head}, tmp_path, monkeypatch)

    changes = {change["pipeline"]: change for change in document["schemaChanges"]}
    assert {c["pipeline"] for c in changes["orders-ingest"]["brokenConsumers"]} == {"customer-360"}
    assert {c["pipeline"] for c in changes["customer-360"]["brokenConsumers"]} == {"profile-export"}
    # the same pipeline is broken by one change and at risk of the other: the lists overlap...
    assert "profile-export" in changes["orders-ingest"]["atRisk"]
    # ...and the count takes it out of the pipelines at risk, as it is broken already
    at_risk = {name for change in changes.values() for name in change["atRisk"]}
    assert at_risk == {"api", "profile-export"}
    assert rr_action.at_risk_count(document) == 1
    assert rr_action.summarize(document) == ("critical", 2, 1)


def golden_documents() -> list[tuple[str, dict[str, Any]]]:
    paths = sorted(GOLDEN.glob("diff_*.json")) + sorted(GOLDEN.glob("impact_*.json"))
    return [(path.name, json.loads(path.read_text(encoding="utf-8"))) for path in paths]


@pytest.mark.parametrize(
    ("name", "document"), golden_documents(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_no_change_has_a_pipeline_that_is_broken_and_at_risk_at_once(
    name: str, document: dict[str, Any]
) -> None:
    reports = document["schemaChanges"] if document["command"] == "diff" else [document]
    for report in reports:
        broken = {consumer["pipeline"] for consumer in report["brokenConsumers"]}
        assert not broken & set(report["atRisk"]), name


def test_the_outputs_of_every_comparison_are_fixed_by_a_golden_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs: dict[str, dict[str, Any]] = {}
    for name in (n for n in SCENARIOS if n.startswith("diff_")):
        files, args = SCENARIOS[name]()
        write_files(files, tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [*args, "-F", "json"])
        assert result.exit_code == 0, result.output
        severity, broken, at_risk = rr_action.summarize(json.loads(result.stdout))
        outputs[name] = {"severity": severity, "broken-count": broken, "at-risk-count": at_risk}
    assert_text_golden("action_outputs.json", json.dumps(outputs, indent=2) + "\n")
