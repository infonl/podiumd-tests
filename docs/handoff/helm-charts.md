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
