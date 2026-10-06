# Research: QA environments

Analysed 2026-10-05, read-only. Sources:

- A: `~/development/werk/infonl-dimpact/icatt-menselijk-digitaal/podiumd-infra`
- B: `~/development/werk/infonl-dimpact/scctwente/ExternalsPodiumD`

## A) podiumd-infra (ICATT, Azure AKS)

- **What it is:** ICATT's throwaway and personal environments. They are built with Bicep, Azure CLI and GitHub Actions `workflow_dispatch` (`deploy-podiumd-helm.yml` → `scripts/deploy-podiumd-helm.sh`). The docs are `docs/test-environments.md`, `docs/deploying-a-new-environment.md` and `docs/infra-contract.md`.
- **Experimental:** Cyso EMK (Gardener) in `cyso/`.
- **Environments (`values/<env>/`):** anna00, bas00, felix00, james00, jim01, jim02, jimme00, johnb00, jos00, kees00, test00. The workflow list also names jim00, sytske00, stefan00, cicd, test01 and test02.
- **Chart version:** pinned with `chartVersion` in `values/<env>/infra.yaml`, e.g. kees00=4.9.0, johnb00=4.8.5, anna00/bas00=4.7.5.
- **Values layering:** `values/<env>/podiumd.yaml` plus `fixed-values.yaml`, `values/layer0/`, `values/layer1-bas00/`.
- **Hosts:** `https://<app>.<env>.pd.test-rig.nl`. The app names:
  - zac, openzaak, keycloak, keycloak-admin, contact (KISS), ita, pabc, abc (OAB), openarchiefbeheer, portaal and openinwoner (OI);
  - formulier and openformulieren (OF), openklant, objecten, objecttypen, notificaties and opennotificaties, omc, openbeheer, referentielijsten, besluiten, office-addin;
  - apisix-admin, grafana, plus mailpit (johnb00) and datamigratie (some).
- **Kubernetes:**
  - namespace `podiumd`
  - RG `rg-podiumd-<env>`
  - cluster `podiumd-<env>-aks`; the context comes from `az aks get-credentials`
  - Postgres `podiumd-<env>-pg.postgres.database.azure.com`
- **Components differ a lot per environment:**
  - zac is off on jim01/02.
  - kiss is only on felix00, jim01/02, jimme00, kees00, test00.
  - OAB is only on felix00, jimme00, test00.
  - OI is off on anna00, bas00, james00, johnb00, jos00.
  - zaakbrug is only on jimme00.
  - omc is on jim01/02, jimme00, kees00.
  - Ingress is apisix on some environments and Traefik on the others.
  - Keycloak comes from keycloak-operator, or the legacy keycloak/infinispan setup (felix00, jimme00, test00).
  - `fullnameOverride` for notificaties on johnb00.
- **Secrets:** Key Vault `podiumd-<env>-kv` in `rg-podiumd-base`. The test user password is `keycloak-user-<env>-password` (realm user `<env>`). The k8s secret `keycloak-podiumd-admin` is also available.
- **Security concern:** tokenauth tokens and ZGW secrets are committed in plaintext in `values/<env>/podiumd.yaml`. Also tracked in git:
  - `credentials.properties`, `oauth-role-mapping.properties`
  - `ispn.pfx`, `ispn.crt`, `server-cert-1.pem`
  - `cyso/emk-sa-kubeconfig.yaml`
  - `Notify/notify-secrets-*.yaml`, `Notify/NotifyEnvsSensitive.md`

  Do not copy this pattern.
- **Tests (`tests/`, pytest):** the AKS port of the minikube tests.
  - `TEST_ENV_NAME` sets the domain.
  - The namespace is hardcoded, and kubectl uses the current context.
  - Fixtures: `enabled_profiles` (pod prefixes) and `app_url()`.
  - Extra tests: `test_zac_zaakafhandelparameters.py` and `test_4_8_5_upgrade.py` (image pins, securityContext).
  - The `seed.sh` named in the README is missing.
- **Infra:** mailpit (johnb00), brp-personen-mock everywhere, monitoring values, CloudBeaver, a PABC init job.
- **Shutdown schedule:** scheduled workflows shut the clusters down, so an environment may be off.

