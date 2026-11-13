# Load, stress, soak and availability sources for podiumd-tests

Researched 2026-11-13/14, read-only. Goal: sources the perf tier could port or reuse to show how PodiumD's components
behave under load and whether they stay available (no crashes, restarts, OOM kills, 5xx storms; recovery after load).

**Already in the suite, not repeated below:** `tests/perf/test_api_perf.py` with `src/podiumd_tests/perf/locustfile.py`
(TA `api-perf.js` reads, Open Zaak `performance_test/` deep-page EIO list and one-zaaktype client, Baseflow dmf document
mix, Open Notificaties `POST /notificaties`, writes for Open Klant and Objecten, ZAC/KISS/portal searches; constant
users, 1 s wait, p95 and failure-ratio thresholds plus slowdown against earlier runs), `tests/perf/test_gateway_perf.py`
(anonymous gateway scenarios), the chaos tier `tests/integration/test_continuiteit.py` (component scaled to 0 without
load), and the run-wide `workloads.cluster_state` / `workloads.disruptions` report of pods restarted during a run
(`cli.py:448`, shown in `summary.md`, not asserted in perf). TA `fg-compare.js` stays todo (MIGRATION.md).

URLs: every GitHub URL below was fetched (HTTP 200 and/or read through the GitHub API); the other URLs were fetched
with curl or WebFetch. "verify" marks a fact not confirmed.

## Top 5

1. **Open Zaak "Notifications performance" (docs) + Objecten #534 notification storm: Open Notificaties down during
   write load.** Measured burst load (10/20/40 users `POST /zaken`: ~24 req/s, 0 failures, median notification delay
   85 ms) and downtime runs (Open Notificaties down 10/60/300/600 s: default autoretry delivers everything up to 60 s, loses
   1,276 of ~1,500 at 300 s). #534 describes the field failure: a misconfigured notification target (403) drove 10k
   calls/min and 100 % database use, degrading every component. The suite has no test where a dependency fails while
   load runs. Port: a chaos+perf test that runs `oz_zaak_create` load, scales Open Notificaties to 0 for 60 s, restores
   it, and asserts Open Zaak kept answering 201 (no 5xx storm, no restarts) and the mock-server abonnement on
   `ptest-bootstrap-perf` received every notificatie afterwards. The numbers are thresholds.
2. **Open Zaak #2577 (Den Haag): a "hot" zaak with many documents and concurrent writes.** Before 1.31.1, each new
   zaakinformatieobject recalculated the ETags of every row of the zaak, twice: 46 queries for the first document,
   1,500+ at 500 documents, so a migration scaled quadratically, and concurrent writes deadlocked (500). The 1.31.1
   changelog says "Adding documents to a zaak no longer gets slower the more documents it has", and a deadlock now
   answers `503` with `Retry-After: 1` instead of `500`. The suite's `oz_zio_create` uses a new zaak each time.
   Port: a perf call that adds documents to one shared zaak (time of the n-th ZIO vs the first) and concurrent ZIO
   creates on that zaak. Assert no 500, only 201 or 503+Retry-After, and a flat p95 from 1.31.1 on. An xfail below
   1.31.1 needs the known-issue route (open-zaak-11 is the ETag-correctness part).
3. **Memory growth under repeated load (soak): Open Klant #636, Open Zaak #1837, Open Klant #323.** Open Klant 2.17.1
   grew from 291 MiB to over 1.1 GiB after 22 list calls with `expand` (fixed in 2.18.0). Open Zaak 1.15 kept the memory
   of `expand` pages (fixed in 1.21.0). In #323, Open Klant v2 answered in 30 s+ and timed out after months of uptime
   until a restart. The fleet-wide mitigation is uWSGI `max-requests` (open-api-framework #211; the helm-charts Open
   Zaak pooling doc sets `maxRequests: 1000`). The suite measures latency only. Port: a soak run (`--perf-duration`
   30–60 min) that samples `container_memory_working_set_bytes` per pod through the Grafana proxy (or `kubectl top`)
   and asserts that memory stays below the limit and levels off, with no OOMKilled or restart (`workloads.disruptions`).
   Include list calls with `expand` for Open Zaak (`zaken?expand=…`) and Open Klant (`klantcontacten?expand=…`).
