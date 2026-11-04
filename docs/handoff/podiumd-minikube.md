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

## ZAC's Solr with 3 nodes, as ExternalsPodiumD (Kees, 2026-11-04)

`values.yaml:527` sets `zac.solr-operator.solr.replicas: 1` (laptop budget). ExternalsPodiumD sets no value and runs
the zac chart default of 3 Solr nodes. ZAC creates its `zac` collection with `numShards=2&replicationFactor=2`, so on
one node both replicas of a shard share the node. Solr then at times rejects an update with "Request says it is coming
from leader, but we are the leader" (`zac_shard2_replica_n6` "now thinks it is the leader"), and ZAC answers a zaak
create with HTTP 500 `msg.error.search.indexing.exception`: `test_word_document_is_converted_to_pdf` failed once on
2026-11-04 09:55 CET (helm-charts 0286636c, podiumd rev 12); 26 Solr errors in two bursts, 09:55:00 and 09:55:35.

Request (Kees chose 3 nodes over keeping 1): remove `replicas: 1` (chart default 3); keep the laptop heap and
resources per node, or lower them, about 2 GiB more in total. On an existing cluster the collection keeps its replica
placement: move one replica of each shard to another node (Collections API `MOVEREPLICA`) or recreate the collection
and reindex in ZAC. A fresh install places them on separate nodes.

Verify: `CLUSTERSTATUS` for `zac` shows the two replicas of each shard on different nodes. Tell podiumd-tests; it then
runs the full tier.
