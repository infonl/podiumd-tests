# podiumd-tests

Smoke, component, integration and perf tests for PodiumD environments: minikube,
the ICATT podiumd-infra AKS environments and the SSC Twente ExternalsPodiumD
environments. One Python/pytest suite, run from the console against an
environment profile. See [PLAN.md](PLAN.md) for the design and the phases.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/playwright install chromium   # only for UI tests
```

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

Tiers: `smoke`, `core`, `full`, `perf`, `chaos`. A profile's `allowed_tiers`
limits which tiers may run against that environment.

Exit codes: 0 pass, 1 test failures, 2 configuration or preflight error,
3 tier not allowed for the environment, 4 environment locked by another run.

In a pipeline: `--env`, `--tier`, `--results-dir` and `--envs-dir` can also be
set as `PODIUMD_TESTS_ENV`, `PODIUMD_TESTS_TIER`, ...; secrets as
`PODIUMD_TESTS_SECRET_<NAME>`. On GitHub Actions and Azure DevOps a run folds
its log into sections and publishes `summary.md` on the job page.

## Environment profiles

`envs/**/<name>.yaml` holds everything non-secret about an environment: kube
context and namespace, the base URL per component, where each secret comes
from, and the allowed tiers. Secrets are never stored here. They resolve in
this order:

1. environment variable `PODIUMD_TESTS_SECRET_<NAME>`;
2. the source in the profile: `k8s_secret`, `pod_env`, `zgw_jwt_secret`
   (from Open Zaak's database) or `keyvault`;
3. `dev_default`, for minikube only.

## Development

```bash
./run_python_checks   # ruff, shellcheck, jscpd, pymarkdown, vulture, bandit, pylint, basedpyright, pytest
```

A bare `pytest` runs only the offline unit tests in `unit_tests/`. The
environment tests in `tests/` run through `podiumd-tests run`.
