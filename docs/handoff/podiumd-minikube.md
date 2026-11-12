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

## BAG mock self links that Open Zaak accepts (podiumd-tests, 2026-11-12)

Since 192fed9 the bag-mock links to `http://bag-mock:8080/lvbag/individuelebevragingen/v2/adressen/...`. Open Zaak
now refuses that zaakobject URL with 400 "Voer een geldige URL in." (`msg.error.validation.zgw`): Django's
URLValidator accepts no single-label host other than localhost.

Request: self links on a host name with a dot, e.g. `http://bag-mock.<namespace>.svc.cluster.local:8080/...` (or the
outway's `http://frankgateway-outway.podiumd.svc.cluster.local:9080/...`, as on kees00 since podiumd-infra #233).

Tests: `tests/component/zac/test_zac_bag.py::test_new_zaak_links_the_chosen_bag_adres` and
`::test_bag_adres_is_linked_once_and_unlinked` (run 20261112-174626_minikube_full_2611121746322b; both pass on
kees00).
