# External test sources outside GitHub

Researched 2026-11-13, read-only. Scope: public test suites, test data, compliance tools and test descriptions for
PodiumD's components and the Common Ground / ZGW ecosystem that are **not** github.com repositories. Checked against
`docs/research/external-test-sources-plan.md` (OneGround and VNG Postman, Nijmegen Open Forms, gemma-zaken-test-integratie,
dmf k6, podiumd-adapter) and `docs/research/upstream-tests.md` (components' own repositories); nothing listed there is
repeated. Every URL below was fetched during the research; "verify" marks a fact that was not confirmed.

## Top 5 recommendations

1. **OMC documentation (GitBook): scenario rules and `/Test/*` endpoints.** Gives the trigger and stop conditions of the
   three OMC scenarios podiumd-tests does not test (Taak toegewezen, Besluit genomen, Bericht ontvangen) plus the
   skip rules (informeren false, zaaktype not whitelisted, taak not `open`, document not `openbaar`/`definitief`,
   unknown event answered 200). The negative cases run on minikube as configured; the positive ones need a whitelist
   change, which podiumd-minikube owns. Its `/Test/OMC/Configuration`, `/Test/ZGW/Endpoints` and
   `/Test/Notify/HealthCheck` give a doctor/smoke check.
2. **RvIG BRP test set (persoonslijsten proefomgeving, 1,035 persons, release 2026-11-01).** podiumd-tests already uses
   three of these persons (EREBOS, KIERKEGAARD, KLAMER) but none of the edge cases: geheimhouding, overleden,
   emigratie, RNI, curatele, opschorting with reason O/E/R/F, in onderzoek, gezag. Use it as data to parametrize the
   BRP, ZAC, KISS and Open Formulieren prefill tests.
3. **Dimpact/objecttypes on Codeberg (CC0): canonical Productaanvraag-Dimpact schema.** Allows a drift test between
   the deployed objecttype and Dimpact's published schema. It also shows that the `oneOf` overlap behind
   `podiumd-chart-42` is in Dimpact's own schema too, a fact for the known-issue write-up.
4. **ADR validator (Geonovum, gitlab.com) and its `security-tls` ruleset.** Run against live API URLs, it checks the
   NCSC TLS versions and cipher suites and the `API-Version` header. podiumd-tests checks neither
   (`test_web_security.py` covers headers, cookies, CORS and certificate validity).
5. **FSC test suite (gitlab.com/commonground/standards/fsc).** 75 Gherkin scenarios for Inway, Outway, Manager and
   integration. About 10 Inway and Outway cases port to Frank!Gateway: a missing or expired access token, a
   certificate that is not trusted or does not match its token, and the TransactionID preserved or required.
   `test_inway_consumers.py` only checks the consumer allow-list. Check first whether Frank!Gateway claims FSC
   conformance.

## Ranked findings

### 1. OMC documentation: scenarios and test endpoints (high)

| | |
| --- | --- |
| URL | <https://omc-notify.gitbook.io/omc-notify-docs/werkwijzen/overzicht> (scenarios), <https://omc-notify.gitbook.io/omc-notify-docs/api-referentie/endpoints> (test endpoints), <https://omc-notify.gitbook.io/omc-notify-docs/aan-de-slag/uitrollen/stap-3-uitrollen-en-testen> ; index: `/omc-notify-docs/sitemap.md` (append `.md` to any page for Markdown) |
| Host | GitBook (Worth-NL's OMC docs) |
| Licence | not stated |
| Component | OMC (NotifyNL), Open Notificaties, Open Zaak, Objecten, Open Klant, Open VTB |
| Kind | specification of acceptance behaviour (trigger conditions per scenario), health-check endpoints |
| Size | 6 scenarios (zaak aangemaakt, gewijzigd, afgesloten; taak toegewezen; besluit genomen; bericht ontvangen), 5 `/Test/*` endpoints, address-selection rules (e-mail, sms, letter via PostGuard) |
| Last activity | changelog top entry v2.0.0 (.NET 10, workflow v2 default, KvK support); page dates not shown |

Port value:

- Gap: `tests/integration/test_omc.py` covers zaak create, update, close, sms and the delivery receipt. Not covered:
  - Taak toegewezen: Objecten `object create` of the taak objecttype. Stop conditions: status not `open`;
    identificatie type not bsn/kvk; zaaktype `informeren` false; zaaktype not in `ZGW_WHITELIST_TASKASSIGNED_IDS`.
  - Besluit genomen: stop conditions: informatieobjecttype not in the configured list; document not `definitief`;
    document not `openbaar`; `informeren` false; zaaktype not whitelisted.
  - Bericht ontvangen: Open VTB `berichten`, only when `ZGW_WHITELIST_MESSAGE_ALLOWED`.
  - Statustype `informeren` false on a zaak status: no mail.
  - An event without a matching scenario: 200 and no mail.
- On minikube (`podiumd-minikube/values.yaml`), `taskAssigned` and `decisionMade` whitelist `niet-bestaande-id` and
  `message.allowed` is false, as on ExternalsPodiumD. As configured, only the "not whitelisted, so no mail" cases
  run. The positive cases need those whitelists changed, and podiumd-minikube owns that configuration: put the request
  in `docs/handoff/podiumd-minikube.md`.
- Smoke/doctor: `POST /Test/OMC/Configuration` (empty list when the configuration is valid), `POST /Test/ZGW/Endpoints`
  (status per ZGW endpoint), `GET /Test/Notify/HealthCheck` (`{"status": "healthy"}`), with the OMC JWT the suite
  already builds (`test_omc_version_answers_to_its_token`). Skip `/Test/Notify/SendEmail` and `/SendSms`, or call
  them only where the capability is `mailpit` and NotifyNL is the mock server.
- Verify first: the docs describe OMC v2.0.0. `docs/handoff/notices/podiumd-testautomation.md` notes OMC 1.17.19, so
  check that the deployed version has the `/Test/*` routes and the same workflow-v2 rules.

How to run: port to pytest (`tests/integration/test_omc.py`, the `mailpit` fixtures, `wait_until`). No code to copy;
the docs are rule descriptions.

### 2. RvIG test set persoonslijsten proefomgeving BRP-V (high)

| | |
| --- | --- |
| URL | <https://www.rvig.nl/testsetpersoonslijstenproefomgevingBRPV> ; file <https://www.rvig.nl/sites/default/files/2026-11/20261101_Testset_persoonslijsten_proefomgeving_BRPV.ods> (1.35 MB, Last-Modified 2026-11-03) |
| Host | rvig.nl |
| Licence | not stated (government publication) |
| Component | Haal Centraal BRP (api-proxy, Frank!Gateway outway), and every consumer: ZAC, KISS, Open Formulieren prefill, Open Inwoner, OMC |
| Kind | test data set with a one-line description per person (sheet `inhoud_PL`), full persoonslijsten (sheet `persoonslijsten`), change log (`versiebeheer`) |
| Size | 1,035 persons. Keyword counts in the descriptions: gezag 255, overleden 108, nationaliteit 90, RNI 76, in onderzoek 65, emigratie 40, curatele 26, verblijfstitel 26, briefadres 13, geheim 9. Opschorting: O 62, E 55, R 21, F 3, M 1 |
| Last activity | release 2026-11-01 |

The BRP API Personen mock (https://developer.rvig.nl/brp-api/lokaal-testen/) serves this same set by default.
`basisregistraties.py` already uses EREBOS 999990019, KIERKEGAARD 999990020 and KLAMER 999991723, and all three are in
it.

Port value: only "found", "unknown" and "invalid" BSNs are tested now. Edge persons from the set:

| Case | BSN (Lg01 id) | What to test |
| --- | --- | --- |
| geheimhouding | 999993458 (Lg01_296), 999992934, 999991206, 999991188 | `geheimhoudingPersoonsgegevens` in the BRP answer; ZAC/KISS person view shows the indicator; OF prefill still works |
| overleden (opschorting O) | 999999692 (Lg01_106), 999991760 | `opschortingBijhouding.reden` O, `overlijden` present; ZAC initiator and KISS search show the person as deceased |
| emigratie (E) | 999993896 (Lg01_276) | no Dutch verblijfplaats; KISS and ZAC address display |
| RNI (R) | 999993884 (Lg01_281) | RNI person found, address abroad |
| curatele | 999999709 (Lg01_107), 999991061 | `indicatieCurateleRegister` |
| in onderzoek | 999970422 (Lg01_138) | `inOnderzoek` fields passed through |
| gezag | 999998778 family (Lg01_001 to _003) | `gezag` for minors (BRP API's gezag information product) |

Verify first, per environment, that the BRP behind the api-proxy serves these persons: the mock on minikube. On kees00
and other estates the outway may route to the RvIG proefomgeving.

How to run: use as data. Parametrize `tests/component/basisregistraties/test_brp.py` and the ZAC and KISS person
tests with named constants in `basisregistraties.py`. Copy only BSNs, not the file.

### 3. Dimpact/objecttypes: Productaanvraag-Dimpact schema (high, small)

| | |
| --- | --- |
| URL | <https://codeberg.org/Dimpact/objecttypes> (mirror: <https://code.overheid.nl/Dimpact/objecttypes>); schema <https://codeberg.org/Dimpact/objecttypes/raw/branch/main/Productaanvraag/productaanvraag-dimpact.json> |
| Host | codeberg.org (Dimpact organisation) |
| Licence | CC0 1.0 |
| Component | Objecttypen, Objecten, Open Formulieren (objects registration), ZAC (productaanvraag intake) |
| Kind | reference data (JSON Schema, `$id` `https://open-objecten.org/schemas/productaanvraag`, README "Versie: .9") |
| Size | 1 schema, 11 top-level properties |
| Last activity | 2026-07-09 |

Port value:

- A drift test: the deployed `Productaanvraag-Dimpact` objecttype version's `jsonSchema` equals Dimpact's published
  schema. A chart or bootstrap that ships another copy then fails loudly.
- `$defs.betrokkene.oneOf` has 12 branches, each one identifier plus `rolOmschrijvingGeneriek` or
  `roltypeOmschrijving`. A betrokkene with both `kvkNummer` and `vestigingsNummer` matches two branches, so `oneOf`
  refuses it. That is the defect of the xfail `podiumd-chart-42` in `test_productaanvraag.py`, and it is in Dimpact's
  canonical schema too. Record that in the podiumd-known-issues write-up: a fix in the chart alone would drift from
  Dimpact's schema.
- Schema-driven valid and invalid productaanvraag cases for `make_productaanvraag`.

How to run: use as data (fetch at test time, or vendor it: CC0 allows copying).

### 4. ADR validator (core and security-tls rulesets) and DON checker (medium)

| | |
| --- | --- |
| URL | <https://gitlab.com/commonground/don/adr-validator> ; DON checker <https://www.npmjs.com/package/@developer-overheid-nl/don-checker> ; background <https://developer.overheid.nl/kennisbank/apis/api-design-rules/api-design-rules-linter> |
| Host | gitlab.com (Geonovum / Developer Overheid), npm |
| Licence | EUPL-1.2 (both) |
| Component | every REST API: Open Zaak, Open Notificaties, Open Klant, Objecten, Objecttypen, Referentielijsten, Open VTB, PABC; TLS of the ingress |
| Kind | compliance validator. The ADR validator calls a live API URL; the DON checker lints an OAS file |
| Size | ADR validator `core` (ADR 1.0: API-03, API-16, API-20, API-48, API-Version header), `core-v2`, `security-tls` (TLS versions, cipher suites per NCSC 2.1); DON checker: ADR 2.0.2, 2.1.0, 2.2.0, werkversie, publiccode 0.5/0.7 |
| Last activity | ADR validator code 2025-04, licence 2026-05-31; developer.overheid.nl marks it "verouderd". DON checker 1.4.0, 2026-10-29 |

Port value:

- Gap: podiumd-tests checks certificate validity, security headers, cookies and CORS (`test_web_security.py`), but not
  the TLS protocol versions and cipher suites the NCSC guidelines require. The `security-tls` rules are a short list,
  to reimplement with Python's `ssl` per ingress host.
- `API-Version` header (ADR API-57) on the ZGW APIs: one parametrized smoke test over `COMPONENTS`.
- The DON checker on each component's published OAS mostly reports upstream design issues, not environment faults.
  Run it once per release as an external tool; it is not a pytest test.

How to run: as an external tool against an environment (Docker image `registry.gitlab.com/commonground/don/adr-validator`),
or reimplement the TLS rules in Python. Copying the code needs an EUPL-compatible licence (see the licence notes in
`external-test-sources-plan.md`).

### 5. FSC test suite (medium, conditional)

| | |
| --- | --- |
| URL | <https://gitlab.com/commonground/standards/fsc/-/tree/master/test-suite> (`inway.md`, `outway.md`, `manager.md`, `integration.md`) |
| Host | gitlab.com (Common Ground standards) |
| Licence | EUPL-1.2 |
| Component | Frank!Gateway inway and outway (FSC/NLX successor) |
| Kind | Gherkin acceptance scenarios for FSC Core, Logging and Delegation |
| Size | Inway 13, Outway 8, Manager about 48, Integration 6 |
| Last activity | test-suite last changed 2024-05-03; project 2026-05-31 |

Port value:

- Inway cases that apply to any mTLS and token gateway:
  - Inway-Incoming-Request-2: no access token.
  - Inway-Incoming-Request-3: token bound to a different certificate.
  - Inway-Incoming-Request-4: untrusted certificate.
  - Inway-Incoming-Request-6: expired token.
  - Inway-TransactionLog-2 and -3: TransactionID preserved, or refused when missing.
  - Inway-Port-1: port 443 or 8443.
- Outway cases: no contract means no proxying (Outway-IncomingRequest-2); a failing inway (Outway-IncomingRequest-3).
- `test_inway_consumers.py` covers the consumer certificate allow-list. Before porting, check whether Frank!Gateway
  implements FSC contracts and access tokens; if not, only the certificate and port cases apply.
- The Manager cases (contracts, grants, signatures) need an FSC Manager, which PodiumD does not deploy.
- Checked 2026-11-13: Frank!Gateway 1.2.1, which PodiumD deploys, ships an FSC Inway plugin (`fsc`, in
  `wearefrank/frank-gateway` `src/apisix/plugins/fsc.lua`): it checks an `Fsc-Authorization` token bound to the
  certificate's SHA-256 thumbprint and requires `Fsc-Transaction-Id`. The podiumd chart configures no route with
  it and no FSC Manager or group; the inway admits consumers by client certificate in OpenBao
  (`openbao-consumer-auth`). So the token, TransactionID, TransactionLog and Outway cases do not apply.
- Ported: Inway-Incoming-Request-4 is the `untrusted-certificate` case; a request without a client certificate is
  the `no-certificate` case of `test_inway_admits_only_the_allowed_consumer`; Inway-Port-1 is
  `test_inway_url_uses_an_fsc_port`. Port the token and TransactionID cases once an estate routes through `fsc`.

How to run: port selected cases to pytest (`tests/component/frankgateway/`, `inway.py`).

### 6. Open Zaak post-install checklist: `/view-config/` and `send_test_notification` (medium)

| | |
| --- | --- |
| URL | <https://open-zaak.readthedocs.io/en/latest/installation/post_install.html> ; Postman "OpenZaak post install check" <https://documenter.getpostman.com/view/7083537/SWT8gKYU?version=latest> |
| Host | readthedocs.io, Postman documenter |
| Licence | EUPL (Open Zaak docs) |
| Component | Open Zaak; the same `/view-config/` page exists in the other Maykin apps (verify per app) |
| Kind | post-install acceptance checks |
| Size | 3 checks; the Postman collection has 9 requests (catalogus, procestype, zaaktype create and publish, zaak create, list, delete), all already covered |
| Last activity | docs for 1.29.x (2026) |

Port value:

- `/view-config/` lists configuration problems (site domain, notifications, external services). No podiumd-tests test
  reads it (grep: none). Add it to `tests/component/platform/test_django_apps.py` for `DJANGO_APPS` behind
  `superuser_login`. It overlaps with `test_zgw_services_authenticate` only partly.
- `manage.py send_test_notification`, run through `Kube.exec`, checks Open Zaak to Open Notificaties delivery from
  inside the pod. It needs a kanaal `test`; bootstrap may add Open Notificaties kanalen. Low extra value beyond
  `test_notificaties.py`.

How to run: port to pytest.

### 7. Haven Compliancy Checker (medium, AKS estates only)

| | |
| --- | --- |
| URL | <https://gitlab.com/commonground/haven/haven> (CLI in `haven/cli/pkg/compliancy`); Homebrew tap <https://gitlab.com/commonground/haven/homebrew-haven> |
| Host | gitlab.com (VNG Realisatie) |
| Licence | EUPL (`LICENCE.md`, © VNG Realisatie 2019-2026) |
| Component | the Kubernetes platform under PodiumD |
| Kind | compliance validator (`haven check`) |
| Size | about 20 checks:; - infra: multi-master, multi-worker, multi-AZ, private topology, secured nodes; - cluster: version, RBAC, RWX volumes; - deployment: log aggregation, metrics-server, HTTPS certificates; - external: CNCF conformance (sonobuoy); - suggestions: kubescape, kube-bench (CIS) |
| Last activity | release v12.14.0 on 2026-10-26; compliancy code changed 2026-11-09 |

Port value:

- Gap: `tests/smoke/test_cluster.py` checks workloads, pods, Pod Security Standards, image pinning, resources and
  disruption budgets. It does not check multi-AZ, a private node topology, RWX storage, log aggregation or the CIS
  baseline, which municipalities ask for under Haven.
- Not for minikube.
- The volumes check creates a PVC, and the CNCF and kubescape checks run Jobs with cluster-admin. These are
  disruptive on a shared cluster, so take the lock or run only on kees00 with Kees's go.

How to run: as an external tool against an environment, with `--output json` read into the results sink (verify the
flag); not a pytest port.

### 8. OpenID Foundation conformance suite (medium-low)

| | |
| --- | --- |
| URL | <https://gitlab.com/openid/conformance-suite> ; OP test instructions <https://openid.net/certification/connect_op_testing/> |
| Host | gitlab.com (OpenID Foundation) |
| Licence | MIT |
| Component | Keycloak (the podiumd realm as OpenID Provider) |
| Kind | compliance suite |
| Size | OP plans: Basic, Implicit, Hybrid, Config, Dynamic, Form Post, Logout, third-party-initiated login |
| Last activity | 2026-11-13 |

Port value:

- The Config plan checks the discovery document; the Basic plan checks registered redirect URIs, code reuse, nonce
  and client binding of codes. Keycloak itself is certified, so the value lies in the realm and client configuration.
  Partly covered by `test_oidc.py`, `test_pkce.py` and `test_realm.py`.
- Needs two or three static clients with the suite's redirect URI: podiumd-tests-owned bootstrap clients (`ptest-*`).
- For an environment that is not public, run the suite locally in Docker; the hosted site needs a public OP (verify
  the local setup in the suite's wiki).

How to run: as an external tool, or pick the few configuration-dependent cases (redirect URI must match exactly, a
code works once) as pytest tests.

### 9. KvK test environment data (low-medium)

| | |
| --- | --- |
| URL | <https://developers.kvk.nl/documentation/testing> |
| Host | developers.kvk.nl |
| Licence | not stated |
| Component | KvK through the api-proxy and outway; KISS company search, ZAC bedrijf initiator, Open Formulieren eHerkenning prefill |
| Kind | test data set |
| Size | 19 KvK numbers by legal form, including 2 error cases (90004973, 90002903); 19 vestigingsnummers by legal form |
| Last activity | not shown |

Port value: `basisregistraties.py` uses Test BV Donald (68750110) and one VOF vestiging. Parametrize
`test_kvk.py::test_basisprofiel` over legal forms (eenmanszaak 69599084, stichting 69599068, VOF 69599076,
coöperatie 55344526) and add the error numbers. Do apps show a KvK error without a 500? (ZAC `test_zac_bedrijven.py`,
KISS company search.)

How to run: use as data.

### 10. RvIG BRP API documentation: information products and the BRP mock (low-medium)

| | |
| --- | --- |
| URL | <https://developer.rvig.nl/brp-api/overview/> ; features e.g. <https://developer.rvig.nl/brp-api/personen/features/volledige-naam/> ; mock <https://developer.rvig.nl/brp-api/lokaal-testen/> |
| Host | developer.rvig.nl |
| Licence | not stated |
| Component | Haal Centraal BRP Personen |
| Kind | Gherkin specifications (Dutch) of derived fields: volledigeNaam, voorletters, leeftijd, adressering (aanhef, aanschrijfwijze, adresregels, gebruikInLopendeTekst), gezag; `fields` filtering |
| Size | about 8 information-product feature pages (scenario count not counted) |
| Last activity | not shown |

Port value: the features use synthetic BSNs (000000395) from RvIG's own test harness, so they do not run against the
mock as-is. Their rules tell which derived fields a consumer may expect: a contract check through the api-proxy that
`adressering` and `leeftijd` come back for test-set persons, and are absent where the rules say so (overleden, geheim).
Combine with finding 2.

How to run: port selected rules to pytest, with test-set persons.

### 11. Keycloak SAML DigiD/eHerkenning provider (RWS): cancel scenario (low-medium)

| | |
| --- | --- |
| URL | <https://code.overheid.nl/RWS/keycloak-saml-identiteitsaanbieders> |
| Host | code.overheid.nl (Forgejo) |
| Licence | not stated (verify) |
| Component | Keycloak DigiD/eHerkenning login; Open Inwoner, Open Formulieren |
| Kind | Java unit tests with sample SAML responses (`valid_response.xml`, `cancel_response.xml`, `unknown_response.xml`) |
| Size | 10 test classes |
| Last activity | 2026-09-22 |

Port value: no code ports. It names a scenario podiumd-tests lacks: the inwoner cancels at DigiD (or eHerkenning).
The portal or form then shows its "login cancelled" message and creates no session or account. With podiumd-minikube's
OIDC mock this is an `error=access_denied` callback. Target `test_portaal_login.py` and `test_formulier_login.py`.

How to run: port the scenario to pytest (Playwright).

### 12. StUF Testplatform compliance reports for ZDS 1.2 (low-medium)

| | |
| --- | --- |
| URL | Zaaksysteem role: <https://www.softwarecatalogus.nl/sites/default/files/20190501-Zaaksysteem-1346395-testrapportage.pdf> ; DMS consumer role: <https://www.softwarecatalogus.nl/sites/default/files/20170102%20-%20Zaak%20Document%20services%201.2.pdf> |
| Host | softwarecatalogus.nl (VNG) |
| Licence | not stated |
| Component | ZaakBrug (ZDS 1.2) |
| Kind | compliance test reports, with the exchanged StUF-ZKN 3.10 XML messages in Bijlage 1 |
| Size | Zaaksysteem role: 5 scenarios, 94 pages. DMS role: 7 scenarios, 31 pages |
| Last activity | 2017 to 2020; the StUF Testplatform itself no longer answers (stuftestplatform.nl 404) |

Port value: the scenario lists name ZDS operations `test_zaakbrug.py` does not call: `ontkoppelZaakdocument`,
`genereerBesluitIdentificatie`, `geefLijstZaakdocumenten`, `geefZaakdocumentLezen`. The reports carry complete request
messages to model builders in `zaakbrug.py` on. Check first which of these ZaakBrug implements (uncertain), and whether
ZaakBrug's SoapUI suite (upstream-tests) already has them.

How to run: port to pytest; reimplement the messages, do not copy them.

### 13. PDF accessibility (veraPDF through pdfchecker.nl) (low)

| | |
| --- | --- |
| URL | <https://gitlab.com/pleio/pdfchecker> (mirror <https://code.overheid.nl/ForumStandaardisatie/pdfchecker>) |
| Host | gitlab.com (Pleio, for Forum Standaardisatie) |
| Licence | not stated (verify) |
| Component | PDFs the platform generates: Open Formulieren submission report, OMC letters (PostGuard), ZAC documents |
| Kind | compliance validator (PDF/UA through veraPDF; the repository is the front end and CMS, veraPDF is "maintained elsewhere") |
| Size | n/a |
| Last activity | 2026-06-05 |

Port value: `test_toegankelijkheid.py` checks HTML pages only. Run veraPDF's PDF/UA profile on the submission PDF that
`test_formulier_zaak.py` already fetches. Low: whether these PDFs must be PDF/UA is a product decision.

How to run: as an external tool (veraPDF CLI or its REST image) from a test.

### 14. Internet.nl website test (low, public estates only)

| | |
| --- | --- |
| URL | <https://internet.nl/> ; mirrors <https://code.overheid.nl/ForumStandaardisatie/Internet.nl> and `.../Internet.nl-API-docs` |
| Host | internet.nl, code.overheid.nl |
| Licence | not checked (source upstream on GitHub) |
| Component | public hostnames of an estate |
| Kind | compliance validator (IPv6, DNSSEC, HTTPS/TLS per NCSC, security headers, RPKI) |
| Size | 4 test categories |
| Last activity | mirror 2026-11-11 |

Port value: overlaps with `test_web_security.py` and finding 4. It adds DNSSEC, IPv6 and RPKI, which belong to the
estate owner (podiumd-infra), not to PodiumD. The batch API needs an account. Report only, not a test.

### 15. VNG DSO business scenarios (low, likely out of scope)

| | |
| --- | --- |
| URL | <https://vng.nl/artikelen/testen-met-behulp-van-ikt-businessscenarios> (4 xlsx: planketen v3.0, toepasbare regels v3.0, vergunningenketen VTH v3.0, gehele keten v2.0) |
| Host | vng.nl |
| Licence | not stated |
| Component | Omgevingswet chain (DSO); at most Open VTB if it takes VTH aanvragen from the DSO |
| Kind | chain acceptance scenarios (test situations, control questions) |
| Size | 4 workbooks |
| Last activity | 3 updated April 2026, page 2026-06-09 |

Port value: only if an estate links Open VTB to the DSO. No PodiumD component does today (verify).

## Pointers on GitHub-hosted sites (outside this scan)

Checked 2026-11-13 against `upstream-tests.md` and `external-test-sources-plan.md`:

- `open-formulieren/form-exports`: does not exist (GitHub answers 404; the organisation's 21 public repositories
  have no form exports). Nothing to port.
- `Sudwest-Fryslan/zaakbrug2`: a fork of `wearefrank/zaakbrug`, 0 commits ahead and 860 behind, last push
  2023-03-22. Its `e2e/SoapUI` suite is the one `upstream-tests.md` already uses. Nothing to port.
- `BRP-API/Haal-Centraal-BRP-bevragen` `features/` (373 feature files): the rules of finding 10. The personen mock
  (`ghcr.io/brp-api/personen-mock` 2.7.0) applies their input validation and derived fields. Ported:
  - the fout-cases (`fields` missing, empty, not a list, unknown or a sub-field of gezag; more than 20 BSNs; a
    search without geboortedatum) with their `invalidParams` code: `test_brp.py::test_invalid_query_is_refused`;
  - volledigeNaam, leeftijd and adressering of a test-set person: `test_brp.py::test_derived_name_age_and_adressering`;
  - aanhef, aanschrijfwijze and gebruikInLopendeTekst by aanduiding naamgebruik, with a partner, an adellijke titel
    or predicaat and the hoffelijkheidstitel: `test_brp.py::test_adressering_with_partner_or_adellijke_titel`;
  - gezag: each gezag type of a minderjarige, the relaties of a gezaghebbende, none for a child without a
    gezaghebbende or for an adult: `test_brp_gezag.py`;
  - `inOnderzoek` of persoon, naam, adressering and gemeente fields, and none when the asked fields do not depend on
    the data in onderzoek: `test_brp_in_onderzoek.py`.

  Not ported: rules the test set has no person for (an ended onderzoek, a hoffelijkheidstitel with naamgebruik V or N),
  and the partner rules of `adressering/in-onderzoek.feature`. personen-mock 2.7.0 does not follow those: with the
  naam of the partner in onderzoek (999970148, 050200; 999991139, 050000) it leaves out `adressering.inOnderzoek`,
  where the feature expects aanhef, aanschrijfwijze and gebruikInLopendeTekst in onderzoek with
  `datumIngangOnderzoekPartner`.

## Looked, nothing useful

- **api-test.nl (VNG API test platform):** redirects to <https://standaarden.vng.nl/APItestplatform>. VNG ended the
  platform. Its ZGW Postman scenarios are `gemma-postman-tests`, already in the plan (2a, 2b).
- **Conduction Procest/Dossiq docs** (dossiq.conduction.nl): Newman runs of the same VNG collections (353 assertions);
  sources on GitHub.
- **Postman public network:**
  - Found the Open Zaak post-install collection (finding 6) and Maykin's Objects/Objecttypes collections on
    readthedocs (generated from the OAS; already noted in upstream-tests).
  - No public ZGW, Haal Centraal, KvK or NotifyNL workspace found by web search (the Postman network is not indexable
    without a browser).
- **gitlab.com keyword search through the API** (zgw, openzaak, open-zaak, podiumd, zaakbrug, stuf-zkn, haalcentraal,
  haal-centraal, notifynl, zaakgericht, common ground, open formulieren, open-forms, objecten api, digid mock,
  eherkenning, zaken api, zds, klantinteracties, open klant, dimpact, brp api, bag api):
  - xxllnc zaaksysteem: another product.
  - Haven tenant and Flux repositories, including `commonground/haven/platform/flux/tenant-zgw`: manifests only.
  - `commonground/basis-platform-commonground/tenants/tenant-pdv` (G4 Platform Dienstverlening: Keycloak, Open Klant,
    Open Notificaties, Objecten, Open Product, Open Zaak): Kustomize manifests, no tests.
  - `blauwe-knop/mock-digid-*`: another domain.
  - `gemeenteutrecht/helm-charts`: only Helm `test-connection` hooks.
  - `gemeenteutrecht/keycloak-add-ons`, `commonground/nlx/hackathon-services`: nothing.
- **GitLab groups** gemeente-tilburg and gemeente-rotterdam have no public projects; gemeente_apeldoorn, ibx-gemeenten
  and purmerend are unrelated.
- **code.overheid.nl** (Forgejo, all 215 public repositories listed):
  - Dimpact/KISS-frontend and Dimpact/helm-charts are GitHub mirrors.
  - CommonGround/vcg-basisset is a component list.
  - VNG/nlx-demo-rgbz is a 2018 mirror.
  - Logius `nldoc-*` is another domain.
  - MinBZK `woo-besluit-broncode-digid*` is DigiD source released under the Woo, not runnable tests.
- **codeberg.org:** the Dimpact organisation has only `objecttypes` (finding 3). Keyword search was rate-limited
  (HTTP 429), so codeberg is not fully searched.
- **Bitbucket** (maykinmedia): only deprecated or unrelated repositories; `openarchiefbeheer` there is gone (404).
- **Azure DevOps:** no public ZGW or PodiumD project found by web search.
- **PyPI:** zgw-consumers, commonground-api-common, notifications-api-common, vng-api-common, gemma-zds-client,
  mozilla-django-oidc-db and django-digid-eherkenning are libraries that ship no test suites.
- **npm:**
  - `@valtimo/*` and `@valtimo-plugins/*` belong to GZAC, not PodiumD.
  - `nl-portal-playwright-libraries` (Den Haag) tests NL Portal, not Open Inwoner.
  - `common-ground-component-checker` checks repository hygiene, not environments.
  - `@gemeentenijmegen/modules-zgw-client` is a client library.
- **KISS docs** (kiss-klantinteractie-servicesysteem.readthedocs.io): manual and decision records. The
  managementinformatie API is already tested (`test_kcc_session.py`).
- **Open Formulieren docs:** "Manual testing" (https://open-forms.readthedocs.io/nl/latest/developers/manual_testing.html)
  is a form-builder component palette checklist (UI only). The developer checklists cover import/export, which is
  development-side.
- **Dimpact / PodiumD test plans and draaiboeken:** none public. Web search found only TenderNed procurement documents
  and Deventer council notes.
- **Logius:**
  - Digikoppeling Compliance Voorziening: WUS and ebMS only, with registration; PodiumD uses neither.
  - DigiD and eHerkenning test environments need a contract and connection.
- **NotifyNL:** the REST docs moved to worth-nl.github.io (GitHub Pages, not checked). The OMC docs state that a test
  API key marks every message delivered; no smoke-test addresses were found.
- **Platform Dienstverlening GitBook** (dienstverleningsplatform.gitbook.io): G4 architecture and best practices
  ("Uniforme registratie van zaken" is still "in voorbereiding"); no test scenarios.
- **VNG ketentests:** only StUF-era reports (2015 to 2016, RvdK); none for ZGW.
- **Open Inwoner:** a Deventer WCAG 2.1 audit PDF of open-inwoner-test.maykin.nl (2022): findings, not a test script.
- **Pact brokers, SoapUI/ReadyAPI projects outside GitHub:** none found.
