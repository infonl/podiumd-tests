# Research: podiumd-testautomation

Source: `~/development/werk/infonl-dimpact/icatt-menselijk-digitaal/podiumd-testautomation` (vendored from Dimpact `testscripts`). Analysed 2026-10-05, read-only. Most titles and comments are in Dutch.

## Layout and the per-version folders

- **Top level:**
  - `README.md`
  - `tools/test-secrets-map.sh` and `tools/seed-test-secrets.sh`: env var to Key Vault mapping.
  - `.github/workflows/{ci,seed,test-suite}.yml`
  - `podiumd-{4.8.2,4.8.4,4.8.5,4.8.6,4.9.0}/`, each with `test-automation/`, `test-seeding/`, `seed-test-data/` and `VERSION-NOTES.md`.
- **Convention:** copy the last triaged folder, record the chart deltas, fix what the release broke.
- **What actually differs between folders:**
  - **4.8.2 → 4.8.4:**
    - About 38 specs have tests commented out (`TEMPORARILY DISABLED`) because of env or kubectl-context errors.
    - CI gets `retries: 2`.
    - The env templates change.
    - The seed scripts are fixed for the OI `OIDCProvider/OIDCClient` model (migration 0098).
  - **4.8.4 → 4.8.5:** host fixes in the env templates, OAB made optional, spec 92 disabled.
  - **4.8.5 → 4.8.6:** README only (a Keycloak CVE patch).
  - **4.8.5 → 4.9.0:**
    - New clients: `lib/frankgateway-client.ts` and `lib/zac-client.ts`.
    - New specs: 192 FG health, 190 KISS contentbronnen, 191 ITA poller split, 193 ZAC→FG→OZ.
    - Spec 92 re-enabled.
- **Conclusion:** there are no API-version or fixture differences between folders. The version dependence is in four places:
  - env hosts and deployment profile;
  - Django models used in the seed scripts;
  - a few chart-feature specs;
  - ad-hoc disabled tests.
- **Chart deltas in VERSION-NOTES:**
  - 4.8.4: frankgateway replaces apiproxy/apisix, openbao added.
  - 4.8.5: ZAC 5.0.2, open-beheer 0.9.1, `enablePkce`, `extendWithZaaktype`.
  - 4.9.0: kiss-chart 3.0.0 (Open Crawler), ITA 3.3.0 (poller split), eck/clamav/redis-operator bumps.

## Tools

- Playwright TS (1.48, axe-core, jsonwebtoken).
- Pact (consumer and provider tests; CI does not run them).
- k6 (`tests/perf/`).
- Bash seeders.
- Python report and catalog scripts.
- A Node test launcher.

## Tiers (README table, `playwright.tiers.config.ts`)

| Tier | Proves | Size |
|---|---|---|
| smoke | Apps are up and login works | 14 files / 52 tests, ~2 min |
| interaction | Core user flows | 27 files / 56 tests |
| maintenance | Cleanup and admin specs; mutate data; not in `full` | separate |
| regression | The rest | 131 files / 344 tests |
| full | smoke + interaction + regression | 172 files / 452 tests |
| perf | API response times with p95 thresholds (k6) | `tests/perf/README.md` |

Other settings:

- `workers: 1`, sequential, shared state.
- About 130 legacy per-number projects in the base config.
- `tests/debug/` sits outside every tier.

## Seeding

**Regression seeding** (`test-seeding/scripts/seed-omgeving.sh`) has about 16 steps. Most run Django ORM through `kubectl exec deploy/<app> -- python manage.py shell`. Keycloak and OK2 are seeded over REST. The steps:

- `seed-minimal`: OZ Applicatie and JWTSecret, Catalogus TEST/000000000, zaaktype `TEST-FORMULIER` with IOT, status and resultaattypen, and 2 OK partijen.
- `seed-oz-autorisaties`: Applicaties open-formulieren, open-inwoner, zac and zgw-test.
- `seed-keycloak`: roles and users (kcc-medewerker, testadmin, testinwoner BSN 999990019, testinwoner2 999990038).
- `seed-digid-oidc-mock` and `seed-eherkenning-oidc-mock`: Keycloak acts as the IdP for OI.
- `seed-notificaties`: ON JWT secrets, Applicaties and 5 kanalen.
- `seed-oi-*`: bedrading, CMS pages, OK2, contactflow.
- `seed-ita-medewerker-actor`: an OK2 actor.
- `seed-of-formulier` and `seed-of-zgw-registration`.
- `seed-oab-*`: only when OAB is deployed.
- `seed-objecten-ita-keten`.
- `--with-oab-zaken`: destructive.

The seeding is idempotent (get_or_create, Keycloak 409 treated as OK). **There is no cleanup.**

**Volume seeder** (`seed-test-data/seed.sh --env X --scale smoke|perf <module>`):

- Driven by fixture YAML and a sci-fi name corpus.
- `assert.sh` checks counts.
- Partijen have no idempotency key.
- There is no cleanup: resetting means a redeploy.

## Tests (4.9.0: ~157 spec files, ~450 tests)

