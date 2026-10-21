# Requests for podiumd-minikube

Open requests from podiumd-tests for the agent working in infonl/podiumd-minikube.

## Deploys: exercise `helm upgrade`

minikube deploys with `helm template | kubectl apply` (`src/podiumd_minikube/manifests.py:1-7`: Helm's release
record exceeds the 3MB API limit). kees00 runs `helm upgrade --install --force-conflicts`; ExternalsPodiumD runs
`helm upgrade --server-side=true --force-conflicts` on long-lived clusters, after deleting a fixed list of 13 Job
names (`pipelines/application.yml:331-356`). What minikube therefore never runs:

- `lookup`: it returns nothing under `helm template` (`_helpers.tpl:911-912`), so the upgrade path that keeps
  generated secrets (`keycloak-podiumd-realm-secrets`, Frank!Gateway keys) and the PV/PVC skip logic
  (`_helpers.tpl:1098, 1141`) are never used;
- `.Release.Revision` above 1 (`keycloak-repair-client-scopes-{{ .Release.Revision }}`);
- hook order and weights (`openbao-db-schema` pre-install weight -5, `openbao-config` and `frankgateway-seed`
  post-install);
- upgrade failures: "field is immutable" on a Job with a fixed name, field-manager conflicts with operators,
  StatefulSet selector changes, CRD upgrades;
- image digest pins (`strip_image_digests`).

Requested:

1. A step that runs the chart through Helm against the cluster, e.g. `helm upgrade --install --dry-run=server`
   of the podiumd chart, or a real `helm upgrade` into a scratch namespace, on every chart change.
2. A check that lists every Job with a fixed name in the rendered chart (subcharts included) and compares it
   with ExternalsPodiumD's delete list; report the Jobs missing from that list.

## Keycloak: a profile with `skipRoles` / `skipGroups: true`

The chart default and ExternalsPodiumD dimp (test, ontw) use `keycloak.config.skipRoles/skipGroups: true`;
minikube (`values.yaml:54-55`) and kees00 use `false`. With `true` the realm import creates no realm roles
(`keycloak-podiumd-realm-config.yaml:1150-1210`: `podiumd-admin`, `DMT-Functioneel-Beheerder`, the PABC roles,
the `zaakbrug` client roles) and `pabc-keycloak-groups-job` does that work; on minikube that Job changes nothing
(`pabc-keycloak-groups-job.yaml:77-78`). A defect in that path passes on minikube and fails on dimp.

Requested: a deploy profile (or option) with both set to `true`, with the groups created as a gemeente does.
Tell podiumd-tests when it exists, so its bootstrap and tests can run against it.

## Postgres: as Azure Flexible Server

minikube runs PostGIS 16 in the cluster, and each app role owns its database
(`vendor/dimpact-zaakafhandelcomponent/postgres/00-create-databases.sql`). kees00 runs Azure Flexible Server 15
(`create-test-environment.yml:389-392`) with `azure.extensions = POSTGIS,PG_TRGM` only (`:431`) and per-app
roles with grants (`create-postgresql-databases.sh:145-195`). A migration that runs `CREATE EXTENSION` for
another extension (btree_gist, citext, unaccent, uuid-ossp), SQL that needs 16, or an `ALTER` on an object
another role owns passes on minikube and fails on Azure.

Requested: Postgres 15, roles with grants instead of ownership as on kees00, and the same extension allow-list
(Postgres has no setting for it: an event trigger on `CREATE EXTENSION`, or a check after each deploy).

## Document the remaining differences

Please record in podiumd-minikube (README or a doc next to `values.yaml`) each difference below: what
minikube does, what the estates do, and what it leaves untested. Where a comment already exists, a link is
enough.

| Area | minikube | Estates |
| --- | --- | --- |
| Redis HA | 1 replica (`values.yaml:78`) | 3; ExternalsPodiumD relabels the master in office hours |
| Keycloak | 1 instance (`values.yaml:29`), no comment | 2, kees00 with a PDB |
| Storage | hostPath ReadWriteOnce (`templates/storage-hooks.yaml`) | Azure Files SMB/NFS, shared between pods |
| Nodes | 1; required anti-affinity dropped; ES, Solr, ZooKeeper 1 node | several nodes; ExternalsPodiumD test: OI ES 2, KISS ES 3 |
| Edge routes | generated from the chart's Ingresses (`gateway.py`) | ExternalsPodiumD: hand-written HTTPRoutes with `X-Forwarded-*`; kees00 moved to NGF on 2026-10-20 |
| Pod tuning | service links off, GC/malloc settings, CA in every pod (`manifests.py:41-49, 127-143`) | none; apps use the chart's CA options |
| External services | BAG mock with two answers, Mailpit without STARTTLS, no e-Suite, ClamAV with EICAR only | real Kadaster BAG, relay SMTP, e-Suite on some |
| Monitoring | anonymous Grafana, Loki filesystem store | Grafana through Keycloak client `monitoring`; ExternalsPodiumD Loki distributed |
| Clients | datamigratie off | on where datamigratie runs |

One item may be a chart defect rather than a minikube choice: the service-link collision that broke Solr and the
Open Notificaties worker (`manifests.py:127-143`). Please check whether the colliding Service names also exist in
an estate's namespace; if so, report it to helm-charts.