4. **Keycloak benchmark (Gatling) + Keycloak sizing guide + `kc-chaos.sh`.** Keycloak is the shared login of every
   PodiumD app, and the suite times only the discovery document. The sizing guide gives reference numbers: 15 password
   logins/s, 120 client-credential grants/s and 120 refresh-token requests/s per vCPU; 1,250 MB per pod as the base;
   150 % CPU headroom; throttled pods degrade sharply. `kc-chaos.sh` deletes a random Keycloak pod every N s under load
   and records the recovery time, restarts and `kubectl top`. Port: Locust calls `kc_password_grant` (`password_grant`)
   and `kc_client_credentials`, with thresholds derived from the pod's CPU limit, plus a chaos-tier "delete the Keycloak
   pod under login load" test. Outside the suite, the scenarios `authentication.AuthorizationCode` and
   `ClientSecret` can run as an external tool against a dev realm.
5. **Open Formulieren #2198 (Den Haag load test): worker and Redis exhaustion, recovery after a restart.** Under load,
   Redis ran out of resources and Celery stopped. After a restart, queued registrations stayed "pending" and were never
   retried. The suite's `test_continuiteit.py` stops components without load and does not check queued work. Port:
   submit N forms (`start_submission`/`submit`) while the Open Formulieren worker is restarted. Assert that every
   submission ends as a zaak (`registered_zaak`), with no lost or stuck registration and no restart of the other pods.
   Use the same pattern for Open Zaak→Open Notificaties and the ZAC→Solr reindex.

## Ranked findings

### High

#### H1. Open Zaak: notifications performance and autoretry under downtime

| | |
| --- | --- |
| URL | <https://open-zaak.readthedocs.io/en/latest/development/performance/notifications.html>, source <https://github.com/open-zaak/open-zaak/blob/main/docs/development/performance/notifications.rst> |
| Licence | EUPL-1.2 (Open Zaak; GitHub reports NOASSERTION, verify) |
| Component | Open Zaak, Open Notificaties (Celery worker) |
| Kind / tool | benchmark results + scenario description; Locust (implied by "users"; verify) |
| Size / activity | one doc page; performance docs dir last changed 2026-10-13 |
| Reference numbers | burst: 10/20/40 users → 1,430/1,479/1,429 requests per minute, ~24 req/s, 0 failures, median 390/740/1,200 ms, median notification 84–89 ms. Downtime (10 users, 1 min, default retry): 10 s and 60 s → 0 lost; 300 s → 1,276 lost. With max retries 7 and backoff max 192: 300 s → 0 lost, 600 s → 1,181 lost |
| Port value | the missing "dependency down under load" case; the notification-delay median as a threshold for the time from a zaak create to its notificatie at the mock server; the retry schedule (3, 9, 21, 45, 93 s) as the window for "delivered after recovery" |
| How | port to the suite's Locust (`oz_zaak_create` load) plus a chaos-tier wrapper that scales Open Notificaties to 0 (existing `test_continuiteit.py` scaling helpers) and counts deliveries on the `ptest-bootstrap-perf` kanaal's mock-server abonnement. Only on environments whose `allowed_tiers` include chaos |

#### H2. Objecten #534: back pressure and circuit breaker (notification storm)

| | |
| --- | --- |
| URL | <https://github.com/maykinmedia/open-object/issues/534> (repo renamed from objects-api) |
| Component | Open Zaak, Objecten, Open Notificaties |
| Kind | field incident description (no script) |
| Activity | closed 2026-02-18; outcome: a health endpoint exposing the task-queue length was proposed |
| Port value | names the failure to provoke: a notification target that refuses (403), producing 10k calls/min and 100 % database use, after which every component degrades. Combined with H1, test both the "down" and the "refuses" variants (an abonnement with a wrong auth header on the perf kanaal) and assert that the other components' p95 does not degrade beyond the slowdown limit |
| How | Locust load + an extra abonnement in bootstrap on `ptest-bootstrap-perf` pointing at a mock-server path that answers 403 |

#### H3. Open Zaak #2577: hot zaak, ETag snowball, deadlock answered 503

