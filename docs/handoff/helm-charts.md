# Handoff to helm-charts

Open items for the helm-charts session. Delete an item when it is done; delete the file when nothing is open.

## Known issues to fix in PodiumD 4.11.0 (Kees, 2026-11-17)

1. SD-10 (rest), Medium: `openinwoner.eck-elasticsearch.image` with digest
   (`docker.elastic.co/elasticsearch/elasticsearch:9.2.0@sha256:...`). Not in the 4.11.0 batch (Kees): first a release-tooling
   PR on main (one image string, the repository at 9.2.0 and 8.19.24, ACR mirror name elasticsearch/elasticsearch),
   then the pin; send podiumd-tests the PR number.

## Release note for PodiumD 4.11.0 (podiumd-tests, 2026-11-18)

1. ZAC 5.8.0 to 5.10 put completed taken of zaakspecifiek geautoriseerde zaken back in ZAC's Solr index, so they show
   in "Aan mij toegewezen taken", Mijn taken, the taken werkvoorraad and the taken search (PZ-13176, ZAC #6920). ZAC
   5.11.0 fixes the cause (#7595), but the stale taken stay until the taken are reindexed. An estate that ran
   PodiumD 4.10.x (ZAC 5.9.x) needs a reindex of the taken after the upgrade to 4.11.0 (ZAC 5.12.0); PZ-13189 holds
   Dimpact's instructions. The 4.11.0 release notes do not mention it yet. podiumd-tests covers the fix in
   `test_zac_zaakspecifiek.py::test_taak_of_a_marked_zaak_is_read_only_by_its_behandelaar` (dffe898).

## OMC's Documenten endpoint for the Berichtenbox (MOBB) scenario (Kees, 2026-11-19)

OMC downloads a bericht's bijlagen (the PDF of a brief) from the Documenten API at
`omc.settings.zgw.endpoint.documenten` (`ZGW_ENDPOINT_DOCUMENTEN`, notifynl-omc-nodep 0.17.8: "MOBB fetches real
attachment content from here"). The podiumd chart sets no default, and no environment sets it (minikube, kees00,
every ExternalsPodiumD gemeente at 8fb69ad). OMC then logs "0 usable attachment(s)" and offers the bericht to the
Berichtenbox without its PDF. podiumd-tests `test_berichtenbox_bericht_is_offered_to_the_berichtenbox` (IN-3532 item 1)
fails on it on minikube.

1. A default in the podiumd chart for `omc.settings.zgw.endpoint.documenten`. Suggestion: derive it from
   `endpoint.openZaak` (its `/zaken/api/v1` replaced by `/documenten/api/v1`) when unset, so every estate that sets
   `openZaak` gets it; your call how.
2. If applicable, the 4.11.0 values-deltas.md in `charts/podiumd/docs/_UPGRADE_PATHS/`: the per-environment keys and
   values an estate needs to turn the MOBB scenario on, e.g. `endpoint.openVtb`, `auth.key.openvtb`,
   `endpoint.documenten` (unless derived), `whitelist.vtbMessage.types`, the `NOTIFY_TEMPLATEID_*_MESSAGEBOX` templates,
   `openvtb.celery.enabled` (#746), Open VTB's Open Notificaties wiring, and the Open Notificaties abonnement for OMC
   with `sendCloudevents` and typeSubstring `nl.overheid.berichten.` (podiumd-tests' bootstrap makes it on its
   environments; estates make it by hand).

Tell podiumd-tests the PR; it reruns the IN-3532 tests on minikube once podiumd-minikube deploys it.

## Automatic failover for redis-ha (podiumd-chart-24; Kees, 2026-11-23)

Gemeenten still report admin 500s and 504s on the Maykin apps (IN-2869, IN-3210: Objecten `/admin/login/`, Taiga issue
611). PRs #634 and #681 shortened the window; redis-ha still promotes no replica, so Redis is down until the old
master pod is back: seconds after a pod deletion, several minutes after a node failure (5 min toleration plus zonal disk
reattach). Background and the operator analysis: podiumd-known-issues `issues/podiumd-chart-24-*.md`
(§ "Analysis of a Sentinel fix"). Target: `feature/podiumd-4.11.0`. The design is yours; the analysis's Sentinel plus
labeller design meets these requirements if its blockers are handled.

Requirements:

1. Takeover: when the master pod or its node goes, a replica becomes master and `redis-ha-master` points at it within
   30 s, without waiting for the old pod to come back.
2. One master: `redis-ha-master` never has more than one ready endpoint, and its endpoint always reports
   `role:master`, during and after a failover. The returning old master rejoins as a replica; nothing (operator, label
   CronJob, labeller) labels it master while another pod is master.
3. Apps unchanged: apps keep connecting to `redis-ha-master:6379/<db>`; no app needs a Sentinel-aware client or new
   settings. Connections to the old master are closed once it is a replica (#681 stays).
4. Losing a sentinel with the master: the takeover also works when the failed node held one sentinel (quorum of the
   remaining two). Sentinels spread over nodes, with a PodDisruptionBudget.
5. Data: keys on the replicas at failover time survive; document the loss window of asynchronous replication.
6. One pod: redis-ha with 1 pod (minikube scaled down) renders as today, without sentinels or labeller.
7. Hosting standards as the other workloads: image in the images manifest with digest and ACR mirror, runAsNonRoot
   (#648), `automountServiceAccountToken` only where RBAC is needed (#735), emptyDir `sizeLimit` (#730), requests and
   limits, probes.
8. Upgrade: in place from 4.10.x without data loss; upgrade notes name the redis-ha restart and its duration.
9. Docs: correct `redis-ha.md` "Failover safeguards" and the "brief sentinel failover" in the 4.7.8-to-4.8.0 guide;
   state the expected outage per failure (pod, node, partition).
10. Visible: each master change shows in a log line or metric (which pod, when).

Verification by podiumd-tests (tier chaos; minikube has one node, so node tests run on kees00):

- `test_redis_ha_master_recovers_when_the_master_pod_is_deleted` changes to expect a takeover: a replica (not the
  recreated pod) is master behind `redis-ha-master` within 30 s and holds the key; sampled every second, never two
  endpoints and never an endpoint that reports `role:slave`; the old pod rejoins as a replica.
- New: the master's node is drained (kees00): takeover within 30 s.
- New: the master pod and one sentinel are deleted together: takeover within 30 s.
- `test_continuiteit_opslag.py` (Redis master restart under load): the apps' outage stays under 30 s, no READONLY
  error count on the replicas afterwards and no app connection on them; `/admin/login/` of every Maykin app answers
  without 500 or 504 after the failover (the IN-3210 symptom).
- Existing: `test_redis_ha_master_service_points_at_the_master` (#634) keeps passing.

Tell podiumd-tests the PR; it runs these tests on minikube and kees00 before the merge.
