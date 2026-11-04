# Open requests for podiumd-minikube

## Size minikube's CPUs from the host (Kees, 2026-10-28)

`src/podiumd_minikube/provision.py` starts minikube with `MINIKUBE_CPUS`, default 6, on any host. Kees wants the
default to depend on the host: at most 8 CPUs, and on a smaller laptop not all of them, so other applications keep
some capacity.

Suggested default (`MINIKUBE_CPUS` still overrides): `min(8, host_cpus - max(2, host_cpus // 4))`, at least 2.

| Host CPUs | minikube CPUs |
| --- | --- |
| 24 | 8 |
| 12 | 8 |
| 8 | 6 |
| 6 | 4 |
| 4 | 2 |

Why it matters for the tests: the node's 6 CPUs limit the full tier, not the laptop's 24 cores. On 2026-10-28
(podiumd 4.10.0, one pod per component) the full tier took 634-648 s with 4 pytest workers and 573 s with 6. With 6
workers the minikube container ran at about 434% of its 600% limit, and 4 more tests failed through contention
(Open Inwoner search, Open Zaak autorisaties).

## Grafana's Keycloak login, as ExternalsPodiumD (2026-11-04)

`values.yaml:3234` sets `grafana.ini.auth.generic_oauth.enabled: false` (anonymous admin as a dev tool).
ExternalsPodiumD (dim1, mayk, info `monitoring.yml`) turns it on against realm podiumd, client `monitoring`, which the
podiumd chart's realm config creates. Without it, monitoring-logging 1.0.19's relink of a recreated Keycloak user
(#697, IN-3352, `oauth_allow_insecure_email_lookup`) cannot be tested on minikube:
`test_recreated_keycloak_user_logs_in_to_the_same_grafana_user` skips.

Request: enable `auth.generic_oauth` with the realm's URLs and the `monitoring` client secret, as ExternalsPodiumD.
Anonymous access may stay on beside it.

Verify: `/api/frontend/settings` lists `oauth.generic_oauth`; then
`podiumd-tests run --env minikube --tier full -- -k test_recreated_keycloak_user`.
