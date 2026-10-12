<!-- pyml disable-next-line first-line-heading -->
> **Frozen since YYYY-MM-DD: this suite is no longer maintained.** Its tests now live in
> [infonl/podiumd-tests](https://github.com/infonl/podiumd-tests), a pytest suite that runs
> against every PodiumD estate (podiumd-infra, ExternalsPodiumD, minikube) with one command:
> `podiumd-tests run --env <environment> --tier smoke|core|full|perf|chaos`.
>
> - Where each spec went (ported, merged or dropped, with the reason):
>   [MIGRATION.md](https://github.com/infonl/podiumd-tests/blob/main/MIGRATION.md), section TA.
> - Which draaiboek case (Testscript PodiumD 4.6, `test-catalog/`) is covered by which test:
>   [docs/draaiboek-coverage.md](https://github.com/infonl/podiumd-tests/blob/main/docs/draaiboek-coverage.md).
>   Every case this suite covered is covered there.
> - `seed-test-data/` is replaced by `podiumd-tests seed-volume` / `unseed-volume`; the
>   environment wiring of `test-seeding/` by `podiumd-tests bootstrap`.
> - Not ported yet: the OMC specs (80, 81, 82, 115, 116, part of 154), blocked on OMC 1.17.19
>   refusing every notification; eSuite (155, 156), which no estate exposes; and
>   `perf/fg-compare.js`, which needs a direct route to Open Zaak besides the Frank!Gateway.
>
> Add new tests to podiumd-tests, not here. Questions: open an issue there.
