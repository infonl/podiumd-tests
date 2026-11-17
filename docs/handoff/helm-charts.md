# Handoff to helm-charts

Open items for the helm-charts session. Delete an item when it is done; delete the file when nothing is open.

## Known issues to fix in PodiumD 4.11.0 (Kees, 2026-11-17)

1. SD-10 (rest), Medium: `openinwoner.eck-elasticsearch.image` with digest
   (`docker.elastic.co/elasticsearch/elasticsearch:9.2.0@sha256:...`). Waits for the digest tooling (string image pins,
   one repository at two versions); send podiumd-tests the PR number.