| | |
| --- | --- |
| URL | <https://github.com/open-zaak/open-zaak/issues/2577>; changelog 1.31.1 (2026-10-23) |
| Component | Open Zaak (Zaken/Documenten API) |
| Kind | analysis by Den Haag with query counts; fix in 1.31.1 |
| Numbers | first ZIO on a zaak: 46 queries; with 500 ZIOs: 1,500+; twice per request; quadratic over a migration |
| Port value | the load shape the suite lacks: many writes to one resource and contention. Expected from 1.31.1: ZIO create time independent of the document count; deadlock → `503` + `Retry-After: 1` (retriable) instead of `500` |
| How | Locust `Prepared` call that seeds one zaak with N documents (registry cleanup) and times the (N+1)-th `link_document`; a second call where all users link to the same zaak. Assert no 500 with `responses.is_server_error`. Minikube and kees00 run 1.29.3: expect the old behaviour, so register it before marking |

#### H4. Memory retention and long-uptime degradation

| | |
| --- | --- |
| URLs | <https://github.com/maykinmedia/open-klant/issues/636> (fixed 2.18.0), <https://github.com/open-zaak/open-zaak/issues/1837> (fixed 1.21.0), <https://github.com/maykinmedia/open-klant/issues/323>, <https://github.com/maykinmedia/open-api-framework/issues/211> |
| Component | Open Klant, Open Zaak, all Maykin components (uWSGI `max-requests`) |
| Kind | measured memory series (Open Klant 291 MiB → 1.1 GiB in 22 calls), field reports |
| Port value | a soak profile with a memory assertion; the reproducer is "page through a list endpoint with `expand`". On environments with older images, it shows whether `max-requests` caps the growth |
| How | new perf test (soak) that reuses the Locust run, samples memory per container before, during and after (Grafana `proxy("prometheus", "/api/v1/query", ...)` with `container_memory_working_set_bytes`, or `kubectl top`), and asserts: peak < limit, no OOMKilled/restart (`workloads.cluster_state` before/after, `disruptions`), memory after the run within X % of the pre-run level |

#### H5. Keycloak benchmark, sizing guide and failure scripts

| | |
| --- | --- |
| URLs | <https://github.com/keycloak/keycloak-benchmark>, <https://www.keycloak.org/keycloak-benchmark/benchmark-guide/latest/scenario-overview>, <https://www.keycloak.org/high-availability/multi-cluster/concepts-memory-and-cpu-sizing>, <https://github.com/keycloak/keycloak-benchmark/blob/main/benchmark/src/main/content/bin/kc-chaos.sh>, <https://www.keycloak.org/keycloak-benchmark/kubernetes-guide/latest/util/kc-chaos> |
| Licence | Apache-2.0 |
| Component | Keycloak |
| Kind / tool | load scenarios (Gatling, Scala), sizing reference numbers, chaos scripts (kubectl, krkn tasks) |
| Activity | pushed 2026-11-11; 179 stars |
| Numbers | 1 vCPU per 15 password logins/s (tested to 300/s), per 120 client-credential grants/s (to 2,000/s), per 120 refresh-token requests/s (to 435/s); 1,250 MB per pod base; 150 % CPU headroom; 70 % of the memory limit for heap. Measured with 1M users, 20k clients, Argon2, 3 pods, Aurora |
| Port value | login storm (start of the working day: every ZAC/KISS/ITA/OAB user logs in) and token traffic of service clients; the per-vCPU figures turn a pod's CPU limit into a throughput threshold. `kc-chaos.sh`: delete a pod under load and measure recovery, the pattern for every component |
| How | port `ClientSecret` and the password grant to the suite's Locust (`password_grant`, bootstrap test clients); the authorization-code browser flow is covered by `challenge_session` logins. Gatling itself only as an external tool on a dev realm (it creates realms, users and clients) |

#### H6. Open Formulieren #2198: Den Haag load test, Celery/Redis exhaustion

| | |
| --- | --- |
| URL | <https://github.com/open-formulieren/open-forms/issues/2198> |
| Component | Open Formulieren (Celery worker, Redis) |
| Kind | field load-test finding (no script published) |
| Activity | closed 2022-12-23 |
| Port value | recovery check: work queued during a worker or Redis outage under load still completes. The suite has form submission helpers and Mailpit; no Open Formulieren load at all |
| How | Locust or a ThreadPool of N `start_submission`/`submit`, a worker restart (chaos tier) in between, then `registered_zaak` for every submission within a timeout. Requires `mailpit` capability (confirmation mails) |

### Medium

#### M1. Open Inwoner `performance-tests/` (Locust)

