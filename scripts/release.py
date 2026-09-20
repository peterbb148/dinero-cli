"""Deterministic build-input detection and GitHub release lifecycle.

Invoked with UV in trusted main jobs; PR planning is strictly read-only.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any

VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.0")
MARKER = "<!-- dinero-cd:v1 "
TARGETS = ("linux-x86_64", "linux-arm64", "windows-x86_64", "windows-arm64")
BUILD_FILES = {
    ".python-version",
    ".gitattributes",
    "LICENSE",
    "NOTICE",
    "scripts/notices.py",
    "pyproject.toml",
    "uv.lock",
    "scripts/build.py",
    "scripts/entrypoint.py",
    "scripts/release.py",
    ".github/workflows/cd.yml",
    ".github/workflows/binaries.yml",
}


def run(*args: str) -> str:
    """Run a checked command without a shell and return stdout."""
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def git(*args: str) -> str:
    """Execute a read-only Git query."""
    return run("git", *args)


def gh(*args: str) -> str:
    """Execute a GitHub CLI command; failures must stop the release."""
    return run("gh", *args)


def relevant(path: str) -> bool:
    """Identify build inputs, including bundled resources of any extension."""
    return path in BUILD_FILES or path.startswith(("src/", "assets/", "packaging/"))


def normalized(path: str, content: str) -> str:
    """Exclude test/lint configuration and dev-only lock entries from build identity."""
    if path == "pyproject.toml":
        data = tomllib.loads(content)
        data = {
            "project": data["project"],
            "build-system": data["build-system"],
            "build": data.get("dependency-groups", {}).get("build", []),
            "uv": data.get("tool", {}).get("uv", {}),
            "hatch": data.get("tool", {}).get("hatch", {}),
        }
        # README is not bundled; it is only project-page metadata.
        data["project"].pop("readme", None)
        return json.dumps(data, sort_keys=True)
    if path == "uv.lock":
        data = tomllib.loads(content)
        packages = data["package"]
        roots = [p for p in packages if p["name"] == "dinero-cli"]
        if len(roots) != 1:
            raise ValueError("Lockfile must contain exactly one dinero-cli project")
        root = roots[0]
        needed = {d["name"] for d in root.get("dependencies", [])}
        needed.update(d["name"] for d in root.get("dev-dependencies", {}).get("build", []))
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        while needed - seen:
            names = needed - seen
            seen.update(names)
            for package in packages:
                if package["name"] in names:
                    selected.append(package)
                    needed.update(d["name"] for d in package.get("dependencies", []))
        return json.dumps(
            sorted(selected, key=lambda p: json.dumps(p, sort_keys=True)), sort_keys=True
        )
    return content


def fingerprint(ref: str) -> str | None:
    """Hash tracked build inputs at a commit, including modes and deletions.

    Return None only when there is no buildable CLI at that commit.
    """
    entries = git("ls-tree", "-r", "-z", ref).split("\0")
    rows = [entry.split("\t", 1) for entry in entries if entry]
    paths = {row[1] for row in rows}
    if not {"src/dinero_cli/cli.py", "pyproject.toml", "uv.lock"} <= paths:
        return None
    digest = hashlib.sha256()
    for metadata, path in sorted(rows, key=lambda row: row[1]):
        if relevant(path):
            mode, kind, oid = metadata.split()
            if kind != "blob":
                raise ValueError(f"Unsupported build input: {path}")
            value = (
                normalized(path, git("show", f"{ref}:{path}"))
                if path in {"pyproject.toml", "uv.lock"}
                else oid
            )
            digest.update(json.dumps([mode, path, value]).encode())
    return digest.hexdigest()


def metadata(release: dict[str, Any]) -> dict[str, str]:
    """Read our own release marker; unrelated releases are never cleaned up."""
    body = release.get("body") or ""
    if MARKER not in body:
        return {}
    value = json.loads(body.split(MARKER, 1)[1].split(" -->", 1)[0])
    if (
        not VERSION.fullmatch(release["tag_name"])
        or not re.fullmatch(r"[0-9a-f]{40}", value["commit"])
        or not re.fullmatch(r"[0-9a-f]{64}", value["fingerprint"])
    ):
        raise ValueError("Invalid managed release metadata")
    return value


def version_key(tag: str) -> tuple[int, int]:
    """Parse a managed minor version."""
    match = VERSION.fullmatch(tag)
    if match is None:
        raise ValueError(f"Not a minor release tag: {tag}")
    return int(match[1]), int(match[2])


def decide(
    head: str, digest: str | None, releases: list[dict[str, Any]], tags: list[str]
) -> dict[str, str]:
    """Choose skip, resume, or the next minor release without mutations."""
    result = {"build": "false", "commit": head, "version": "", "tag": ""}
    if digest is None:
        return result | {"reason": "No buildable CLI"}
    managed = sorted(
        [r for r in releases if metadata(r)], key=lambda r: version_key(r["tag_name"]), reverse=True
    )
    published = [r for r in managed if not r["draft"] and not r["prerelease"]]
    if published and metadata(published[0])["fingerprint"] == digest:
        return result | {"reason": "Build inputs unchanged"}
    # A rerun of an older, already released commit must not publish it again.
    if any(metadata(r)["commit"] == head for r in published):
        return result | {"reason": "Commit already released"}
    drafts = [r for r in managed if r["draft"]]
    if drafts:
        if len(drafts) != 1 or metadata(drafts[0])["fingerprint"] != digest:
            raise ValueError("A different release is pending. Retry its failed CD run first.")
        tag = drafts[0]["tag_name"]
        return result | {
            "build": "true",
            "commit": metadata(drafts[0])["commit"],
            "version": tag[1:],
            "tag": tag,
            "reason": "Resume draft",
        }
    used = [version_key(t) for t in tags if VERSION.fullmatch(t)]
    used.extend(version_key(r["tag_name"]) for r in managed)
    major, minor = max(used, default=(0, 0))
    tag = f"v{major}.{minor + 1}.0"
    return result | {
        "build": "true",
        "version": tag[1:],
        "tag": tag,
        "reason": "Build inputs changed",
    }


def list_releases(repo: str) -> list[dict[str, Any]]:
    """Read every page; retained release notes must not hide newer/older assets."""
    pages = json.loads(gh("api", f"repos/{repo}/releases?per_page=100", "--paginate", "--slurp"))
    return [release for page in pages for release in page]


def output(values: dict[str, str]) -> None:
    """Write machine-readable job outputs and a non-secret diagnostic."""
    if destination := os.environ.get("GITHUB_OUTPUT"):
        with Path(destination).open("a") as handle:
            for key, value in values.items():
                if "\n" in value:
                    raise ValueError("Multiline job output is not supported")
                handle.write(f"{key}={value}\n")
    print(json.dumps(values, sort_keys=True))


def plan(repo: str, head: str) -> dict[str, str]:
    """Reserve a draft only when real build inputs changed."""
    head = git("rev-parse", f"{head}^{{commit}}")
    digest = fingerprint(head)
    releases = list_releases(repo)
    # Prevent a queued old run from rolling back a newer published release.
    for release in releases:
        info = metadata(release)
        if info and not release["draft"]:
            ancestor = git("merge-base", head, info["commit"])
            if ancestor == head and info["commit"] != head:
                return {
                    "build": "false",
                    "commit": head,
                    "version": "",
                    "tag": "",
                    "reason": "Superseded by published descendant",
                }
    result = decide(head, digest, releases, git("tag", "--list").splitlines())
    if result["build"] == "true" and result["reason"] != "Resume draft":
        marker = MARKER + json.dumps({"commit": head, "fingerprint": digest}) + " -->"
        notes = gh(
            "api",
            "--method",
            "POST",
            f"repos/{repo}/releases/generate-notes",
            "-f",
            f"tag_name={result['tag']}",
            "-f",
            f"target_commitish={head}",
        )
        body = json.loads(notes)["body"] + "\n\n" + marker
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "notes.md"
            file.write_text(body)
            gh(
                "release",
                "create",
                result["tag"],
                "--repo",
                repo,
                "--target",
                head,
                "--draft",
                "--title",
                result["tag"],
                "--notes-file",
                str(file),
            )
    return result


def asset_names(tag: str) -> set[str]:
    """Enumerate exactly the assets owned by this workflow."""
    return {f"dinero-{tag}-{target}.zip" for target in TARGETS} | {"SHA256SUMS"}


def verify_assets(directory: Path, tag: str) -> list[Path]:
    """Verify all four archives and every checksum before publication."""
    expected = asset_names(tag)
    if {p.name for p in directory.iterdir()} != expected:
        raise ValueError("Release must contain exactly four target archives and SHA256SUMS")
    records = (directory / "SHA256SUMS").read_text().splitlines()
    found = set()
    for record in records:
        digest, name = record.split("  ", 1)
        if name not in expected - {"SHA256SUMS"} or name in found:
            raise ValueError("Unexpected or duplicate checksum entry")
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Checksum mismatch: {name}")
        found.add(name)
    if found != expected - {"SHA256SUMS"}:
        raise ValueError("Missing checksum entries")
    return sorted(directory.iterdir())


def cleanup(repo: str) -> None:
    """Keep binary assets for the latest two managed published releases only."""
    published = sorted(
        [r for r in list_releases(repo) if metadata(r) and not r["draft"] and not r["prerelease"]],
        key=lambda r: version_key(r["tag_name"]),
        reverse=True,
    )
    for release in published[2:]:
        for asset in release["assets"]:
            if asset["name"] in asset_names(release["tag_name"]):
                gh("api", "--method", "DELETE", f"repos/{repo}/releases/assets/{asset['id']}")


def publish(repo: str, tag: str, directory: Path) -> None:
    """Upload verified archives, publish atomically, then prune older binaries."""
    assets = verify_assets(directory, tag)
    matches = [r for r in list_releases(repo) if r["tag_name"] == tag and metadata(r)]
    if len(matches) != 1:
        raise ValueError("Expected one reserved managed release")
    release = matches[0]
    if release["draft"]:
        gh("release", "upload", tag, "--repo", repo, "--clobber", *map(str, assets))
        remote = json.loads(gh("api", f"repos/{repo}/releases/{release['id']}"))
        actual = {a["name"]: a["size"] for a in remote["assets"]}
        if actual != {p.name: p.stat().st_size for p in assets}:
            raise ValueError("Uploaded assets incomplete; draft remains unpublished")
        gh("release", "edit", tag, "--repo", repo, "--draft=false", "--latest")
    cleanup(repo)


def main() -> None:
    """Dispatch release tooling without implicit GitHub mutations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["pr", "plan", "publish", "cleanup"])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--base")
    parser.add_argument("--tag")
    parser.add_argument("--directory", type=Path, default=Path("dist/release"))
    args = parser.parse_args()
    if args.command == "pr":
        if not args.base:
            parser.error("pr requires --base")
        digest = fingerprint(args.head)
        output(
            {
                "build": str(digest is not None and digest != fingerprint(args.base)).lower(),
                "version": "0.0.0.dev0",
                "commit": git("rev-parse", args.head),
            }
        )
    else:
        if not args.repo:
            parser.error("--repo is required")
        if args.command == "plan":
            output(plan(args.repo, args.head))
        elif args.command == "publish":
            if not args.tag or not VERSION.fullmatch(args.tag):
                parser.error("publish requires --tag vMAJOR.MINOR.0")
            publish(args.repo, args.tag, args.directory)
        else:
            cleanup(args.repo)


if __name__ == "__main__":
    main()