## B) ExternalsPodiumD (SSC Twente, Azure AKS)

- **What it is:** the managed environments for each gemeente, deployed by Azure DevOps (`pipelines/application.yml`, HelmDeploy, namespace `podiumd`).
- **Environments (`applications/gemeenten/<g>/<stage>/`):** ontw-dim1, ontw-dim2, ontw-dim3, ontw-dimp, test-dimp, ontw-icat, ontw-info, ontw-mayk.
- **Chart version:** `config.yml` → `podiumd.chartversion`. dim1/dimp/icat/mayk/test-dimp = 4.9.1, info = 4.8.0, dim3 = 4.7.8, dim2 = 4.6.6.
- **Domains:**
  - dim1: `dev.dimpact.nl`
  - dim2: `dim2.dimpact.nl`
  - dim3: `dim3.dimpact.nl`
  - dimp: `dimpact.nl`
  - icat: `dimpact.icatt.nl`
  - info: `dimpact.info.nl`
  - mayk: `dimpact.opengem.nl`
- **Hosts:** `<stage>-<app>.<domain>`, e.g. `ontw-zac.dimpact.icatt.nl`.
  - The apps include zac, openzaak, keycloak, keycloak-admin, contact (KISS), ita, pabc, abc (OAB), mijn (OI), formulier, openklant, objecten, objecttypen, notificaties, omc, openbeheer, referentielijsten, office-addin, datamigratie and podiumd-logs (Grafana).
  - Routing uses Gateway API (NGF).
  - Grafana runs in namespace `monitoring`.
- **Infra names:**
  - kube context `aks-blue-<stage>-<g>`
  - Key Vault `kv-<stage>-<g>`
  - Postgres `psql-<stage>-<g>`
  - This is a different tenant and subscription from A.
- **Secrets:** the pipeline fills `REP_<NAME>_REP` placeholders from Key Vault. `/check-podiumd-secrets` enforces that the values files contain no literals.
- **Concern:** `smoke-tests/env-templates/*.env` commit the test-identity passwords.
- **Tests (`smoke-tests/`, Playwright TS):** the same smoke specs as testautomation (00, 01, 04/05/82/99, 06/113, 66, 72, 79, 81, 92, 155).
  - Environment selection: `PODIUMD_ENV` → `.env.<env>`, generated from `env-templates/<env>.env` by `scripts/generate-env.sh`.
  - The template holds per-component base URLs plus `PODIUMD_KUBECTL_CONTEXT`, `PODIUMD_KV_NAME`, `PODIUMD_NAMESPACE` and fixtures (zaaktype `zaaktype-voor-e2e-testen`, catalogus `ALG`).
  - The script signs a ZGW JWT from OZ `JWTSecret` via `kubectl --context`, and reads the PABC `API_KEY__0` from the pod env.
  - `scripts/seed-identities.sh` and `unseed-identities.sh` manage the test identities.
  - Worth porting: `lib/urls.ts` and `lib/{zgw,kiss,ita,omc,pabc}-client.ts`.
- **Mocks:** brppersonenmock. There is no mail sink or webhook receiver.

## What the suite must handle

1. **Two incompatible host schemes, plus app aliases.** KISS is `contact`. OI is `portaal`/`openinwoner` in A and `mijn` in B. OAB is `abc`. Grafana is `grafana` or `podiumd-logs`. The fix is an explicit URL per component in each environment profile.
2. **Kube context and namespace come from config,** and every kubectl call passes `--context`. Monitoring can live in its own namespace.
3. **Secrets are read in the cluster first:** OZ `JWTSecret` through manage.py shell, pod env, k8s secrets. Key Vault is optional, because names and tenants differ per estate. Committed values files are never read.
4. **Detect components,** because they vary per environment. Also handle `fullnameOverride` names and the two Keycloak flavours.
5. **Ingress differs** (Traefik, APISIX, Gateway API NGF), so do not assert exact redirect status codes.
6. **Chart versions range from 4.6.6 to 4.9.x.**
7. **Pre-seeded fixtures differ per environment.** The suite must create its own.
8. **Clusters may be shut down,** so a preflight check gives a clear message.
