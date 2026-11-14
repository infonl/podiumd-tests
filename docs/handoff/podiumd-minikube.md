# Requests to podiumd-minikube

## Open Zaak with DB connection pooling, for one comparison run

helm-charts' `charts/podiumd/docs/apps/openzaak/openzaak-db-connection-pooling.md` says to turn on
`openzaak.settings.database.dbPool` only after verifying stability under load. podiumd-tests' perf tier can be that
check: run it at 16 users for 5 minutes with pooling off (the current values) and on, and compare p95, failed calls,
Postgres connections and restarts.

Request: when it suits you, deploy Open Zaak on minikube with the doc's proposed values (`uwsgi` 2 processes × 4
threads, `maxRequests` 1000, `dbPool` min = max = 4), tell the podiumd-tests session, and put the old values back after
its run. podiumd-tests runs the baseline with pooling off first.

Answer in this file or by message to the podiumd-tests session.