| | |
| --- | --- |
| URL | <https://github.com/maykinmedia/open-inwoner/tree/main/performance-tests> |
| Licence | EUPL-1.2 (GitHub NOASSERTION; verify) |
| Kind / tool | Locust file (2 kB) + `tests.sh` + result CSVs for 1.13.2 and zgw-consumers 0.28.0 |
| Activity | added 2024-01-15, fixed 2025-11-24 |
| Flow | DigiD-mock login (`/digid/idp/inloggen_ww/`), then HTMX fragments `/mijn-aanvragen/content` and a case's `…/status/content`, cached and uncached (`?_uncached=true`), 0.5 s wait |
| Reference numbers | (1 user, local, test.openzaak.nl) list: median 600–670 ms, uncached 8.2–9.1 s; status: median 480–500 ms, uncached 1.5–4.5 s; DigiD POST 2–4 s |
| Port value | the logged-in portal path under load; the suite's `oi_search` is anonymous. Mijn aanvragen fans out to Open Zaak, Open Klant and Objecten, and OI's earlier hang (NO MERCY) lives in this area |
| How | port to the suite's Locust with `portal_login` (DigiD mock via Keycloak), one inwoner per user from the identities seed; thresholds from the CSVs only as an order of magnitude |

#### M2. Objecten `performance_test/` (Locust + pytest-benchmark)

| | |
| --- | --- |
| URL | <https://github.com/maykinmedia/open-object/tree/master/performance_test> |
| Kind / tool | `locust/test_locust.py` (100 users, spawn 10, 60 s), `tests/test_objects_list.py` (pytest-benchmark, Bencher), `create_data.py` (5,000 records) |
| Activity | 2026-08-18 |
| Load shape | `GET /api/v2/objects?type=…&pageSize=500&ordering=-record__data__nested__timestamp`; benchmarks with pageSize 1000 (page 1 and 5) and 20 (page 50), `data_attrs=identifier__exact__…`, regression for open-object #538 |
| Reference numbers | `benchmark_assertions(mean=1, max=1)`: ≤ 1 s per call on CI |
| Port value | large pages and ordering on a JSON attribute, which `obj_vac_search` (pageSize 20, `icontains`) does not cover; the 1 s bound is a usable threshold. Stress-test plan in open-object #149 (100k imports and updates, page sizes 100–5,000, geo and date filters) |
| How | one extra call in `_objecten_calls` on the `ptest-volume` objecttype (seed-volume 1,000 objects) |

#### M3. Open Zaak performance index, #1647, #2161

| | |
| --- | --- |
| URLs | <https://open-zaak.readthedocs.io/en/latest/development/performance/index.html>, <https://github.com/open-zaak/open-zaak/issues/1647>, <https://github.com/open-zaak/open-zaak/issues/2161>, Bencher project (public API) <https://api.bencher.dev/v0/projects/open-zaak-ed2ce35-z71n5gf8t4f40> |
| Kind | release benchmark method + results; issues |
| Method | Locust, 1 and 16 users, superuser vs regular client, ≥ 5 min, 10 replicas × 1 CPU/1 Gi, 1M zaken/documenten/besluiten, 100 zaaktypen; 16 users need 4 processes × 4 threads |
| Numbers | Docker history (median over endpoints): 1.23.0 1 user 150/190 ms, 16 users 500/670 ms (superuser/regular). From 1.24 on, only relative changes per release |
| #1647 | `zaken?rol__…inpBsn=…&expand=*` took 34 s (expected < 1 s); the portal's "my zaken" with expand |
| #2161 | Maykin's open proposal for a realistic mix: weighted tasks per client type, reads and writes on hot resources, p50/p95/p99 per endpoint, recorded hardware and spread over repeated runs |
| Port value | a 16-user and ≥ 5 min profile instead of 5 users × 60 s; `oz_zaken_by_bsn` with `expand=zaaktype,status,…` (which the suite lacks); #2161 as the design target for a weighted mix |
| How | settings via `--perf-users 16 --perf-duration 5m`; one new call with expand. The 1.23 numbers fit `perf.yaml` only as a ceiling |

#### M4. ZAC `scripts/test-data/create-load.py` and reindex spec

