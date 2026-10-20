# Requests for helm-charts

Open requests from podiumd-tests for the agent working in Dimpact-Samenwerking/helm-charts.

## monitoring-logging: Traefik PodMonitor and docs (known issue podiumd-chart-14)

monitoring-logging 1.0.18 renders `PodMonitor/<release>-traefik` by default (`traefikMonitor.enabled: true`,
`templates/traefik-podmonitor.yaml`, added in #262). No estate runs Traefik since the move to NGINX Gateway
Fabric, so the monitor never has a target (minikube, 2026-10-20, branch `verify/podiumd-4.10.0-pr620`).
NGF is already scraped: its pods carry `prometheus.io/scrape: "true"` on port 9113 and Prometheus' job
`kubernetes-pods` picks them up.

Requested:

1. Set `traefikMonitor.enabled: false` by default, or remove the template and its values.
2. `docs/prometheus-scraping.md`: replace the Traefik rows with NGF (annotation scraping, port 9113).
3. `otelIngress` (`templates/otel-ingress.yaml`) supports only Traefik (`ingressClassName: traefik`, Traefik
   middleware): add a Gateway API HTTPRoute, or document it as Traefik-only.

podiumd-tests' `test_every_monitor_has_scrape_targets` xfails on this monitor until the fix is released;
tell podiumd-tests the version, so the xfail can go.
