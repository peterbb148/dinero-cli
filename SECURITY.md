# Security policy

## Reporting a vulnerability

Please use [GitHub private vulnerability reporting](https://github.com/peterbb148/dinero-cli/security/advisories/new).
Do not include credentials, tokens, accounting records or customer data in public issues.
Describe the affected version, impact and minimal reproduction using synthetic data.
Maintainer: @peterbb148. Reports are reviewed privately; coordinated disclosure follows
triage and a fix. No response-time SLA is promised.

## Supported versions

The latest two published binary release versions receive security fixes. Upgrade to the
latest release when possible; older versions are unsupported. Before two releases exist,
all published versions are supported. Security changes follow the normal release process.

## Automated controls

- CodeQL Python with `security-extended` runs on every PR to main, pushes to main, and
  Mondays at 06:17 UTC. It performs static analysis without running project build code.
- Dependency review rejects newly introduced high/critical vulnerabilities in runtime,
  development and unknown scopes. Dependabot checks UV and GitHub Actions weekly;
  vulnerability alerts and security updates are enabled at repository level.
- Secret scanning and push protection are enabled. Never bypass protection for a real
  credential: revoke it and remove it from the proposed commit.
- `Security gate` requires successful CodeQL and dependency-review execution. Findings
  are separate from successful analysis: the main ruleset in #16 must also require
  CodeQL results with no high/critical security findings or error-level alerts.
- Other findings require maintainer triage; dismissals need a documented justification.
  Copilot review supplements these controls and is not a vulnerability scanner.

PR workflows do not use `pull_request_target` or execute untrusted code with repository
write credentials. CodeQL's only elevated permission uploads SARIF results; GitHub
restricts fork-PR tokens and permits code-scanning uploads through its supported PR flow.
Actions are pinned to commit SHAs, and checkout does not persist credentials. Native
binary builds are required only when build inputs change, as defined by the PR gate.

Workflow schedules and Dependabot configuration become active when merged into the
repository's default branch. The default branch must be main (tracked in #16).
