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

## WAF runs out of memory on a large upload (podiumd-tests, 2026-11-12)

A POST of a 500 MB + 1 byte document to `zac.local` (ZAC's upload limit is 500 MB) made pod
`ingress-basic/waf-6df6444d47-g94wm` exit 137 (OOMKilled, memory limit 512Mi) at 15:01:46 UTC; its log shows "a client
request body is buffered to a temporary file" for that POST. Until it restarted, every request through the edge got
"Connection refused" on 10.96.0.200:443.

Cause: the ModSecurity-nginx connector passes a body nginx buffered to a temp file to libmodsecurity 3.0.17
(`msc_request_body_from_file`), whose `Transaction::requestBodyFromFile` reads the whole file into memory before
`SecRequestBodyLimit`/`ProcessPartial` cut it. `SecRequestBodyInMemoryLimit` does not exist in ModSecurity v3.
`src/podiumd_minikube/waf.py`: memory limit 512Mi (`:101`), `client_max_body_size 0` (`:150`), 2 nginx workers
(`:242`). podiumd-infra's WAF (kees00) has the same; podiumd-infra was told (2026-11-12).

Request: follow podiumd-infra #234 in your port: WAF limits.memory 512Mi → 1536Mi (2 workers × 500 MB plus baseline),
with a comment on libmodsecurity's requestBodyFromFile; inspection stays on for the upload paths.

Test: `tests/component/zac/test_zac_documenten.py::test_document_above_the_maximum_file_size_is_refused` (destructive,
slow) fails on minikube until then.

## Shared lock file: flock the hold, refuse to break a live one (podiumd-tests, 2026-11-12)

podiumd-tests db3e058 changed how it holds `/home/kvv/development/werk/infonl-dimpact/infonl/.minikube-lock`; the
line format is unchanged:

- Its holder keeps an exclusive `fcntl.flock` on the lock file for the whole hold, so "is the holder still running"
  is "can a non-blocking flock be taken", also for a holder in another PID namespace (a sandbox or container) where
  a pid check sees nothing.
- It takes over a stale podiumd-tests line only under a flock on `.minikube-lock.guard`, so two takers cannot both
  win. It never treats a podiumd-minikube line as stale.

Requests for `src/podiumd_minikube/lock.py`, so both sides behave the same:

1. `take`: after the `O_EXCL` create, keep the descriptor open with `fcntl.flock(fd, LOCK_EX | LOCK_NB)` until
   `release` (also for `cluster-lock run`). Then podiumd-tests, and your own `cluster-lock status`, can tell a live
   holder from a leftover line.
2. `break_lock`: refuse while the file is flock-ed (a live holder, of either repository), unless forced, e.g.
   `cluster-lock break --force`; today it removes any hold, including a running podiumd-tests run's.
3. `break_lock` and `release_held_by`: read, compare and unlink under a flock on `.minikube-lock.guard`, so a break
   cannot remove a hold someone took just after it was read.

Check: `fcntl.flock(open(".minikube-lock"), LOCK_SH | LOCK_NB)` raises `BlockingIOError` while either side holds the
lock.
