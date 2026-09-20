import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import build, release

ROOT = Path(__file__).resolve().parents[1]
HEAD = "2" * 40
OLD = "1" * 40
DIGEST = "a" * 64
OTHER = "b" * 64


def record(tag="v0.1.0", digest=DIGEST, commit=OLD, draft=False):
    return {
        "id": 1,
        "tag_name": tag,
        "draft": draft,
        "prerelease": False,
        "assets": [],
        "body": release.MARKER + json.dumps({"commit": commit, "fingerprint": digest}) + " -->",
    }


@pytest.fixture
def repository(tmp_path, monkeypatch):
    project = (ROOT / "pyproject.toml").read_text()
    lock = (ROOT / "uv.lock").read_text()
    monkeypatch.chdir(tmp_path)
    release.run("git", "init", "-q")
    release.run("git", "config", "user.email", "test@example.invalid")
    release.run("git", "config", "user.name", "Test")
    release.run("git", "commit", "--allow-empty", "-qm", "empty")
    assert release.fingerprint("HEAD") is None
    Path("src/dinero_cli").mkdir(parents=True)
    Path("src/dinero_cli/cli.py").write_text("initial")
    Path("pyproject.toml").write_text(project)
    Path("uv.lock").write_text(lock)
    commit()
    return tmp_path


def commit():
    release.run("git", "add", ".")
    release.run("git", "commit", "-qm", "test change")
    return release.git("rev-parse", "HEAD")


def test_docs_tests_and_dev_config_do_not_change_binary_identity(repository):
    original = release.fingerprint("HEAD")
    Path("README.md").write_text("Documentation")
    Path("tests").mkdir()
    Path("tests/test_example.py").write_text("# Tests only")
    p = Path("pyproject.toml")
    p.write_text(p.read_text().replace("line-length = 100", "line-length = 99"))
    commit()
    assert release.fingerprint("HEAD") == original


def test_sources_rename_delete_and_bundled_markdown_are_build_inputs(repository):
    original = release.fingerprint("HEAD")
    resource = Path("src/dinero_cli/template.md")
    resource.write_text("Bundled runtime resource")
    commit()
    added = release.fingerprint("HEAD")
    assert added != original
    resource.rename(resource.with_name("renamed.md"))
    commit()
    renamed = release.fingerprint("HEAD")
    assert renamed != added
    resource.with_name("renamed.md").unlink()
    commit()
    assert release.fingerprint("HEAD") == original
    Path("README.md").write_text("Mixed change")
    Path("src/dinero_cli/cli.py").write_text("updated")
    commit()
    assert release.fingerprint("HEAD") != original


@pytest.mark.parametrize(
    "path",
    [
        ".python-version",
        "scripts/build.py",
        "scripts/release.py",
        ".github/workflows/cd.yml",
        "packaging/notices.txt",
    ],
)
def test_build_configuration_changes_trigger_release(repository, path):
    original = release.fingerprint("HEAD")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("new build input")
    commit()
    assert release.fingerprint("HEAD") != original


def test_dev_only_lock_update_is_ignored_but_runtime_update_is_not(repository):
    path = Path("uv.lock")
    initial = path.read_text()
    original = release.fingerprint("HEAD")
    path.write_text(initial.replace('name = "ruff"\nversion = "', 'name = "ruff"\nversion = "9'))
    commit()
    assert release.fingerprint("HEAD") == original
    path.write_text(initial.replace('name = "typer"\nversion = "', 'name = "typer"\nversion = "9'))
    commit()
    assert release.fingerprint("HEAD") != original


def test_invalid_lock_fails_instead_of_skipping():
    with pytest.raises(ValueError, match="exactly one"):
        release.normalized("uv.lock", "package = []")
    assert release.normalized("other", "abc") == "abc"


def test_unbuildable_and_unchanged_do_not_allocate_versions():
    assert release.decide(HEAD, None, [], [])["build"] == "false"
    result = release.decide(HEAD, DIGEST, [record()], [])
    assert result["build"] == "false" and result["tag"] == ""


def test_first_release_and_minor_increment():
    assert release.decide(HEAD, DIGEST, [], [])["tag"] == "v0.1.0"
    assert release.decide(HEAD, OTHER, [record()], ["v0.1.0"])["tag"] == "v0.2.0"
    assert release.decide(HEAD, OTHER, [], ["v2.9.0", "unrelated"])["tag"] == "v2.10.0"


