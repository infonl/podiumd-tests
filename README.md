# podiumd-tests

## Introduction

podiumd-tests checks whether a PodiumD environment works: are the components
up, are they wired to each other, and do the user flows across them work
(a zaak, a form submission, a contactverzoek from KISS to ITA, notifications,
logins through Keycloak). It is one Python/pytest suite that runs from your
console, or from a pipeline, against one environment at a time:

- minikube (podiumd-minikube);
- the ICATT podiumd-infra AKS environments (e.g. kees00);
- the SSC Twente ExternalsPodiumD environments (ontw-*, test-*).

The suite runs against any PodiumD release; see [PodiumD versions](#podiumd-versions).

## Prerequisites and setup

You need:

- Python 3.12 or newer;
- `kubectl` with a context for the environment;
- `az`, logged in, when the profile reads secrets from Azure Key Vault;
- network access to the environment's URLs (for ExternalsPodiumD: the VPN, and
  `KUBECONFIG` including the cluster's kubeconfig).

Install:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/playwright install chromium   # only for UI tests
```

`pip install -e` is an editable install: a change in `src/` takes effect at
once. Rerun it after changing `pyproject.toml`; `./run_python_checks` does
this itself.

Or use the container image, which has all of it (`kubectl`, `kubelogin`, `az`,
Chromium); the `Dockerfile` shows how to run it with your kubeconfig:

```bash
docker build -t podiumd-tests .
```

## Quick start

```bash
podiumd-tests env list                        # known environments
podiumd-tests doctor --env kees00             # can a run work right now?
podiumd-tests bootstrap --env kees00          # once per install
podiumd-tests run --env kees00 --tier smoke   # results in results/<YYYY-MM>/<run>/
```

## Workflow

1. **Profile.** An environment needs a profile in `envs/`. For a new one,
   `podiumd-tests env init <name> --estate <estate> --context <kube context>`
   drafts it from the cluster's ingresses and HTTPRoutes; review the URLs and
   secret sources (see [Environment profiles](#environment-profiles)).
2. **Doctor.** `podiumd-tests doctor --env <name>` checks read-only that the
   cluster, every URL and every secret are reachable. `run` and `bootstrap` run
   it first themselves (`--skip-doctor` skips it).
3. **Bootstrap.** After an install or reinstall, run
   `podiumd-tests bootstrap --env <name>` once. It adds test users, API
   clients, a test catalogus and test forms to the environment, and on
   minikube and podiumd-infra also wires test logins (DigiD and eHerkenning
   through a mock) into the platform's configuration. All of it stays until
   `unbootstrap` (see [Bootstrap and cleanup](#bootstrap-and-cleanup)).
4. **Run.** `podiumd-tests run --env <name> --tier <tier>`; start with `smoke`,
   then `core` or `full` (see [Tiers](#tiers)). Extra pytest arguments go after
   `--`, e.g. one file:
   `podiumd-tests run --env kees00 --tier full -- tests/integration/test_sso.py`.
5. **Read the results.** Each run writes `summary.md`, `report.html`,
   `junit.xml` and `run.json` to `results/<YYYY-MM>/<timestamp>_<env>_<tier>_<runid>/`.
   What each outcome means: [results/README.md](results/README.md).
6. **Clean up.** A run deletes the data it created. After a crashed run,
   `podiumd-tests sweep --env <name>` deletes what it left behind. When an
   environment no longer needs testing, `podiumd-tests unbootstrap --env <name>`.

Exit codes: 0 pass, 1 test failures, 2 configuration or preflight error,
3 tier not allowed for the environment, 4 environment locked by another run.

## Tiers

A profile's `allowed_tiers` limits which tiers may run against that
environment. `core`, `full` and `chaos` run on 4 pytest-xdist workers; profile
setting `pytest_workers` changes that (1 runs serially).

| Tier | Runs | Changes the environment |
|---|---|---|
| `smoke` | `tests/smoke`: every component answers, logins redirect to Keycloak, components reach each other, secrets resolve. About a minute. | no |
| `core` | smoke plus the tests marked `core`: the key user flows (create a zaak, submit a form, a contactverzoek from KISS to ITA, notifications). | yes: creates test data tagged with the run and deletes it at the end |
| `full` | smoke, `tests/component` (one component's behaviour) and `tests/integration` (chains across components), except destructive tests. | yes: as `core` |
| `perf` | `tests/perf`: Locust load with the response-time thresholds of `perf.yaml`. | read-mostly; load on the environment |
| `chaos` | only tests marked `destructive`: a component or SMTP stopped and recovery, changes to global settings (Open Archiefbeheer). Opt-in. | yes: disrupts other users meanwhile |

## Bootstrap and cleanup

`podiumd-tests bootstrap --env <name>` creates what the tests need and a PodiumD
install lacks. Run it once after an install or reinstall, before `core`;
`smoke` needs it only for the DigiD and eHerkenning login checks. A test whose
bootstrap step is missing skips and names the step. Each step is idempotent,
so rerunning it is safe; `--step` runs one step, `--rotate` renews the
credentials.

- **Test objects** (always): API clients and tokens (Open Zaak, Open
  Notificaties, Open Klant, Objecten, Objecttypen), a test catalogus and
  zaaktype, Open Formulieren test forms, test users in Keycloak, Open
  Archiefbeheer, Open Formulieren and Open Inwoner, and the mock server in
  `infra/` (webhooks, NotifyNL, Worldline). All named `ptest-bootstrap-*`.
- **Wiring** (only with `bootstrap.wiring: true` in the profile: minikube and
  podiumd-infra): changes to the platform's own configuration, such as
  DigiD and eHerkenning through Keycloak's mock in Open Inwoner and Open
  Formulieren, Open Inwoner's CMS pages and connections, Open Notificaties and
  KISS kanalen. Each step stores the old state first.

Credentials go to the Secret `podiumd-tests-credentials` in the environment's
namespace.

Cleanup has two layers:

- **Bootstrap data stays** between runs, so runs reuse the users and clients.
  `podiumd-tests unbootstrap --env <name>` removes the test objects and the
  Secret, and restores the wiring.
- **Data a test creates** (zaken, partijen, submissions, ...) is deleted by
  that test at its end, pass or fail. Its name carries the run's tag, so
  `podiumd-tests sweep --env <name>` finds what a crashed run left behind.
  Sweep never touches `ptest-bootstrap-*` objects.

## Environment profiles

`envs/**/<name>.yaml` holds everything non-secret about an environment: kube
context and namespace, the base URL per component, where each secret comes
from, and the allowed tiers. Secrets are never stored here. They resolve in
this order:

1. environment variable `PODIUMD_TESTS_SECRET_<NAME>`;
2. the source in the profile: `k8s_secret` (optional `namespace`, default the profile's), `pod_env`, `zgw_jwt_secret`
   (from Open Zaak's database) or `keyvault`;
3. `dev_default`, for minikube only.

`podiumd-tests env show <name>` prints a profile.

## PodiumD versions

There is no list of supported versions and no test branches on a version
number. Tests depend on what an environment has (`@pytest.mark.requires`,
detection of each component's layout), so a missing component skips its tests
and an unknown layout fails a test. A known product bug is a strict xfail: a
release that fixes it fails the test, and the xfail is removed. Only when the
fix's component version is known does the xfail apply below that version
(`expect_ita_group_access_bug`). Each run records the chart version and image
tags read from the cluster.

## Pipelines

`--env`, `--tier`, `--results-dir` and `--envs-dir` can also be set as
`PODIUMD_TESTS_ENV`, `PODIUMD_TESTS_TIER`, ...; secrets as
`PODIUMD_TESTS_SECRET_<NAME>`. On GitHub Actions and Azure DevOps a run folds
its log into sections and publishes `summary.md` on the job page.

From another repository's GitHub Actions (e.g. podiumd-infra), call the reusable
workflow `.github/workflows/run.yml`; its header shows how. Without pipeline
rights (SCC Twente), run the container image from a machine that has access.

## Development

```bash
./run_python_checks   # ruff, shellcheck, jscpd, pymarkdown, vulture, bandit, pylint, basedpyright, pytest
```

A bare `pytest` runs only the offline unit tests in `unit_tests/`. The
environment tests in `tests/` run through `podiumd-tests run`.

Layout: `src/podiumd_tests/` holds the logic (clients, bootstrap, seeding,
CLI), `tests/` the environment tests per tier, `envs/` the profiles, `infra/`
the mock server's manifests.

## Further documentation

- [results/README.md](results/README.md): where runs are stored, what each outcome means, how to view a run.
- [MIGRATION.md](MIGRATION.md): where each test of the older suites went.
- [docs/draaiboek-coverage.md](docs/draaiboek-coverage.md): which draaiboek case which test covers.
- [docs/handoff/notices/README.md](docs/handoff/notices/README.md): freeze notices for the older suites' owners.
- `docs/handoff/`: open requests to other repositories; `docs/research/`: background research.
