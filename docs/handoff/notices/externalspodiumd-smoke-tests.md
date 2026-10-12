# Smoke tests: frozen

**Frozen since YYYY-MM-DD: these smoke tests are no longer maintained.** They are part of
[infonl/podiumd-tests](https://github.com/infonl/podiumd-tests), as its `smoke` tier, which
runs against every PodiumD estate.

- Where each spec went: [MIGRATION.md](https://github.com/infonl/podiumd-tests/blob/main/MIGRATION.md),
  section EX (all 14 merged).
- Profiles for ExternalsPodiumD environments live in
  [envs/externals/](https://github.com/infonl/podiumd-tests/tree/main/envs/externals); new ones
  start as smoke-only (`allowed_tiers: [smoke]`), which the suite enforces.
- Running without a pipeline: build the container image from podiumd-tests' `Dockerfile` and run
  it from a machine that has access to the cluster:

  ```bash
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v ~/.kube/config:/tmp/kubeconfig:ro -e KUBECONFIG=/tmp/kubeconfig -v ~/.azure:/tmp/.azure \
    -v "$PWD/results:/opt/podiumd-tests/results" podiumd-tests run --env <environment> --tier smoke
  ```

Add new tests to podiumd-tests, not here.
