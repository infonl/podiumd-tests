# Research: podiumd-minikube tests

Source: `~/development/werk/infonl-dimpact/infonl/podiumd-minikube`. Analysed 2026-10-05, read-only. Paths are relative to that repo.

## Purpose and layout

- **What it is:** a Helm chart that rebuilds the `dimpact-zaakafhandelcomponent` docker-compose dev stack on minikube, on top of the published `podiumd` umbrella chart.
  - Plain Deployments and a Traefik ingress on `*.local` hosts replace the production infra (Keycloak Operator, Redis HA, APISIX, cert-manager).
  - The scope is ZAC plus its ZGW dependencies. It is not a full PodiumD install.
- **Chart files:** `Chart.yaml`, `values.yaml` (130 KB, heavily commented), `templates/`, `charts/` (vendored podiumd and monitoring-logging tgz).
- **`vendor/dimpact-zaakafhandelcomponent/`:** realm JSON, WireMock mappings, SQL fixtures and seed scripts. `NOTES.md` records where each came from.
- **`scripts/`:** cluster lifecycle and deploy tooling (bash, plus Python post-renderers in `scripts/lib/`).
- **`tests/`:** a flat pytest directory, the only test suite.
- **No CI, Makefile or justfile.**
- **Moved out:** the AKS tests (`tests-johnb00/`, including `test_4_8_5_upgrade.py` and `test_zac_zaakafhandelparameters.py`) now live in podiumd-infra `tests/`, selected with `TEST_ENV_NAME`.

## Test inventory (`tests/`)

All tests are API tests unless marked UI. All are read-only unless noted.

| File | Components | Verifies | Seeding | Cleanup |
|---|---|---|---|---|
| `test_pods.py` | all | Every pod is Running or Succeeded and every non-Job container is Ready. 14 core pods are present. Uses a hardcoded `ONE_SHOT_JOB_PREFIXES` list. | none | n/a |
| `test_reachability.py` | ZAC, Keycloak, OZ, OK, PABC, Solr, Objecten, Objecttypen, ON, OAB, OF, Grafana, Mailpit | Each ingress host returns a hardcoded status code, and is skipped when its profile is off. | none | n/a |
| `test_login_flow.py` | ZAC, Keycloak, PABC | Full OIDC code flow with `requests.Session`, ending with the `<zac-root>` shell. | realm user `beheerder1newiam` | n/a |
| `test_browser.py` (UI) | ZAC, Keycloak | Playwright login, then the dashboard labels are shown. | same user | n/a |
| `test_pkce.py` | Keycloak, PABC, ZAC, Django clients, ITA, KISS | PABC sends `code_challenge`. ZAC PKCE is checked only when it is enabled. The Django, ITA and KISS clients do not require PKCE (checked through the Admin API). | realm | n/a |
| `test_django_admin_login.py` | OZ, OK, Objecten, Objecttypen, ON, OF, OAB | Django admin login (admin/admin) through the two-factor wizard form. | superuser | n/a |
| `test_database.py` | Postgres, OZ | The databases exist, PostGIS is installed, and the `zac_client` app and JWT secret are seeded. Uses `kubectl exec psql`. | SQL fixtures | n/a |
| `test_zgw_service_reachability.py` | Objecten, ON, OAB, OF | Every `zgw_consumers.Service.api_root` is reachable from inside the app's pod (`kubectl exec`). | config Jobs | n/a |
| `test_mailpit.py` (API and UI) | OZ, Mailpit | Sends mail with a UUID subject through `kubectl exec`, then finds it through the Mailpit API and UI. | creates its own | **none** |
| `test_metrics.py` | Grafana, Prometheus, Tempo | The datasources are present and the scrape targets are up. | none | n/a |
| `test_monitoring_logging.py` | Grafana, Prometheus, Loki, Tempo | The same checks, plus Loki holds this namespace's logs. | none | n/a |
| `test_pabc_migrations_guard.py` | PABC, Postgres | The PABC migration script refuses to recreate the destructive Job. **Changes cluster state:** it deletes the Job and restores it in a `finally` block. | seeded PABC | restores |
| `test_productaanvraag_flow.py` (E2E) | Objecten, Objecttypen, ON, ZAC, OZ, OF, Keycloak | Seed state and ZAC zaakafhandelparameters are in place. The full flow POSTs an object, then polls OZ for up to 60 s for a zaak with a matching `kenmerk`. | `--full` deploy | **none** |

