"""Publish a fail-closed commit status for Copilot review of each PR's current head.

Run only trusted default-branch code. PR contents, titles and artifacts are never executed.
"""

import json
import os
import subprocess
from typing import Any

CONTEXT = "Copilot review"
BOT_ID = 175728472
BOT_LOGIN = "copilot-pull-request-reviewer[bot]"


def decision(head: str, reviews: list[dict[str, Any]]) -> tuple[str, str]:
    """Require a submitted, non-dismissed review by the real Copilot bot for this SHA."""
    current = [
        r
        for r in reviews
        if r.get("commit_id") == head
        and r.get("user", {}).get("id") == BOT_ID
        and r.get("user", {}).get("login") == BOT_LOGIN
        and r.get("user", {}).get("type") == "Bot"
        and r.get("submitted_at")
    ]
    if not current:
        return "failure", "Copilot has not completed a review of the current commit"
    latest = max(current, key=lambda r: r["id"])
    if latest["state"] in {"COMMENTED", "APPROVED"}:
        return "success", "Copilot reviewed the current commit; resolve review threads before merge"
    return "failure", "Copilot review was dismissed or requested changes"


def api(path: str, *args: str) -> Any:
    """Call GitHub without shell expansion; API failures must remain visible."""
    result = subprocess.run(
        ["gh", "api", path, *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def pages(path: str) -> list[dict[str, Any]]:
    """Read all pages so an old review cannot hide the latest one."""
    return [item for page in api(path, "--paginate", "--slurp") for item in page]


def reconcile(repo: str) -> None:
    """Update open PR statuses from API metadata, including drafts, forks and bot PRs."""
    pulls = pages(f"repos/{repo}/pulls?state=open&base=main&per_page=100")
    for pull in pulls:
        number, head = pull["number"], pull["head"]["sha"]
        reviews = pages(f"repos/{repo}/pulls/{number}/reviews?per_page=100")
        state, description = decision(head, reviews)
        statuses = pages(f"repos/{repo}/commits/{head}/statuses?per_page=100")
        previous = next((s for s in statuses if s["context"] == CONTEXT), None)
        if previous and (previous["state"], previous["description"]) == (state, description):
            continue
        api(
            f"repos/{repo}/statuses/{head}",
            "--method",
            "POST",
            "-f",
            f"state={state}",
            "-f",
            f"context={CONTEXT}",
            "-f",
            f"description={description}",
            "-f",
            f"target_url={pull['html_url']}",
        )
        print(f"PR #{number}: {state}: {description}")


def main() -> None:
    """Reconcile only the repository supplied by the trusted workflow environment."""
    reconcile(os.environ["GITHUB_REPOSITORY"])


if __name__ == "__main__":
    main()
