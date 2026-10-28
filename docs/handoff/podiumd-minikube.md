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

## Metrics for Frank!Gateway and OpenBao, as the chart's values-enable-observability.yaml (podiumd-tests, 2026-10-28)

`tests/smoke/test_metrics.py::test_every_component_reports_metrics` fails on minikube with "components without
metrics in Prometheus: ['frankgateway', 'openbao']" (run with `--runxfail`, 2026-10-28; until now hidden by the
podiumd-chart-19 xfail, which podiumd-tests moves to podiumd < 4.10.0). Published 4.10.0's
`charts/podiumd/values-enable-observability.yaml` has both sections; minikube's metrics profile applies neither:

- `frankgateway.metrics.enabled: true`, `frankgateway.metrics.serviceMonitor.enabled: true` (interval 30s)
- `openbao.serverTelemetry.serviceMonitor.enabled: true` with `openbao.server.extraPorts` and
  `openbao.server.service.extraPorts` for the metrics listener on 9101 (the render fails without them). Turning it
  on restarts the OpenBao pods; with the Shamir seal they come back sealed.

Also: the comment in podiumd-minikube `values.yaml` near `eck-operator.config.metrics.port` says the chart's
`values-enable-observability.yaml` sets `metricsPort`; published 4.10.0 sets `config.metrics.port: "8080"`
(podiumd-chart-15 is fixed there).
