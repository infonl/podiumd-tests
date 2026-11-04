# Open requests for podiumd-infra

## ClamAV on kees00, as ExternalsPodiumD (Kees, 2026-11-04)

kees00 runs no ClamAV: `helm_deploy.py:422` sets `clamav.enabled=false` unless the deploy gets `--clamav`, although
`values/kees00/podiumd.yaml:92` sets `clamav.enabled: true`. Open Formulieren on kees00 has `enable_virus_scan=False`.
ExternalsPodiumD sets no `clamav.enabled`; the chart counts a missing key as on (`podiumd.clamav.enabled` in
`_helpers.tpl`), so it runs ClamAV, and the chart's configure-clamav Jobs turn on Open Formulieren's virus scan.
minikube runs it too (`clamav-0`, `enable_virus_scan=True`, host `clamav:3310`).

Request: deploy kees00 with ClamAV, so the values file decides (`--clamav` by default for kees00, or no
`clamav.enabled` override in section 2).

Verify: StatefulSet `clamav` ready; Open Formulieren `GlobalConfiguration.enable_virus_scan` is true with
`clamav_host` `clamav`; then `podiumd-tests run --env kees00 --tier core`.
