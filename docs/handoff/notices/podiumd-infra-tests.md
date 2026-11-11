<!-- pyml disable-next-line first-line-heading -->
> **Frozen since 2026-10-20: these tests are no longer maintained.** They moved to
> [infonl/podiumd-tests](https://github.com/infonl/podiumd-tests), which runs the same checks,
> and more, against every PodiumD estate.
>
> - Where each test went: [MIGRATION.md](https://github.com/infonl/podiumd-tests/blob/main/MIGRATION.md),
>   section PI. 13 of the 15 are ported or merged; dropped are `test_4_8_5_upgrade.py` (one
>   environment's pinned images) and `test_pabc_migrations_guard.py` (a podiumd-minikube script).
> - podiumd-infra environments have profiles in
>   [envs/podiumd-infra/](https://github.com/infonl/podiumd-tests/tree/main/envs/podiumd-infra);
>   add one with `podiumd-tests env init <name> --estate podiumd-infra --context <kube context>`.
> - From GitHub Actions, call the reusable workflow
>   [`.github/workflows/run.yml`](https://github.com/infonl/podiumd-tests/blob/main/.github/workflows/run.yml)
>   with the environment, the tier and this repository's Azure OIDC identity; its header shows the
>   calling job. A private AKS API needs a self-hosted runner (`runs-on`).
> - `scripts/seed-test-data/lib/seed_zac_zaakafhandelparameters.py` stays here: it is environment
>   setup. podiumd-tests checks its result (`test_zaakafhandelparameters_are_valide`).
>
> Add new tests to podiumd-tests, not here.
