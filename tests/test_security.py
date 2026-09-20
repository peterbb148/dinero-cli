"""Security boundaries that must survive workflow maintenance."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_security_jobs_use_safe_events_and_minimal_permissions():
    workflow = yaml.load((ROOT / ".github/workflows/security.yml").read_text(), yaml.BaseLoader)
    assert set(workflow["on"]) == {"pull_request", "push", "schedule", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["codeql"]["permissions"] == {
        "contents": "read",
        "security-events": "write",
    }
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                revision = step["uses"].split("@")[1]
                assert len(revision) == 40 and int(revision, 16)
    gate = workflow["jobs"]["gate"]
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == {"codeql", "dependencies"}
    review = workflow["jobs"]["dependencies"]["steps"][0]["with"]
    assert review["fail-on-severity"] == "high"
    assert "development" in review["fail-on-scopes"]
    assert review["comment-summary-in-pr"] == "never"


def test_dependabot_covers_locked_python_and_action_revisions():
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    assert {item["package-ecosystem"] for item in config["updates"]} == {"uv", "github-actions"}
    assert all(item["schedule"]["interval"] == "weekly" for item in config["updates"])