Almost every spec depends on the seed data. 72 files create zaken with `uniqueRunId()`, but only 6 delete them.

**Smoke:**

- 00 preflight (kubectl)
- 01 ZGW JWT on OZ catalogi
- 04/05/82/99 portaal homepage, DigiD, login config, eHerkenning (UI)
- 06 KISS BFF healthz
- 113 KISS login (UI)
- 155 eSuite SAML (UI)
- 66 PABC health
- 72 ITA kanalen
- 79 OMC health
- 81 continuity pings
- 92 Keycloak SSO (UI)
- 192 Frank!Gateway outway

**By component (I = interaction, R = regression):**

- **Open Zaak** (API): I02, I03, I10; R13/17/23 VA, R14/48 audit, R15/39 status, R22 negative JWT, R24, R28/56/59 relations, R29 besluit, R36 zaakobject, R38 concurrency, R41, R43 pagination, R44 validation, R49/51/64 documents, R50 `_zoek`, R52 geo, R55, R60 seed health, R63, R90, R122, R167/173 zaaktype CRUD.
- **Notifications** (API with the in-cluster webhook-receiver): R19, 25, 26, 27, 30, 33, 34, 37, 42, 45, 46, 53.
- **Open Klant 2** (API): I09, I35, I145; R18, 54, 58, 62, 85, 86, 87, 149, 157.
- **Open Inwoner portaal** (UI, DigiD mock): many I and R specs. R65 uses kubectl with a hardcoded `kind-podiumd` context.
- **Open Formulieren:** I32, I76; R11, 57, 75, 79, 80, 120, 150, 152, 153 (API, prefill and payment); R158, 159, 176, 178, 183, 185 (UI chain OF→OZ).
- **KISS:** R12, R100 (UI); R147, R190 (API).
- **ITA:** I74, 78, 148, 180, 181; R73, 75, 76, 77, 112, 184, 191. The cookie OIDC flow means a browser is needed even for API calls.
- **PABC:** R67–71.
- **OMC/NotifyNL:** R80, 81, 82, 115, 116, 154 (notifynl-mock `/__received`).
- **OAB:** I142, 168; R143, 166, 169, 170, 171, 174. These force state through the Django shell and have 90 s timeouts.
- **Keycloak/security:** R91 realm snapshot, R177 admin consoles not public.
- **External:** R07, R40 BRP; R08, R47, R125 KvK; R88, R151 PDOK.
- **eSuite:** R156.
- **Frank!Gateway/ZAC:** R193.
- **Continuity/chaos:** R89, 124, 144 (`PODIUMD_DESTRUCTIVE_TESTS=1`); R121; R175 Alertmanager; R119; R172 WCAG axe.
- **Maintenance:** `cleanup-test-zaken.spec.ts`.
- **Pact:** KISS→OK2/OZ, OF→catalogi, OI→zaken, ZAC→zaak-create; provider tests for OZ and OK2.

## Config

- **Selection:** `PODIUMD_ENV=<omg>` loads `.env.<omg>`.
- **Templates:** `.env.example` (KIND), `.env.omgeving.example`, and `env-templates/{jim00,jim01,jim02}.env` (AKS `*.<omg>.pd.test-rig.nl`).
- **URL variables:** `PODIUMD_*_BASE_URL`. A missing URL makes the spec skip (189 skip calls in total). This is the de facto capability gating.
- **Secrets:** 11 secrets in Azure Key Vault `podiumd-<omg>-kv`, mapped in `tools/test-secrets-map.sh`.
- **Seeding target:** context `podiumd-<omg>-aks-admin`, namespace `podiumd`.

## CI

All workflows are `workflow_dispatch` only, on GitHub-hosted runners.

- `test-suite.yml`: Azure OIDC login, AKS credentials, render `.env`, run the tier, JUnit and HTML artifacts.
- `seed.yml`: regression or volume seeding.
- `ci.yml`: actionlint, shellcheck, gitleaks, tsc baseline.

## Test infra (`test-seeding/`)

- **`webhook-receiver.yaml`:** a node:22 ON subscriber with an Ingress. The notification specs poll it.
- **`notifynl-mock.yaml`:** a node:20 GovUkNotify stand-in with `GET/DELETE /__received`.
- **Alertmanager route** for spec 175, and the OAB PVC.
- **Hetzner-only leftovers:** redis, tls-ingresses, letsencrypt.

## Notable points

- **Flakiness:** CI uses `retries: 2`. There are 21 `waitForTimeout` calls and 38 files with `TEMPORARILY DISABLED` blocks.
- **Dependencies:** specs depend on each other (the OAB chains). Preconditions often go through kubectl and the Django shell.
- **Known gaps:** the KISS search indices are empty (Objecten token mismatch), and the crawler, PKCE and `extendWithZaaktype` are untested.
- **Perf:** k6 read-only checks with p95 < 1500 ms on OZ zaken/zaaktypen, OK2 partijen and BRP. `fg-compare.js` compares the Frank!Gateway path.
- **Mapping:** `test-catalog/` maps 546 draaiboek (4.6) test cases to specs (`coverage.md`). Use it for deduplication.
