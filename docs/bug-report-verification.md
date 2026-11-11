# Bug report verification

How the known defects found by this suite are re-checked against a PodiumD version and ranked, so that
anyone can repeat the check. The reports are in the private repository infonl/podiumd-known-issues; this
document holds only the method.

## Scope

- In scope: every report of a defect found by this suite or by podiumd-minikube, in any product,
  chart or estate configuration.
- Not verifiable: a report about an estate without an environment for the tester (e.g. ExternalsPodiumD
  without access). It keeps its last status, marked "not re-checked".

## Code under test

Two variants, each deployed on a fresh install:

1. **Base**: helm-charts `feature/podiumd-X.Y.Z` at a fixed commit.
2. **Base + open fixes**: the base with every open pull request into that branch that changes what gets
   deployed (`charts/podiumd/values.yaml`, `Chart.yaml`, `templates/`, `files/`), merged in a
   fixed order. Pull requests that change only documentation or tooling are left out. Conflicts in
   `charts/podiumd/README.md` and `charts/podiumd/docs/` keep the base side: they do not change the
   deployment. A conflict anywhere else stops the round.

A report that fails on the base and passes on base + open fixes is "fixed by PR" with its number.

The merge for variant 2, with the head commits of the round's branches in their order (branches move,
commits do not):

```bash
git clone https://github.com/Dimpact-Samenwerking/helm-charts.git && cd helm-charts
git checkout -B verify <base commit>
for h in <head commit> ...; do
    git merge --no-edit "$h" || {
        u=$(git diff --name-only --diff-filter=U)
        if grep -qvE '^charts/podiumd/(README\.md|docs/)' <<<"$u"; then echo "conflict in $h"; exit 1; fi
        for f in $u; do git checkout --ours -- "$f" 2>/dev/null && git add "$f" || git rm -q "$f"; done
        git commit --no-edit
    }
done
git rev-parse HEAD:charts/podiumd   # must equal the chart tree recorded for the round
```

Commit hashes differ per merge (author and date); the tree hash of `charts/podiumd` does not, so the
round records that, plus the merge commit pushed for the installs.

## Environments

| Report type | Environment | Why |
| --- | --- | --- |
| Product defect | minikube and an AKS estate (podiumd-infra) | reproduced on both: not caused by one estate |
| Needs an outage (SMTP, PABC) | minikube | the `chaos` tier runs only there |
| Fresh-install chart defect | minikube | reinstalled in minutes |
| Estate defect (edge headers, PodDisruptionBudgets, node scale-down) | AKS estate | minikube has no edge gateway and one node |

Each environment is destroyed and installed fresh before a round, by the owner of its deploy
(podiumd-minikube, podiumd-infra). The round records per environment: profile, chart tree, image
versions (`run.json`), podiumd-tests commit and the bootstrap steps run.

## Procedure

Per environment and variant:

```bash
podiumd-tests doctor --env <env>
podiumd-tests bootstrap --env <env>
podiumd-tests run --env <env> --tier full
podiumd-tests run --env <env> --tier chaos                          # minikube only
podiumd-tests run --env <env> --tier full -- --runxfail <node ids>  # every known-defect test
```

- `summary.md` of a run lists the known defects that failed ("Known defects (XFailed)") and those that
  passed ("Known defects that did not show (XPassed)"); `junit.xml` has the failure messages.
- `--runxfail` runs known-defect tests as plain tests, so the failure message shows whether the test
  fails with the reported symptom and not for an unrelated reason.
- A report without a test is checked with the command in its text (`curl`, `kubectl`, `helm template`).
- A report's "Found by" names the test, its source and the source's reason for the test: the test's
  `@pytest.mark.source(origin, reason)`, listed per test in `summary.md` ("Sources of the failed and
  known-defect tests"). Creating or updating a report copies them.
- Upstream: the issue tracker and the newest release of the product decide "fixed upstream" with the version.

## Outcome per report

| Outcome | Rule |
| --- | --- |
| reproduced | fails with the reported symptom on the base, after a clean bootstrap |
| fixed by PR | reproduced on the base, passes on base + open fixes |
| fixed upstream | not in the pinned version, fixed in a newer upstream release |
| not reproduced | passes on the base in two runs; the report is proposed for removal |
| not re-checked | no environment, or a precondition that the round cannot create (e.g. a 12 h cache) |

## Severity

| Level | Rule |
| --- | --- |
| Critical | silent loss of mail or data, an outage of a user-facing component, or an exploitable security hole |
| High | a user or integration flow fails: error 500, wrong or lost data, authorization bypass |
| Medium | missing hardening (security headers), resource requests or PodDisruptionBudgets, configuration gaps with a workaround |
| Low | question, feature request, cosmetic |

Between two reports of one level: reproduced on every estate ranks above one estate only, and a
production flow ranks above a test-only path.
