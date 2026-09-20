# Repository rules

`main.json` is the final main ruleset: no bypass actors, PR-only changes, no deletion
or force pushes, resolved review threads, squash merges, up-to-date PR/Security/Copilot
checks from GitHub Actions and CodeQL without high/critical findings or error alerts.
`PR gate` includes lint/typecheck/tests/coverage and all four native builds when build
inputs change. Documentation-only changes need no binary build. New-code coverage >80%
remains a measured review obligation alongside the existing 81% aggregate CI threshold.

CODEOWNERS assigns all files to @peterbb148. Required human approvals remain zero because
the sole owner cannot approve their own PRs. Copilot's COMMENTED review is sufficient for
the separate completion check; Copilot approvals are not enabled or treated as codeowner
approval. Review comments must still be addressed and threads resolved.

`copilot.json` requests reviews for every branch, including drafts and every push.
GitHub only automatically requests Copilot when access/quota permits; native request
policy is not completion enforcement. If a fork/bot author's PR does not receive an
automatic review, the owner must request one using their eligible account. The completion
gate applies equally to drafts, forks and bot PRs, with no author-based bypass.

The metadata-only review workflow checks the real Copilot bot ID, submitted review state
and exact head SHA. It runs trusted default-branch code, never PR code or downloaded PR
artifacts, on PR events, after CI/Security, on demand and every five minutes. Scheduled
runs may be delayed by GitHub. A new commit has no passing status until reviewed; missing,
dismissed, stale or changes-requested reviews produce a failing status. API errors fail
the job rather than inventing success. Review-state changes are reflected on the next
reconciliation; thread resolution is enforced natively at merge.

## Activation order

1. Correct the default branch to main and enable squash merges.
2. Enable the automatic-review ruleset. Apply a bootstrap main ruleset with PR-only,
   no bypass/deletion/force-push, resolved threads and required PR gate. This protects
   main while the new workflows are still being delivered through PRs.
3. Merge the licensing, security and review-workflow PRs. Verify main CodeQL analysis
   and run `Copilot review gate` from main to establish the trusted commit-status source.
4. Replace the bootstrap ruleset with `main.json` using the existing ruleset ID. Verify
   the returned rule configuration and reject a direct push without adding a bypass.

Create/update rules using `gh api repos/peterbb148/dinero-cli/rulesets` (POST to create,
PUT to `.../rulesets/ID` to update, `--input` with the relevant JSON file). Repository
administration permissions are required; ordinary workflow tokens cannot alter rules.
Do not activate checks before their trusted workflow is on main, or claim that the
bootstrap policy already enforces completed Copilot review/security findings.
