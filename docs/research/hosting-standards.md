# PodiumD hosting standards: what podiumd-tests can verify

Source: `hosting-contract-2025Q4.pdf` in Dimpact-Samenwerking/podiumd-hosting-standards (the README calls it the current
version; `PodiumD_Hosting_Standards-2026Q1.md` there has the same COMP identifiers). Analysed 2026-11-18.

The contract states what Dimpact expects from suppliers (component publishers) so SSC can host PodiumD. podiumd-tests
checks a running environment, so it can verify only what a deployed PodiumD shows: Kubernetes objects, HTTP
behaviour, logs, metrics and behaviour under disruption. Process, documentation and Azure-side items are out of
reach.

## Measured on kees00 (AKS, PodiumD 4.11.0), 2026-11-18

Read-only, 65 Deployments and StatefulSets in namespace podiumd:

| Check | Conforming |
| --- | --- |
| containers request CPU and memory (COMP020) | 65 / 65 (smoke `test_containers_request_cpu_and_memory`) |
| memory limit / CPU limit (COMP020) | 34 / 65 / 25 / 65 |
| liveness / readiness / startup probe on every container (COMP014.2) | 48 / 38 / 12 of 65 |
| runs as non-root (COMP023) | 58 / 65 |
| drops ALL capabilities (COMP023) | 57 / 65 |
| read-only root filesystem (COMP023) | 17 / 65 |
| 2 or more replicas (COMP006.1) | 8 / 65 |
| covered by a PodDisruptionBudget (COMP014.4) | 16 / 65 |
| topology spread or pod anti-affinity (COMP014.3) | 13 / 65 |
| HorizontalPodAutoscaler (COMP020) | 1 / 65 |
| secret-like env var with a literal value (COMP012) | 2 workloads: zgw-office-addin-backend (`JWT_SECRET`, `MSAL_SECRET`), frankgateway-etcd |
| container clock and `TZ` (COMP004) | UTC, `TZ` unset (openzaak) |

Images run by digest from podiumdregistry.azurecr.io, so the semantic-version label of COMP003.3 is not visible on
the running image; it is in the chart, not the cluster.

Most gaps are supplier obligations with Dimpact's own deadline ("hot items" by end of Q1 2026), not regressions.

## Per standard

Legend: **covered** (a test checks it today), **new test** (observable, worth a gating test), **report** (observable,
but most components do not conform yet: list it, do not fail on it), **n/a** (not observable from a running
environment).

