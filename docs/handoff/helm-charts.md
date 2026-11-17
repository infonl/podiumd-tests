# Handoff to helm-charts

Open items for the helm-charts session. Delete an item when it is done; delete the file when nothing is open.

## Known issues to fix in PodiumD 4.11.0 (Kees, 2026-11-17)

Kees wants one PR per item into `feature/podiumd-4.11.0`, unless items are related and belong together. Full text of
each issue: infonl/podiumd-known-issues `issues/<id>-*.md` and `security-review/podiumd-4.10.0.md`. Values line
numbers are from `origin/feature/podiumd-4.11.0` (adf68891). Please name the issue id in each PR, and tell
podiumd-tests the PR numbers so the known issues can point to them.

### Changes to #719 itself (ZAC 5.12.0)

1. zac-42 (Critical): the 4.10.1-to-4.11.0 upgrade guide does not mention it. Add the step: before the upgrade, export
   each zaaktype configuration's niet-ontvankelijk resultaattype and zaakbeeindig resultaten; after it, enter them
   again (ZAC 5.10 migrations V103-V105 drop them without backfill).
2. podiumd-chart-39: the office converter values comment and the upgrade guide (lines 190-191) still say "not yet
   measured on Gotenberg 9". Measured on minikube with #719 b9567fff: 1,665 MiB peak for a Word file with 40 photos,
   within the 2Gi limit.
3. podiumd-chart-43 (also PR 1 below): #719 rewrites the PABC prefill comment to "the roles ZAC 5.12.0 checks" but the
   list lacks `zaakspecifiek_geautoriseerd`. Either fix it in #719 or in PR 1, not both.

### One PR each

| PR | Issue | Sev | Change |
| --- | --- | --- | --- |
| 1 | podiumd-chart-43 | Medium | Add application role `zaakspecifiek_geautoriseerd` to `pabc.migrations.prefill.applications[zaakafhandelcomponent].roles` (values.yaml:4266) and to `files/pabc-dataset.json` (lines 12-45). Not `systeemrol_behandelaar_alle_zaaktypen`: ZAC 5.12 filters it out (PabcClient.kt:50-56). Upgrade note: prefill skips an existing application, so existing installs add the role once. |
| 2 | podiumd-chart-40 | Medium | `zac.office_converter.env.API_TIMEOUT` above Gotenberg's 30 s default (values.yaml:3642), kept below the edge timeout of about 60 s. Check that the env name still applies to Gotenberg 9.4.1. |
| 3 | zac-5 (partial) | High | REST client connect and read timeouts through `zac.extraEnv` (zac chart 1.0.385): `<CLIENT>_MP_REST_CONNECTTIMEOUT` / `_READTIMEOUT` for the ZGW, Klantinteracties, BRP, KVK, BAG, Objects and PABC clients. The read timeout must stay above Open Zaak upload and conversion times. |
| 4 | WH-02 (rest) | Medium | `openvtb.securityContext` (values.yaml:2940): `allowPrivilegeEscalation: false` and `seccompProfile: {type: RuntimeDefault}`; openvtb 0.2.0's config Job uses the same securityContext. |
| 5 | SD-10 (rest) | Medium | `openinwoner.eck-elasticsearch.image` (values.yaml:2490-2494): the full image with digest, `docker.elastic.co/elasticsearch/elasticsearch:9.2.0@sha256:...`. |
| 6 | NW-13 | Low | `templates/keycloak-podiumd-realm-config.yaml`: remove `http://localhost:8080/oauth2/callback` from the Frank!Gateway dashboard client (line 1062); put OpenBao's `http://localhost:8250/*` (line 791, for `bao login -method=oidc`) behind an opt-in value. |
| 7 | IA-06 | Low | Keycloak realms: drop `xXSSProtection` and the unused `offlineSessionMaxLifespan` 7776000 (keycloak-master-realm-config.yaml:19, 28-29; podiumd realm around line 104). |
| 8 | podiumd-chart-44 | Medium | Extend the commented Open Notificaties example (values.yaml about 1000-1075) with the abonnement on kanaal `autorisaties` (callback `<ON>/api/v1/callbacks`) and `notifications_subscriptions_config`, plus an upgrade-guide step; the values are per environment. |
| 9 | podiumd-chart-42 | Medium | `files/objecttypen/Productaanvraag-Dimpact.json` `$defs.betrokkene`: `anyOf` instead of `oneOf`, so a company with kvkNummer and vestigingsnummer is accepted. New installs only; existing estates need a new objecttype version. |
| 10 | WH-12 | Low | `sizeLimit` on the emptyDirs of PodiumD's own templates (Keycloak ensure and import Jobs, openbao-token-renewal, podiumd-adapter). |
| 11 | NW-16 | Low | api-proxy ConfigMap: `proxy_ssl_verify on` by default (the legacy api-proxy is disabled by default). |
| 12 | NW-18 | Low | Example URLs in values.yaml comments: `https://`. Docs only. |
| 13 | SD-09b | Low | Keycloak Jobs: pass credentials to curl with `-K <file on tmpfs>` instead of argv. |
| 14 | WH-08 | Medium | `automountServiceAccountToken: false` on PodiumD's own workloads that have no RBAC. |

Not in this round: NW-01, NW-02, NW-04, SD-02, SD-04, podiumd-chart-7, -8, -24 and WH-10 (scheduled for 4.11 by John,
none on the branch yet); omc-5, omc-8, open-zaak-1, -4, -16 and open-archiefbeheer-4 are fixed by #720 and #721.