def test_failed_release_reuses_reserved_version_even_after_docs_merge():
    pending = record(tag="v0.2.0", digest=OTHER, draft=True)
    result = release.decide(HEAD, OTHER, [record(), pending], ["v0.1.0"])
    assert result["tag"] == "v0.2.0"
    assert result["commit"] == OLD
    assert result["reason"] == "Resume draft"
    with pytest.raises(ValueError, match="pending"):
        release.decide(HEAD, "c" * 64, [pending], [])


def test_old_released_commit_is_not_republished():
    releases = [record(), record("v0.2.0", OTHER, HEAD)]
    assert release.decide(OLD, DIGEST, releases, [])["build"] == "false"


def test_managed_metadata_is_validated_and_other_releases_ignored():
    assert release.metadata({"body": "Unrelated"}) == {}
    with pytest.raises(ValueError):
        release.metadata(record(tag="bad"))
    with pytest.raises(ValueError):
        release.metadata(record(commit="bad"))
    with pytest.raises(ValueError):
        release.version_key("bad")
    assert release.version_key("v3.12.0") == (3, 12)


def test_list_releases_handles_pagination(monkeypatch):
    monkeypatch.setattr(release, "gh", lambda *args: json.dumps([[record()], [record("v0.2.0")]]))
    assert len(release.list_releases("owner/repo")) == 2


def test_plan_reserves_only_changed_build(monkeypatch):
    calls = []
    monkeypatch.setattr(release, "fingerprint", lambda ref: DIGEST)
    monkeypatch.setattr(release, "list_releases", lambda repo: [])
    monkeypatch.setattr(release, "git", lambda *args: HEAD if args[0] == "rev-parse" else "")

    def fake_gh(*args):
        calls.append(args)
        if args[0] == "api":
            return json.dumps({"body": "Release notes"})
        notes = Path(args[args.index("--notes-file") + 1]).read_text()
        assert release.MARKER in notes
        return ""

    monkeypatch.setattr(release, "gh", fake_gh)
    assert release.plan("owner/repo", "HEAD")["tag"] == "v0.1.0"
    assert len(calls) == 2
    calls.clear()
    monkeypatch.setattr(release, "list_releases", lambda repo: [record()])
    assert release.plan("owner/repo", "HEAD")["build"] == "false"
    assert calls == []


def test_queued_old_run_does_not_roll_back_newer_release(monkeypatch):
    monkeypatch.setattr(release, "fingerprint", lambda ref: OTHER)
    monkeypatch.setattr(release, "list_releases", lambda repo: [record(commit=HEAD)])
    monkeypatch.setattr(release, "git", lambda *args: OLD)
    assert release.plan("owner/repo", OLD)["reason"] == "Superseded by published descendant"


def archives(directory, tag="v0.1.0"):
    for name in release.asset_names(tag) - {"SHA256SUMS"}:
        (directory / name).write_bytes(name.encode())
    build.checksums(directory)