| Standard | Verdict | How |
| --- | --- | --- |
| COMP001 naming | n/a | Naming taste; chart and namespace layout are SSC/podiumd-chart decisions. |
| COMP002.1 version API | report | GET `/api/v1/version` and `/health/version` without login on every component; record which answer JSON with name and version. Expected: almost none. |
| COMP003.1 containers | n/a | True by construction. |
| COMP003.3 registry, semver labels | report | `app.kubernetes.io/version` label of each workload is SemVer; image tags are replaced by digests on AKS. smoke `test_images_are_pinned` covers "no latest". |
| COMP004 timezone | new test | Container clock and `TZ` are UTC; PostgreSQL `SHOW timezone` is UTC (Django shell or psql in the database pod). |
| COMP005 supply chain | n/a | Scanning process at supplier and SSC. pip_audit covers podiumd-tests itself only. |
| COMP006.1 stop/start safe | covered, extend | Continuity tests restart ZAC, Keycloak, Postgres, Redis, Solr and the Open Formulieren worker. New: delete one pod of every component under load; the root answers again within the restart budget, and with 2+ replicas no request fails (chaos tier). |
| COMP006.2 zero-downtime rolling upgrade | new test (chaos) | `kubectl rollout restart` of each Deployment with 2+ replicas under `watched_load`: no failed request. Where replicas are 1 (minikube, most of kees00) the test skips with the count. |
| COMP006.3, COMP010 rollback | n/a | Needs a downgrade with a schema rollback; belongs to podiumd-minikube's upgrade checks. zac-42 shows the risk. |
| COMP007.x Helm, operators, sub-charts | n/a | Chart structure; helm-charts' own lint/CI. |
| COMP008.1 100% automated | covered | Every podiumd-tests estate is deployed by chart only; smoke `test_jobs_succeeded` and `test_workloads_ready`. |
| COMP009 internal communication | new test | Every Service URL in the apps' configuration (zgw_consumers Services, ZAC/KISS/ITA env) points to a cluster address (`*.svc.cluster.local` or a Service name), not the public host. |
| COMP011 no local storage | report | Workloads writing to the root filesystem without a volume: `readOnlyRootFilesystem` false and no PVC or emptyDir for their data path. Only the flag is observable; the data path needs per-component knowledge. |
| COMP012 secrets | new test | No env var whose name says PASSWORD, SECRET, TOKEN or KEY has a literal `value`; it must use `valueFrom.secretKeyRef`. Today 2 workloads fail. |
| COMP013 HTTP behind the gateway | covered | Services are plain HTTP; TLS at the edge is checked by `test_tls_meets_ncsc_guidelines`. |
| COMP014.1 health states | report | Whether a component's health endpoint distinguishes degraded from unhealthy is per component; record the endpoints' answers while a dependency is down (continuity tests stop them already). |
| COMP014.2 probes | new test + report | Gating: every serving container (it has a Service port) has liveness and readiness probes. Report: startup probes, workers and beats without probes. Behaviour: liveness does not fail when the database or Redis is down; `test_no_other_container_restarts_when_*` already shows it for Postgres and Redis (open-inwoner-7 is a gap). New: readiness turns false (pod leaves its Endpoints) while the database is down. |
| COMP014.3 redundancy | report | Replicas, topology spread, anti-affinity per workload; only meaningful on a multi-zone production-like estate, so report, never gate. |
| COMP014.4 PDB | report, partly covered | Keycloak and redis-ha are checked; report every workload with 2+ replicas without a PDB. |
| COMP015.1 logging to stdout | covered | `test_every_pod_logs_to_loki`. Report: JSON log lines share per component, `LOGLEVEL` env var present. |
| COMP016.2 UTC log timestamps | new test | Sample recent log lines per component from Loki; parsed timestamps are UTC (no offset other than Z or none). |
| COMP017 golden signals | report | Per component in Prometheus: a request-duration histogram, a request counter, an error-status label, a saturation gauge. `test_every_component_reports_metrics` checks only that series exist. |
| COMP018 alerting | new test (if alerts are shipped) | Every PrometheusRule alert has a severity label and summary, description and runbook_url annotations. |
| COMP019 SLO | n/a | Documentation; podiumd-tests' perf gate (perf.yaml) already uses SLO-style thresholds. |
| COMP020 resources | covered + report | Requests covered; report memory and CPU limits and HPAs. |
| COMP021 DR, backups | n/a | Azure backups and restore drills. |
| COMP022 release notes | n/a | Document content (helm-charts' release-notes skill). |
| DNS naming: any URL at once | new test | Each API answers the same through its public host and its cluster Service (host-header mode exists in `make_session`); the cluster URL is the one other components use. |
| COMP023 container security | covered + report | `test_pods_meet_the_baseline_security_standard` gates the baseline. Report: non-root, drop ALL, read-only root filesystem (restricted profile). |
| COMP023 network security | covered + report | `test_network_policy_blocks_a_non_allowlisted_pod`; TLS 1.2+; anonymous calls refused. Report: workloads no NetworkPolicy selects. |
| COMP023 secret rotation | n/a | Process; `podiumd-tests bootstrap --rotate` exists for test secrets only. |
| COMP024 SBOM | n/a | Registry attestations are not visible from the cluster (images by digest from ACR). |
| COMP025 API practices | report | OpenAPI document reachable per API (`/api/v1/schema` etc.); errors are JSON with a code (validation tests cover Open Zaak, Open Klant). Versioned paths are true for the ZGW APIs. |
| COMP026 service mesh | n/a | Not used. |
| COMP027 documentation | n/a | Documents. |
| COMP028 audit | new test | Keycloak records login and admin events (realm `eventsEnabled`, `adminEventsEnabled`); a failed login appears among the events. Open Zaak's audittrail is covered. GDPR items n/a. |
| COMP029 performance | covered (perf tier) | perf.yaml thresholds; align p95 targets with 200 ms interactive and 500 ms API. |
| COMP030 cost | n/a | |

## Proposal

1. **One shared check module, two uses.** `src/podiumd_tests/hosting_standards.py` computes per workload and per
   component what the table marks new test or report (probes, limits, securityContext, PDB, spread, HPA, secret env,
   version endpoint, UTC, metrics signals). `podiumd-tests standards --env X` writes the matrix (component x
   standard: conforms, gap, n/a) to `results/` as Markdown, like the run summary. Gating tests call the same
   functions (repository rule: doctor and tests share one function).
2. **Gating tests, only where PodiumD should already conform** (smoke or component tier):
   - secrets come from secretKeyRef (COMP012): fails today on 2 workloads;
   - serving containers have liveness and readiness probes (COMP014.2);
   - container clock, `TZ`, PostgreSQL and log timestamps are UTC (COMP004, COMP016.2);
   - apps reach each other through cluster addresses, and every API answers on public host and cluster Service
     (COMP009, DNS naming);
   - Keycloak records login and admin events (COMP028);
   - alert rules carry severity, summary, description and runbook_url (COMP018), if PodiumD ships alert rules.
3. **Chaos tests** (opt-in tier): delete one pod per component under load, and rolling restart per Deployment with 2+
   replicas: no failed request (COMP006.1, COMP006.2). They skip with the replica count where an estate runs one
   replica; minikube scales replicas down by design.
4. **Not a known issue per gap.** About 200 gaps against supplier obligations would swamp podiumd-known-issues and
   need an xfail each. The matrix is the record; a gating test that fails gets a known issue as usual.

Phasing: 1 and the probes/secrets/UTC tests first (about a day), then internal addressing and Keycloak events, then
the chaos tests. Report items move to gating once every estate conforms.

## Decisions (Kees, 2026-11-18)

- The matrix is for us only; it lives in the private podiumd-known-issues repository (`hosting-standards/`),
  regenerated with `podiumd-tests standards --env kees00 --output ...`.
- kees00 (podiumd-infra values on AKS) is the reference; minikube differs by design.
- A gap a gating test finds gets a known issue as usual: zgw-office-addin-2 (secrets), podiumd-chart-48 (probes),
  zac-48 (time zone).
