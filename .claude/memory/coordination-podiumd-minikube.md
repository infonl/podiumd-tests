---
name: coordination-podiumd-minikube
description: Coordinate with the podiumd-minikube agent before disruptive actions on the shared live minikube
metadata:
  type: feedback
---

# Coordination with podiumd-minikube

The podiumd-minikube agent works on the same live minikube at the same time: it changes its chart and redeploys, and keeps the configuration as close as possible to ExternalsPodiumD and podiumd-infra. The user asked to coordinate so the two agents do not interfere (2026-10-07).

**Why:** its deploys deleted podiumd-tests' credentials Secret twice, and its restarts and configuration changes broke running tests; podiumd-tests' bootstrap changes shared configuration it also manages.

**How to apply:**

- Disruptive actions take the lock file `/home/kvv/development/werk/infonl-dimpact/infonl/.minikube-lock` (one line: who, what, start time) and release it afterwards; if another agent holds it, wait or message it. podiumd-tests' CLI does this itself for `bootstrap`, `unbootstrap` and non-smoke runs when the profile sets `settings.lock_file`.
- Disruptive for podiumd-tests: bootstrap, unbootstrap, `--rotate`, write-heavy test runs. Not disruptive: read-only checks and smoke tests.
- Send the podiumd-minikube session a short message (SendMessage) before and after a disruptive action, and before changing anything it might also configure.
- Ownership (user, 2026-10-07): anything for setup and deploys belongs to podiumd-minikube (what QA/podiumd-infra and ExternalsPodiumD deploy); anything for testing, including seeding and test cleanup, belongs to podiumd-tests (what TA and ExternalsPodiumD's testing do, e.g. `seed-omgeving.sh`, `seed-identities.sh`). podiumd-tests owns `ptest-bootstrap-*` objects, the Secret `podiumd-tests-credentials` and its PLAN.md §4 A2 wiring, which never overrides an environment owner's configuration.
- Findings in podiumd-minikube go into the handoff file, never as direct changes to that repository or its live configuration.

Related: [[feedback-handoff-docs]], [[reuse-existing-logic]].