**Not covered:** KISS, ITA, Open Inwoner, Open Beheer, ClamAV, Zaakbrug and Referentielijsten are disabled in `values.yaml` and have no functional tests.

## Seeding (all at deploy time, none in pytest)

- **Postgres:** initdb SQL plus background loops that run `fixtures/{openzaak,openklant,openarchiefbeheer}/*.sql`.
- **Keycloak:** the vendored realm JSON is imported on startup (about 16 test users plus clients). PKCE is kept in step by `scripts/lib/fixup-zac-pkce-realm.py` and `sync-zac-pkce-realm.sh`.
- **Django superusers:** create-superuser Jobs for some apps, chart env vars for the others.
- **Subchart `setup_configuration` Jobs:** objecten, objecttypen, opennotificaties, openformulieren.
- **Custom Jobs:**
  - ZAC productaanvraag zaakafhandelparameters: Keycloak password-grant token, then GET-then-PUT.
  - The Open Formulieren productaanvraag form, created through `manage.py shell`.
- **`scripts/lib/seed-fixtures.sh`:** `kubectl cp` plus `loaddata` of objecten/objecttypen demodata.
- **PABC:** a guarded migration Job.
- **Stubs:** WireMock for BAG, KvK, BRP and SmartDocuments.

## Framework and config

- **Dependencies:** `tests/requirements.txt` has pytest>=8, requests and pytest-playwright. `pytest.ini` sets `-ra`. There are no markers.
- **`conftest.py`:**
  - Hardcodes the namespace `podiumd-minikube`.
  - Provides a `kubectl()` wrapper.
  - The `traefik_ip` fixture skips the whole suite when the IP is missing.
  - The `pods` fixture and the `enabled_profiles` fixture (based on pod-name prefixes).
  - `host_url()` and `host_headers()` call `http://<ip>` with a `Host:` header, so no hosts-file edit is needed.
  - Chromium `--host-resolver-rules` for the browser tests.
- **Credentials:** hardcoded dev defaults (admin/admin, client secrets, tokens). No k8s secrets are read.

## Version selection

- **Pinning:** the gitignored `.podiumd-versions.yaml`, set with `scripts/set-podiumd-version.sh`. `scripts/lib/podiumd-dependency.sh` syncs `charts/*.tgz`. There is one `values.yaml`.
- **Runtime detection:** objecten classic vs merged "openobject" layout (`detect-objecten-shape.sh`), and ZAC PKCE gated on the chart version.
- **In the tests:** detected at runtime. Objecttypen tests skip on the merged layout, productaanvraag picks host and token by layout, and the ZAC PKCE test skips unless the experiment is on.

## Worth keeping

- Detecting profiles and capabilities from what is deployed, then skipping.
- The Traefik IP plus `Host` header mode, and Playwright host-resolver rules.
- Helpers: `_zgw_jwt()`, `_beheerder_token()`, `_keycloak_admin_token()`, the Django two-factor admin `_login()`, `_extract_form_action()`.
- Polling with a deadline, and Playwright `expect()`.
- Unique UUID markers per run.
- Asserting on real effects rather than Job exit codes.

## Weaknesses

- Tied to minikube: the namespace, hosts, service names and secrets are hardcoded.
- Not self-contained: seeding happens at deploy time.
- No cleanup, and one destructive test.
- Helpers duplicated across files.
- No markers or CI.
- Brittle hardcoded expectations (status codes, datasource sets, English labels).
- Heavy use of `kubectl exec`.
