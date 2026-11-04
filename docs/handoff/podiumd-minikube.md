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

## uWSGI threads as ExternalsPodiumD for Objecten, Open Notificaties, Open Formulieren and Open Archiefbeheer (Kees, 2026-11-04)

minikube runs these four with 2 uWSGI threads: `settings.uwsgi.threads: 2` for objecten, opennotificaties and
openformulieren, and `UWSGI_THREADS=2` in openarchiefbeheer's `extraEnvVars` (values.yaml). ExternalsPodiumD and
kees00 set no uWSGI values and the podiumd chart sets none for these four, so they run the threads of each image's
`/start.sh`.

Request: remove the `threads: 2` settings and the `UWSGI_THREADS` variable, so these four run their image's threads
as ExternalsPodiumD. `processes: 1` stays (laptop budget), as for Open Inwoner in 08c66cc.

Why it matters for the tests: a race or deadlock between request threads shows only with the estates' thread count;
Open Inwoner's hang on kees00 (2026-11-04) did not show on minikube while it ran 2 threads.
