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