def test_asset_verification_rejects_missing_duplicate_and_corrupt_files(tmp_path):
    archives(tmp_path)
    assert len(release.verify_assets(tmp_path, "v0.1.0")) == 5
    manifest = tmp_path / "SHA256SUMS"
    original = manifest.read_text()
    manifest.write_text(original + original.splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        release.verify_assets(tmp_path, "v0.1.0")
    manifest.write_text(original.splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="Missing"):
        release.verify_assets(tmp_path, "v0.1.0")
    manifest.write_text(original)
    binary = next(tmp_path.glob("*.zip"))
    binary.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        release.verify_assets(tmp_path, "v0.1.0")
    binary.unlink()
    with pytest.raises(ValueError, match="exactly four"):
        release.verify_assets(tmp_path, "v0.1.0")


def test_retention_preserves_latest_two_drafts_tags_and_unrelated_assets(monkeypatch):
    releases = [record(f"v0.{i}.0") for i in range(1, 5)]
    for index, r in enumerate(releases):
        r["assets"] = [
            {"id": index, "name": f"dinero-{r['tag_name']}-linux-arm64.zip"},
            {"id": 100 + index, "name": "user-file.zip"},
        ]
    releases.append(record("v0.5.0", draft=True))
    releases.append({"body": "User release", "draft": False})
    calls = []
    monkeypatch.setattr(release, "list_releases", lambda repo: releases)
    monkeypatch.setattr(release, "gh", lambda *args: calls.append(args))
    release.cleanup("owner/repo")
    assert {c[-1] for c in calls} == {
        "repos/owner/repo/releases/assets/0",
        "repos/owner/repo/releases/assets/1",
    }
    assert all(c[0:3] == ("api", "--method", "DELETE") for c in calls)


def test_publication_happens_after_upload_and_before_cleanup(tmp_path, monkeypatch):
    archives(tmp_path)
    calls = []
    monkeypatch.setattr(release, "list_releases", lambda repo: [record(draft=True)])
    monkeypatch.setattr(release, "cleanup", lambda repo: calls.append(("cleanup",)))

    def fake_gh(*args):
        calls.append(args)
        if args[0] == "api":
            return json.dumps(
                {"assets": [{"name": p.name, "size": p.stat().st_size} for p in tmp_path.iterdir()]}
            )
        return ""

    monkeypatch.setattr(release, "gh", fake_gh)
    release.publish("owner/repo", "v0.1.0", tmp_path)
    assert calls[0][0:2] == ("release", "upload")
    assert calls[-2][0:2] == ("release", "edit")
    assert calls[-1] == ("cleanup",)


def test_partial_upload_never_publishes_or_cleans_up(tmp_path, monkeypatch):
    archives(tmp_path)
    calls = []
    monkeypatch.setattr(release, "list_releases", lambda repo: [record(draft=True)])
    monkeypatch.setattr(release, "gh", lambda *args: calls.append(args) or '{"assets": []}')
    with pytest.raises(ValueError, match="incomplete"):
        release.publish("owner/repo", "v0.1.0", tmp_path)
    assert not any("edit" in call or "DELETE" in call for call in calls)
    monkeypatch.setattr(release, "list_releases", lambda repo: [])
    with pytest.raises(ValueError, match="reserved"):
        release.publish("owner/repo", "v0.1.0", tmp_path)


def test_publication_rerun_only_retries_retention(tmp_path, monkeypatch):
    archives(tmp_path)
    monkeypatch.setattr(release, "list_releases", lambda repo: [record()])
    called = []
    monkeypatch.setattr(
        release, "gh", lambda *args: pytest.fail("Must not overwrite published assets")
    )
    monkeypatch.setattr(release, "cleanup", lambda repo: called.append(repo))
    release.publish("owner/repo", "v0.1.0", tmp_path)
    assert called == ["owner/repo"]


def test_job_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    release.output({"build": "false"})
    assert (tmp_path / "outputs").read_text() == "build=false\n"
    assert json.loads(capsys.readouterr().out) == {"build": "false"}
    with pytest.raises(ValueError, match="Multiline"):
        release.output({"bad": "one\ntwo"})


def test_command_failure_propagates():
    with pytest.raises(subprocess.CalledProcessError):
        release.run(sys.executable, "-c", "raise SystemExit(3)")


@pytest.mark.parametrize("args", [["pr"], ["plan"], ["publish", "--repo", "a/b"]])
def test_cli_missing_inputs_fail(args, monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setattr(sys, "argv", ["release", *args])
    with pytest.raises(SystemExit) as exc:
        release.main()
    assert exc.value.code == 2


def test_cli_dispatch(repository, monkeypatch, capsys):
    head = release.git("rev-parse", "HEAD")
    monkeypatch.setattr(sys, "argv", ["release", "pr", "--base", head])
    release.main()
    assert json.loads(capsys.readouterr().out)["build"] == "false"
    monkeypatch.setattr(release, "plan", lambda *args: {"build": "false"})
    monkeypatch.setattr(sys, "argv", ["release", "plan", "--repo", "a/b"])
    release.main()
    assert json.loads(capsys.readouterr().out)["build"] == "false"
    calls = []
    monkeypatch.setattr(release, "publish", lambda *args: calls.append(args))
    monkeypatch.setattr(sys, "argv", ["release", "publish", "--repo", "a/b", "--tag", "v0.1.0"])
    release.main()
    assert calls[0][:2] == ("a/b", "v0.1.0")
    monkeypatch.setattr(release, "cleanup", lambda repo: calls.append(repo))
    monkeypatch.setattr(sys, "argv", ["release", "cleanup", "--repo", "a/b"])
    release.main()
    assert calls[-1] == "a/b"


def test_constitution_and_precommit_do_not_trigger_release(repository):
    original = release.fingerprint("HEAD")
    for name in (
        ".specify/memory/constitution.md",
        ".pre-commit-config.yaml",
        "devtools/contracts.py",
        "tests/contracts/test_cli.py",
        ".github/workflows/ci.yml",
    ):
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Development-only change")
    commit()
    assert release.fingerprint("HEAD") == original
