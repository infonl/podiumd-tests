# Open requests for podiumd-infra

## ClamAV metrics on kees00, as ExternalsPodiumD (2026-11-04)

ClamAV runs on kees00 since podiumd-infra 7ddf377, but without its exporter: pod `clamav-0` has only the `clamav`
container and there is no ServiceMonitor, so `test_every_component_reports_metrics` fails with "components without
metrics in Prometheus: ['clamav']" (core 20261104-113142, the only failure). ExternalsPodiumD (dim1) sets
`clamav.metrics.enabled: true` with `serviceMonitor.enabled: true` (interval 30s, scrapeTimeout 10s), as the chart's
`values-enable-observability.yaml`; minikube runs the exporter too.

Request: the same `clamav.metrics` block for kees00 (`values/kees00/podiumd.yaml`).

Verify: pod `clamav-0` has the `clamav-exporter` container, a ServiceMonitor for clamav exists, then
`podiumd-tests run --env kees00 --tier core -- -k test_every_component_reports_metrics`.
