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

## Open Inwoner: uWSGI threads and max-requests as ExternalsPodiumD (Kees, 2026-11-04)

minikube's Open Inwoner runs `settings.uwsgi.threads: 2` and `UWSGI_MAX_REQUESTS=1000` (values.yaml, openinwoner
block). ExternalsPodiumD and kees00 set neither, so they run the image defaults from `/start.sh`: 8 threads per
process and a worker recycle every 100 requests (podiumd-infra checked dimp/test, dim1/ontw and icat/ontw on
2026-11-04). Kees asks to keep minikube's configuration close to ExternalsPodiumD.

Request: remove `threads: 2` and the `UWSGI_MAX_REQUESTS` variable for Open Inwoner, so it runs the image defaults.
`processes: 1` stays (laptop budget).

Why it matters for the tests: on kees00 (Open Inwoner 2.4.9, 2026-11-04) Open Inwoner requests hung inside the
process until uWSGI killed the worker ("NO MERCY" 17:16:22, 17:56:45, 17:57:05 CET): a livez with no test running,
a DigiD callback and a Mijn zaken content request, which failed two tests. Open Zaak, Redis and Postgres answered
normally. The leading hypothesis is a thread deadlock under 8 threads; minikube's 2 threads and rare recycles hide
it. podiumd-tests takes a py-spy stack of a stuck worker on the fresh kees00 (Open Inwoner 2.5.0) on 2026-11-05; with
the image defaults, minikube can show the same hang.
