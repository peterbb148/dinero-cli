from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def test_docs_changes_can_finish_required_pr_gate_without_binary_jobs():
    ci = load("ci.yml")
    assert "paths" not in (ci["on"]["pull_request"] or {})
    assert ci["jobs"]["gate"]["if"] == "always()"
    assert ci["jobs"]["binaries"]["if"] == "needs.changes.outputs.build == 'true'"
    assert ci["permissions"] == {"contents": "read"}
    assert "upload" not in ci["jobs"]["binaries"]["with"]


def test_cd_decides_before_version_build_and_publish():
    cd = load("cd.yml")
    assert cd["on"]["push"]["branches"] == ["main"]
    assert cd["concurrency"]["cancel-in-progress"] == "false"
    assert cd["concurrency"]["queue"] == "max"
    assert cd["jobs"]["plan"]["if"] == "github.ref == 'refs/heads/main'"
    for name in ("tests", "binaries", "publish"):
        assert cd["jobs"][name]["if"] == "needs.plan.outputs.build == 'true'"
    assert cd["jobs"]["publish"]["needs"] == ["plan", "binaries"]
    assert cd["jobs"]["cleanup"]["if"].startswith("always()")


def test_build_matrix_is_four_native_targets_and_actions_are_pinned():
    workflow = load("binaries.yml")
    matrix = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]
    assert {row["target"] for row in matrix} == {
        "linux-x86_64",
        "linux-arm64",
        "windows-x86_64",
        "windows-arm64",
    }
    assert len({row["runner"] for row in matrix}) == 4
    for file in ("ci.yml", "cd.yml", "binaries.yml"):
        for job in load(file)["jobs"].values():
            for step in job.get("steps", []):
                if "uses" in step:
                    revision = step["uses"].split("@")[1]
                    assert len(revision) == 40 and int(revision, 16)


def test_ci_runs_same_always_on_contract_hooks_as_local_commits():
    hooks = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())["repos"][0]["hooks"]
    assert {h["id"] for h in hooks} == {"ruff-check", "ruff-format", "cli-contracts"}
    contract = next(h for h in hooks if h["id"] == "cli-contracts")
    assert contract["always_run"] is True
    assert contract["pass_filenames"] is False
    assert "files" not in contract and "types" not in contract
    assert all(h["entry"].startswith("uv run --locked ") for h in hooks)
    steps = load("ci.yml")["jobs"]["checks"]["steps"]
    assert any(s.get("run") == "uv run --no-sync pre-commit run --all-files" for s in steps)
