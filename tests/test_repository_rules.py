"""Guard the configuration boundaries that prevent privileged PR-code execution."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_rules_require_pr_checks_without_owner_or_admin_bypass():
    config = json.loads((ROOT / ".github/rulesets/main.json").read_text())
    assert config["bypass_actors"] == []
    assert config["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    rules = {r["type"]: r.get("parameters") for r in config["rules"]}
    assert {"pull_request", "deletion", "non_fast_forward", "code_scanning"} <= rules.keys()
    assert rules["pull_request"]["required_review_thread_resolution"]
    assert rules["pull_request"]["required_approving_review_count"] == 0
    assert not rules["pull_request"]["require_code_owner_review"]
    assert {r["context"] for r in rules["required_status_checks"]["required_status_checks"]} == {
        "PR gate",
        "Security gate",
        "Copilot review",
    }
    assert all(
        r["integration_id"] == 15368
        for r in rules["required_status_checks"]["required_status_checks"]
    )


def test_privileged_review_workflow_only_executes_default_branch_code():
    config = yaml.load((ROOT / ".github/workflows/copilot-review.yml").read_text(), yaml.BaseLoader)
    assert config["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
        "statuses": "write",
    }
    steps = config["jobs"]["reconcile"]["steps"]
    assert steps[0]["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert steps[0]["with"]["persist-credentials"] == "false"
    assert len(steps) == 3
    assert steps[-1]["run"] == "uv run --no-project python -m devtools.review_gate"
    assert all("pull_request.head" not in str(step) for step in steps)
    assert all("download-artifact" not in step.get("uses", "") for step in steps)
