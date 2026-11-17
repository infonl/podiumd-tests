# Handoff to helm-charts

Open items for the helm-charts session. Delete an item when it is done; delete the file when nothing is open.

## Known issues to fix in PodiumD 4.11.0 (Kees, 2026-11-17)

1. SD-10 (rest), Medium: `openinwoner.eck-elasticsearch.image` with digest
   (`docker.elastic.co/elasticsearch/elasticsearch:9.2.0@sha256:...`). Not in the 4.11.0 batch (Kees): first a release-tooling
   PR on main (one image string, the repository at 9.2.0 and 8.19.24, ACR mirror name elasticsearch/elasticsearch),
   then the pin; send podiumd-tests the PR number.
