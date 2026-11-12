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

## BAG mock self links that Open Zaak can fetch (podiumd-tests, 2026-11-12)

The BAG mock (`vendor/dimpact-zaakafhandelcomponent/bag/*.json`, served by `bag-mock`) answers with self links on
`http://bag-wiremock.local:8080/...`, copied from ZAC's docker-compose setup. Open Zaak fetches that URL to validate a
zaakobject and cannot resolve the host, so ZAC answers 400 to a new zaak with `bagObjecten`: "De URL
`http://bag-wiremock.local:8080/...` kon niet opgehaald worden".

Request: serve the self links on a URL Open Zaak can reach, e.g. the `bag-mock` Service.

Test: `tests/component/zac/test_zac_bag.py::test_new_zaak_links_the_chosen_bag_adres` fails on minikube until then
(run 20261112-141919_minikube_full_26111214197e4a: 104 passed, this one failed).
