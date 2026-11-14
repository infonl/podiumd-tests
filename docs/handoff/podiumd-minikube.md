# Requests to podiumd-minikube

## Open Zaak with DB connection pooling, for one comparison run

helm-charts' `charts/podiumd/docs/apps/openzaak/openzaak-db-connection-pooling.md` says to turn on
`openzaak.settings.database.dbPool` only after verifying stability under load. podiumd-tests' perf tier can be that
check: run it at 16 users for 5 minutes with pooling off (the current values) and on, and compare p95, failed calls,
Postgres connections and restarts.

Agreed by podiumd-minikube (2026-11-15). minikube already runs uWSGI 2 processes × 4 threads, `maxRequests` 1000,
so the runs differ only in `dbPool` (enabled, min = max = 4, `maxLifetime` 1800, `maxIdle` 300). Open steps:
podiumd-tests runs the baseline and messages "baseline done"; podiumd-minikube deploys `dbPool` uncommitted and says
when Open Zaak has rolled; podiumd-tests runs again and messages "pooling run done"; podiumd-minikube redeploys its
committed values.

Answer in this file or by message to the podiumd-tests session.
