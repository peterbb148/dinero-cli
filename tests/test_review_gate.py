"""Review metadata is evidence; a request or old review is not a completed review."""

import json
import subprocess

import pytest

from devtools import review_gate as gate

HEAD = "a" * 40


def review(**changes):
    return {
        "id": 1,
        "commit_id": HEAD,
        "state": "COMMENTED",
        "submitted_at": "2026-09-20",
        "user": {"id": gate.BOT_ID, "login": gate.BOT_LOGIN, "type": "Bot"},
        **changes,
    }


@pytest.mark.parametrize(
    "reviews,state",
    [
        ([], "failure"),
        ([review()], "success"),
        ([review(state="APPROVED")], "success"),
        ([review(commit_id="old")], "failure"),
        ([review(submitted_at=None)], "failure"),
        ([review(state="DISMISSED")], "failure"),
        ([review(state="CHANGES_REQUESTED")], "failure"),
        ([review(user={"id": 1, "login": gate.BOT_LOGIN, "type": "Bot"})], "failure"),
        ([review(user={"id": gate.BOT_ID, "login": "other", "type": "Bot"})], "failure"),
        ([review(user={"id": gate.BOT_ID, "login": gate.BOT_LOGIN, "type": "User"})], "failure"),
        ([review(), review(id=2, state="DISMISSED")], "failure"),
    ],
)
def test_decisions(reviews, state):
    assert gate.decision(HEAD, reviews)[0] == state


def test_paginated_api_uses_checked_subprocess_without_shell(monkeypatch):
    def run(args, **kwargs):
        assert args == ["gh", "api", "path", "--paginate", "--slurp"]
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        return subprocess.CompletedProcess(args, 0, json.dumps([[{"id": 1}], [{"id": 2}]]))

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.pages("path") == [{"id": 1}, {"id": 2}]


def test_reconcile_drafts_forks_bots_and_unchanged_statuses(monkeypatch):
    posted = []
    state, description = gate.decision(HEAD, [review()])

    def api(path, *args):
        if "/pulls?" in path:
            return [
                [
                    {"number": n, "head": {"sha": str(n)}, "html_url": f"https://example/{n}"}
                    for n in range(1, 4)
                ]
            ]
        if "/reviews?" in path:
            return [[review(commit_id=path.split("/")[-2])]]
        if "/commits/3/statuses?" in path:
            return [[{"context": gate.CONTEXT, "state": state, "description": description}]]
        if "/statuses?" in path:
            return [[]]
        posted.append((path, args))
        return {}

    monkeypatch.setattr(gate, "api", api)
    gate.reconcile("owner/repo")
    assert [p for p, args in posted] == [
        "repos/owner/repo/statuses/1",
        "repos/owner/repo/statuses/2",
    ]
    assert all("state=success" in args for _, args in posted)


def test_main_and_api_failure_are_not_silenced(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    calls = []
    monkeypatch.setattr(gate, "reconcile", calls.append)
    gate.main()
    assert calls == ["owner/repo"]

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(gate.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        gate.api("path")