| | |
| --- | --- |
| URL | <https://github.com/infonl/dimpact-zaakafhandelcomponent/blob/main/scripts/test-data/create-load.py>, <https://github.com/infonl/dimpact-zaakafhandelcomponent/blob/main/openspec/specs/solr-reindexing-performance/spec.md> |
| Licence | EUPL-1.2+ (SPDX header) |
| Kind / tool | Python ThreadPool load script (652 lines + `zac_client.py`, `zac_testdata.py`), BPMN `loadTestProcess.bpmn` and form; no Gatling/k6/Locust in ZAC |
| Activity | added 2026-04-22 (#5819), documents 2026-04-30 (#5881), last change 2026-11-04 |
| Flow | uploads a BPMN process and form, sets zaakafhandelparameters for 4 CMMN and 4 BPMN zaaktypen, creates N zaken through `POST /rest/zaken/zaak` with `--concurrency`, optionally uploads documents through `/rest/informatieobjecten/informatieobject/{zaak}/{zaak}` |
| Port value | ZAC writes under load (the suite times only `zac_search`): zaak create (Open Zaak + Flowable + Solr + notificatie chain) and document upload. The reindex spec (bounded concurrency, one ZRC read per zaak) gives a check: ZAC keeps answering searches and zaak pages during a full reindex, which seed-volume already triggers |
| How | port the two calls to the Locust file with `zac_session` (ADMIN, the bootstrap zaaktype); BPMN upload changes shared configuration, so leave it out. The local checkout is at v4.6.0; the script is on `origin/main` |

#### M5. ZaakBrug #714: Fo03 under highly concurrent genereer

| | |
| --- | --- |
| URL | <https://github.com/wearefrank/zaakbrug/issues/714>, follow-up <https://github.com/wearefrank/zaakbrug/issues/718>; `contrib/compose.frank.loc.perf-tests.yaml` (perf compose, no scripts published) |
| Licence | EUPL-1.2 |
| Kind | issue (open, 2026-10-26): `genereer[Zaak|Document]Identificatie` answers Fo03 under concurrent load since 1.26.17; quick fix PR #717, structural fix #718 (database sequences) |
| Port value | the suite serializes the first genereer calls because of zaakbrug-2 (first calls). #714 is about sustained concurrency after that. A Locust call on `genereer_zaak_id` shows it and gives ZaakBrug a load point at all |
| How | add `zaakbrug_genereer` to `ENDPOINTS` (component `zaakbrug`), assert distinct identificaties within a round; check known-issues before marking (may be zaakbrug-2 or a new id) |

#### M6. Open Archiefbeheer performance flow (Playwright, 10,000 zaken)

| | |
| --- | --- |
| URL | <https://github.com/maykinmedia/open-archiefbeheer/blob/main/backend/src/openarchiefbeheer/destruction/tests/performance/test_performance.py>, <https://github.com/maykinmedia/open-archiefbeheer/issues/496>, <https://github.com/maykinmedia/open-archiefbeheer/issues/655> |
| Kind / tool | Playwright (async) against a live `TEST_ENVIRONMENT`, prints the timing of every request; skipped by default; 12 kB |
| Activity | 2026-09-28 |
| Flow | list of 100 pages ("Gigantic list"), review, reject, re-submit, approve, archivist, "10000 zaken vernietigen"; waits 240 s for background processing |
| Findings (#496) | Open Zaak JWT expired after 1 h during a long sync (403), zaken fetches needed retries, a timed-out delete task left the list "processing" (#655) |
| Port value | a large background job; the check is whether the OAB worker survives it (memory, restarts) and the list reaches a final state. Destroying 10,000 zaken fits only a throwaway seed |
| How | adapt `test_vernietigingslijst.py` to a volume list from `seed-volume` (own zaaktype), chaos/perf tier only; observe with `cluster_state`/`disruptions` |

#### M7. Resource-sizing method for the Maykin components (open)

| | |
| --- | --- |
| URLs | <https://github.com/maykinmedia/charts/issues/367> (Dimpact integratieteam, open), <https://github.com/maykinmedia/open-api-framework/issues/241> (open, 2026-11-05) |
| Kind | planned method, no numbers yet |
| Content | Locust, 10 users, GET of every endpoint without filters, raise limits until every call < 100 ms; Locust tests for Open Notificaties, Open Klant and Objecten "with representable data"; Python memory "ballooning" seen at Open Formulieren (2026-06-29) |
| Port value | when published, the advised requests and limits are thresholds to check a deployment against; the "all GET endpoints, 10 users, < 100 ms" profile is cheap to add (one call per list endpoint) |
| How | watch both issues; no port yet |

#### M8. helm-charts: Open Zaak DB connection pooling doc (local)

| | |
| --- | --- |
| Path | `dimpact-samenwerking/helm-charts/charts/podiumd/docs/apps/openzaak/openzaak-db-connection-pooling.md` (local checkout, 2026-11-12) |
| Content | uWSGI 2 processes × 4 threads, `maxRequests: 1000`; pooling "explicitly experimental… only after verifying stability under load" |
| Port value | the perf tier is the "verify under load" step: run with pooling on and off at 16 users, compare p95, failures, connection count and restarts |
| How | run the perf tier twice on minikube with the two values (podiumd-minikube owns the values: handoff file) |

### Low

| # | Source | URL | Why low |
| --- | --- | --- | --- |
| L1 | TA `perf/hairpin-compare.js` + `run-hairpin-compare.sh` (only in TA podiumd-4.8.2, removed in 4.8.4; not in MIGRATION.md) | local `icatt-menselijk-digitaal/podiumd-testautomation/podiumd-4.8.2/test-automation/tests/perf/` | k6, constant arrival rate 10/s; public hostname vs `frankgateway-internal:9080`, run as an in-cluster Job. Network-path cost, not availability; needs an in-cluster runner. Add a MIGRATION row (drop or todo) |
| L2 | Open Zaak "Apache Benchmark stress test" | <https://open-zaak.readthedocs.io/en/latest/development/performance/apachebench.html> | `ab -n 1000 -c 100` on the API root; tests ingress/TLS throughput. The gateway scenario `openzaak_root` already covers it |
| L3 | APISIX benchmark | <https://apisix.apache.org/docs/apisix/benchmark/> | wrk numbers for bare APISIX; Frank!Gateway publishes none; only a comparison for `test_gateway_perf.py` |
| L4 | Keycloak admin scenarios (`CreateDeleteUsers`, `UserCrawl`, …) | keycloak-benchmark | admin load is no PodiumD use; would write to the shared realm |
| L5 | Open Formulieren #6515 (uWSGI timeouts with 28–70 registrations) | <https://github.com/open-formulieren/open-forms/issues/6515> | PodiumD forms have one registration backend |
| L6 | OneGround "99 % of ZGW requests within 50 ms" | <https://dev.oneground.nl/docs/about-oneground> | vendor claim, no method |
| L7 | Bencher project of Open Zaak (public API) | <https://api.bencher.dev/v0/projects/open-zaak-ed2ce35-z71n5gf8t4f40> | benchmarks `test_eio_list`, `test_eio_list_with_ordering`, `test_zaken_list` on GitHub runners; already ported; CI noise (#2161 notes Zen 3 vs Zen 4) |
| L8 | VNG gemma-zaken discussion #1960, OpenZaakBrug #323 | <https://github.com/VNG-Realisatie/gemma-zaken/discussions/1960>, <https://github.com/Sudwest-Fryslan/OpenZaakBrug/issues/323> | API design for fewer calls (expand/include); timings of one client |
| L9 | Open Zaak #2529 (uncached loose-fk fetches; concurrent creates deadlock the caller) | <https://github.com/open-zaak/open-zaak/issues/2529> | only with external loose-fk URLs (gpp-publicatiebank); PodiumD links within one Open Zaak |

## Tooling for availability under load

| Tool | URL / place | Licence | Use for podiumd-tests |
| --- | --- | --- | --- |
| suite: `workloads.cluster_state` / `disruptions` | `src/podiumd_tests/workloads.py` | own | take a state before and after the Locust run in `tests/perf` and assert "no pod gone, started or restarted" per component (with the restart's `lastState.terminated.reason`, e.g. OOMKilled). It already exists, so only the assertion is new (reuse, no copy) |
| kube-state-metrics pod metrics | <https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/workload/pod-metrics.md> | Apache-2.0 | `kube_pod_container_status_restarts_total`, `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}`, with cAdvisor `container_memory_working_set_bytes` and `container_cpu_cfs_throttled_periods_total`, through `Grafana.proxy` to Prometheus over the run's time window: memory peak vs limit, CPU throttling (Keycloak sizing: throttling degrades sharply). The Prometheus of minikube and kees00 scrapes neither (checked 2026-11-14), so `perf.availability` reads the same series from the kubelet through the API server's node proxy (`/metrics/resource`, `/metrics/cadvisor`) |
| Locust load shapes and history | <https://github.com/locustio/locust/tree/master/examples/custom_shape>, `--csv-full-history` | MIT | `step_load.py`/`stages.py`: ramp to find the breaking point and a spike-then-recover shape. `stats_history.csv` gives 5xx bursts over time to line up with pod restarts |
| locust-plugins | <https://github.com/SvenskaSpel/locust-plugins> | Apache-2.0 | `--check-fail-ratio` etc. are redundant with `perf.yaml`; Timescale dashboards not needed (Grafana exists). Low |
| krkn (pod-scenarios) | <https://github.com/krkn-chaos/krkn>, <https://krkn-chaos.dev/docs/scenarios/pod-scenario/> | Apache-2.0 | kill pods by label with recovery checks; used by keycloak-benchmark. Heavier than needed; the suite's own scaling or `kubectl delete pod` via `Kube` does the same in the chaos tier |
| Chaos Mesh / LitmusChaos | <https://chaos-mesh.org/docs/simulate-pod-chaos-on-kubernetes/>, <https://github.com/litmuschaos/litmus> | Apache-2.0 | network delay, packet loss and memory stress need a cluster operator (CRDs). Only if the user wants network faults; installation belongs to podiumd-minikube (handoff) |
| chaoskube / kube-monkey | <https://github.com/linki/chaoskube>, <https://github.com/asobti/kube-monkey> | MIT / Apache-2.0 | random pod kills on a schedule; unsuited to a reproducible test |
| xk6-disruptor | <https://github.com/grafana-cold-storage/xk6-disruptor> | AGPL-3.0 | archived (moved to grafana-cold-storage); do not use |

## Looked, nothing useful

- **TA (all local versions 4.8.2–4.9.0):** `api-perf.js`, `fg-compare.js` and `lib.js` are identical across versions (md5)
  and already handled; `seed-test-data/fixtures/catalogus.perf.yaml` is a smoke catalogus fixture, not a load script;
  `run-perf.sh` is a wrapper. The test catalog's CONT rows are continuity (no load) and are in MIGRATION.md.
- **ZAC (local checkout v4.6.0 + `origin/main`):** no Gatling/k6/Locust/JMeter; `perf:` commits are code optimizations;
  ADR 0009 (JOL memory of ZTC caches; admin page `/rest/admin/util/cache/ztc` shows cache memory, which could become a
  doctor read but is undocumented and may disappear); `LargeDocumentUploadTest.kt` is a functional itest.
- **Open Klant, Objecttypen, Open Formulieren, Open Beheer, Referentielijsten repos:** no perf or load tests in the tree
  (open-forms only has profiling docs, <https://open-forms.readthedocs.io/nl/latest/developers/profiling.html>).
  Open Klant #385 is about query reduction, with no numbers.
- **Open Notificaties:** only `docs/development/performance/scenarios.rst` (one call, 1–100 VUs, no numbers), already
  ported as `onrc_notificatie`.
- **KISS-frontend, ITA, NotifyNL-OMC, PABC-API:** no perf tests in their trees and no perf issues with numbers (KISS #602
  is a caching idea).
- **Frank!Gateway (`wearefrank/frank-gateway`):** no tests or benchmarks beyond FSC test certificates; no perf issues.
  **Frank!Framework:** `CmisSenderPerformanceTest` is unit-level.
- **Haal Centraal BRP (`BRP-API/Haal-Centraal-BRP-bevragen`):** no load tests; RvIG only claims availability and performance.
- **Open Producten:** has performance docs, but it is not a PodiumD component.
- **Web searches** for gemeente, Dimpact, VNG or supplier load-test reports on ZGW APIs ("belastingtest", "performancetest
  PodiumD", OneGround): none published; the only field reports are the Den Haag findings inside the GitHub issues above
  (Open Zaak #2577, Open Formulieren #2198).
- **Local repos:** ExternalsPodiumD, podiumd-minikube and podiumd-infra(-perf: deploy speed) have no load tests;
  helm-charts has only the pooling doc (M8).
