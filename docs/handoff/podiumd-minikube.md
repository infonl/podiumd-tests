# Requests for podiumd-minikube

## Open Inwoner's KvK configuration through the chart

helm-charts #604 (merged into `feature/podiumd-4.10.0`) configures Open Inwoner's KvK API with
`openinwoner.kvk.apiRoot`; its Job `openinwoner-configure-kvk` writes it. kees00 sets it since 2026-10-19 and the Job
completes there. podiumd-tests' bootstrap step `openinwoner-kvk` does the same on minikube today and hides whether the
chart works; it is removed once minikube sets the value.

Set, as podiumd-infra does for kees00:

```yaml
openinwoner:
  kvk:
    apiRoot: http://api-proxy.podiumd-minikube.svc.cluster.local/api/
```

- The host needs a dot: Open Inwoner's URL validator refuses `http://api-proxy/api/` (podiumd-chart-10).
- No `apiKey`: the api-proxy adds none.

Done when the Job `openinwoner-configure-kvk-*` completes on minikube; tell podiumd-tests, which then removes its step.
