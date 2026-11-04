# Open requests for podiumd-infra

## ZAC's Solr with 3 nodes on kees00, as ExternalsPodiumD (Kees, 2026-11-04)

`values/kees00/podiumd.yaml:2455` sets `zac.solr-operator.solr.replicas: 1`. ExternalsPodiumD sets no value, so it runs
the zac chart default of 3 Solr nodes. ZAC creates its `zac` collection with `numShards=2&replicationFactor=2`, so on
one node both replicas of a shard share the node. Then Solr at times rejects an update with "Request says it is coming
from leader, but we are the leader", and ZAC answers a zaak create with HTTP 500
`msg.error.search.indexing.exception` (seen on minikube 2026-11-04 09:55 CET, same layout).

Request: remove `replicas: 1` under `zac.solr-operator.solr` (chart default 3). The collection keeps its existing
replica placement: after the deploy, move one replica of each shard to another node (Collections API `MOVEREPLICA`), or
recreate the `zac` collection and reindex in ZAC (Beheer, "Herindexeren").

Verify: `CLUSTERSTATUS` for `zac` shows the two replicas of each shard on different nodes; then
`podiumd-tests run --env kees00 --tier core`.
