# podiumd-tests

Smoke, component, integration and perf tests for PodiumD environments: minikube,
the ICATT podiumd-infra AKS environments and the SSC Twente ExternalsPodiumD
environments. One Python/pytest suite, run from the console against an
environment profile.

More documentation:

- [results/README.md](results/README.md): where runs are stored, what each outcome means, how to view a run.
- [MIGRATION.md](MIGRATION.md): where each test of the older suites went.
- [docs/draaiboek-coverage.md](docs/draaiboek-coverage.md): which draaiboek case which test covers.
- [docs/handoff/notices/README.md](docs/handoff/notices/README.md): freeze notices for the older suites' owners.
- `docs/handoff/`: open requests to other repositories; `docs/research/`: background research.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/playwright install chromium   # only for UI tests
```

`pip install -e` is an editable install, so there is no build step. `.venv`
points at `src/` (a `.pth` file in `site-packages`), so a change in `src/`
takes effect at once. The `podiumd-tests` command is generated from
`[project.scripts]` in `pyproject.toml`. Rerun the install after changing
`pyproject.toml`; `./run_python_checks` does this itself, and also upgrades
the dev tools once a day to match CI.

You also need `kubectl` with a context for the environment, and `az` when the
profile reads secrets from Azure Key Vault.

Or use the container image, which has all of it (`kubectl`, `kubelogin`, `az`,
Chromium); see the `Dockerfile` for how to run it with your kubeconfig:

```bash
docker build -t podiumd-tests .
```

## Use

```bash
podiumd-tests env list                       # known environment profiles
podiumd-tests env show kees00
podiumd-tests doctor --env kees00            # preflight: can a run work right now?
podiumd-tests run --env kees00 --tier smoke  # results in results/<YYYY-MM>/<run>/
podiumd-tests env init ontw-icat --estate externals --context aks-blue-ontw-icat
```

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

## Bootstrap

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
namespace. `podiumd-tests unbootstrap --env <name>` removes the test objects and
restores the wiring.

What each outcome means and how to view a run: [results/README.md](results/README.md).

Exit codes: 0 pass, 1 test failures, 2 configuration or preflight error,
3 tier not allowed for the environment, 4 environment locked by another run.

In a pipeline: `--env`, `--tier`, `--results-dir` and `--envs-dir` can also be
set as `PODIUMD_TESTS_ENV`, `PODIUMD_TESTS_TIER`, ...; secrets as
`PODIUMD_TESTS_SECRET_<NAME>`. On GitHub Actions and Azure DevOps a run folds
its log into sections and publishes `summary.md` on the job page.

From another repository's GitHub Actions (e.g. podiumd-infra), call the reusable
workflow `.github/workflows/run.yml`; its header shows how. Without pipeline
rights (SCC Twente), run the container image from a machine that has access.

## Environment profiles

`envs/**/<name>.yaml` holds everything non-secret about an environment: kube
context and namespace, the base URL per component, where each secret comes
from, and the allowed tiers. Secrets are never stored here. They resolve in
this order:

1. environment variable `PODIUMD_TESTS_SECRET_<NAME>`;
2. the source in the profile: `k8s_secret` (optional `namespace`, default the profile's), `pod_env`, `zgw_jwt_secret`
   (from Open Zaak's database) or `keyvault`;
3. `dev_default`, for minikube only.

## PodiumD versions

The suite runs against any PodiumD release; there is no list of supported
versions and no test branches on a version number. Tests depend on what an
environment has (`@pytest.mark.requires`, detection of each component's
layout), so a missing component skips its tests and an unknown layout fails a
test. A known product bug is a strict xfail: a release that fixes it fails the
test, and the xfail is removed. Only when the fix's component version is known
does the xfail apply below that version (`expect_ita_group_access_bug`). Each run
records the chart version and image tags read from the cluster.

## Development

```bash
./run_python_checks   # ruff, shellcheck, jscpd, pymarkdown, vulture, bandit, pylint, basedpyright, pytest
```

A bare `pytest` runs only the offline unit tests in `unit_tests/`. The
environment tests in `tests/` run through `podiumd-tests run`.
