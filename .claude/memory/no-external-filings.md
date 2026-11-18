# No external tickets or filings

**Never create, edit, comment on or react to anything outside our own repositories** (Kees, 2026-11-18: "no external
tickets or filings !!"): no issues, PRs, discussions or comments in maykinmedia, pravega,
infonl/dimpact-zaakafhandelcomponent, Dimpact-Samenwerking or any other external repository; no Jira, Taiga, forum or
mailing-list posts.

**Why:** an upstream issue opened by mistake (2026-11-18) put internal measurements and environment details in the
open; a closed and blanked issue keeps its text in the edit history.

**How to apply:**

- "File" always means register in the private infonl/podiumd-known-issues repository. Kees reports upstream himself.
- Before any `gh issue create`, `gh pr create`, `gh issue comment` or `gh api` write against a repository that is not
  ours: do not run it. Put a draft in podiumd-known-issues and tell Kees.
- A third-party defect gets an interim fix at the level we control (podiumd chart via the helm-charts session, estate
  values); remove it once upstream releases a fix.

Related: [[xfail-markers]], [[coordination-podiumd-minikube]].
