# Cross-component and chain test sources for podiumd-tests

Researched 2026-11-14, read-only. Scope: tests and scenario descriptions that follow a flow across several PodiumD
components. I checked each find against `docs/research/upstream-tests.md`, `external-test-sources-plan.md`,
`external-sources-beyond-github.md`, `kiss-ita-port-plan.md`, `zac-port-plan.md`, `MIGRATION.md` (TA, MK, PI, EX) and
the suite's tests (`tests/integration/*.py`, `tests/component/**`). Nothing listed there is repeated, unless a new gap
was found in it.

Versions in the podiumd chart (helm-charts `charts/podiumd/values.yaml`, 2026-11-12): Open Zaak 1.29.3, ZAC 5.9.1,
Open Formulieren 4.0.7, Open Inwoner 2.5.0, Open Archiefbeheer 2.0.0, Open Klant 2.15.0, Referentielijsten 0.7.5.

Every URL below was fetched (HTTP 200, or read through the GitHub API) unless it is marked otherwise. "Verify" marks a
fact I did not confirm.

## Top 5

1. **Dimpact's ZAC BPMN "end-to-end-testproces (E2E)"** (Dimpact-Samenwerking/zaakafhandelcomponent-configuratie).
   This is Dimpact's own regression process for ZAC upgrades: Flowable BPMN, 21 Form.io task screens and an Open Zaak
   zaaktype export. It uses ZAC delegates that `src/podiumd_tests/bpmn/ptestBpmnProcess.bpmn` does not:
   `SuspendZaakDelegate`, `ResumeZaakDelegate`, `ExtendZaakDelegate`, and `UpdateZaakJavaDelegate` at six points (it
   uses it twice). It also has forms that read a ZAC referentietabel (`COMMUNICATIEKANAAL`), a besluit select, a fatale
   datum on a taak, and assignment expressions such as `taken:behandelaar('BPMNe2e_Start')` and the AGM snippet. Port
   these as an extension of the suite's own process, or as a second process.
2. **Open Archiefbeheer 2.0 destruction across registers** (maykinmedia/open-archiefbeheer `destruction_logic.py`,
   `external_registers/contrib/openklant` and `objecten`). Before it deletes the zaak, OAB deletes the zaak's
   besluiten and their BIOs, and the Open Klant onderwerpobjecten that a zaakobject points to. PodiumD configures both
   external registers. `test_vernietiging.py` covers the zaak, its document and the productaanvraag object, but not a
   besluit with a document and not Open Klant.
3. **Open Formulieren ↔ Open Klant `customerProfile`, Referentielijsten options, Objects API prefill and update**
   (open-formulieren/open-forms tests and their `docker/` stacks). There are three OF chains no test touches:
   - communication preferences: Open Klant prefill, writes back to Open Klant, then used by ZAC and OMC;
   - select options from PodiumD's Referentielijsten;
   - prefill from an existing object, with "update existing object" on registration.
4. **Nijmegen `mijn-services` OpenKlantRegistrationService.** A real chain: a submission becomes a zaak; the
   notification creates a partij and digitale adressen in Open Klant; OMC then reads them. Its README documents a
   race: the status notification arrives before the rol carries its betrokkene, and OMC relies on Open Notificaties'
   retry. No OMC test covers "rol after status".
5. **ZDS client message sequences from OpenZaakBrug's Ladybug reports** (Sudwest-Fryslan/OpenZaakBrug, EUPL-1.2).
   These are recorded sequences of real ZDS clients (GISVG, Suites4SociaalDomein, Verint KANA) and error handling
   (invalid SOAPAction, invalid XML, invalid path). `test_zaakbrug.py` tests the operations one by one. A client's full
   sequence and `zakLv01` (the KCC system's zaak list) are not covered.

## Ranked findings

### 1. Dimpact ZAC BPMN end-to-end test process (high)

| | |
| --- | --- |
| URL | <https://github.com/Dimpact-Samenwerking/zaakafhandelcomponent-configuratie/tree/main/Procesmodellen%20en%20taakschermen/end-to-end-testproces%20(E2E)> ; repo <https://github.com/Dimpact-Samenwerking/zaakafhandelcomponent-configuratie> |
| Licence | none declared (no LICENSE file; GitHub: none) |
| Components | ZAC (Flowable, Form.io task screens, referentietabellen, mail), Open Zaak (zaaktype export `bpmn_e2e-2026-03-05.zip`, statussen, opschorting, verlenging, besluit), Keycloak groups and users |
| Kind | executable test fixture: a BPMN process and task screens built "to test ZAC's functions, e.g. after an update" (README), run by hand |
| Tool | Flowable BPMN 2.0 + Form.io JSON |
| Size | 1 process with about 31 tasks, 21 task screens, 1 zaaktype export. The repo also holds 9 municipal processes (Groningen BAG and besluitvorming, Emmen Bezwaar indienen and bestuurlijke besluitvorming, Oost Gelre beroep, Assen subsidie, evenementen-vooroverleg, generiek-proces PZ-9471), about 150 files, plus "Taakscherm snippets" |
| Last activity | 2026-08-20 (README: tested on ZAC 4.5.33) |

Process content (BPMNe2e.bpmn):

- Service tasks:
  - automatic and manual ontvangstbevestiging (`SendEmailDelegate` ×2);
  - status changes (`UpdateZaakJavaDelegate` ×6);
  - opschorten (`SuspendZaakDelegate`), hervatten (`ResumeZaakDelegate`), verlengen (`ExtendZaakDelegate`);
  - zaak toewijzen (`UpdateZaakAssignmentDelegate`).
- User tasks:
  - assign to yourself, to the previous or next behandelaar, or to behandelaar A, B or C;
  - select, show and sign documents;
  - Document aanmaken (SmartDocuments);
  - Attributen testen (field validation for bsn, postcode, iban, kvk and vestigingsnummer, a select on referentietabel
    `COMMUNICATIEKANAAL`, conditional panels, a datagrid);
  - fatale datum on a taak, Voortgangsbewaking, Besluit (select `ZK_Besluit`), Zaak afsluiten.

Port value (checked against `tests/component/zac/test_zac_bpmn*.py` and `ptestBpmnProcess.bpmn`):

- Covered: intake, assignment, select and sign, summary and close, BPMN mail, beheer upload and delete. Opschorten,
  hervatten and verlengen of a BPMN zaak are covered through ZAC's REST API only
  (`test_bpmn_zaak_is_opgeschort_hervat_and_verlengd`).
- Gaps:
  - the Suspend, Resume and Extend delegates run as service tasks: does the zaak in Open Zaak get the opschorting
    and verlenging, and does the next taak's fatale datum move;
  - automatic ontvangstbevestiging at process start (Mailpit; needs capability `mailpit`);
  - status changes at several points, with their order in Open Zaak;
  - a taak form select filled from a ZAC referentietabel;
  - a besluit chosen in a taak form;
  - assignment to the previous behandelaar (`taken:behandelaar(...)`).
- Out of scope: SmartDocuments "Document aanmaken" (no environment has SmartDocuments).
- Corpus test: upload each municipal process and its forms through ZAC's procesdefinitie beheer, check that ZAC
  accepts them, then delete them. This catches Form.io components that a ZAC upgrade no longer accepts. It extends
  `test_procesdefinitie_beheer_from_upload_to_delete`.

How to port: there is no licence, so reimplement. Add the delegates and forms to `src/podiumd_tests/bpmn/`, or ask
Dimpact (the ZAC BPMN werkgroep) for permission to vendor the process. The zaaktype goes through the bootstrap snippet
pattern of `openzaak-zaaktype-bpmn`. Verify first that ZAC 5.9.1 still has the delegate classes; the suite's own
process uses the same `net.atos.zac.flowable.delegate` namespace.

### 2. Open Archiefbeheer: destruction across Besluiten, Documenten, Objecten and Open Klant (high)

| | |
| --- | --- |
| URL | <https://github.com/maykinmedia/open-archiefbeheer/blob/main/backend/src/openarchiefbeheer/destruction/destruction_logic.py> ; <https://github.com/maykinmedia/open-archiefbeheer/tree/main/backend/src/openarchiefbeheer/external_registers/contrib/openklant> ; CHANGELOG 2.0.0 (#940 Objecten plugin, #905 Open Klant plugin), 2.1.0 (#1032 list with a zaak without archiefactiedatum) |
| Licence | none declared in the repository (verify; Maykin's other apps are EUPL) |
| Components | Open Archiefbeheer, Open Zaak (Zaken, Besluiten, Documenten), Objecten, Open Klant; producers: ZAC (besluit, productaanvraag zaakobject), KISS (klantcontact on a zaak) |
| Kind | executable unit and VCR tests (`OpenKlantPluginTests.test_delete_relations`, `ObjectenPluginTests.test_delete_relations`), and the deletion order in code |
| Tool | pytest/Django with VCR cassettes recorded against docker Open Zaak, Open Klant and Objecten |
| Size | 2 plugin test modules; deletion steps: external relations through zaakobjecten → besluiten with BIOs → ZIOs → EIOs → zaak |
| Last activity | 2026-11-13 |

Port value:

- PodiumD estates configure `external_registers.openklant` and `objecten` (podiumd values, OAB section, with the
  `openklant-api` identifier note).
- Gaps:
  - Destroying a zaak with a besluit that has a besluit document: the besluit, its BIO and the document are gone from
    Open Zaak. `test_vernietiging.py` has no besluit case. `open-zaak-7` (deleting a besluit leaves its document links)
    may show up here; reproduce before marking anything.
  - A zaak whose zaakobject points to an Open Klant onderwerpobject: after destruction the onderwerpobject is gone
    and the klantcontact stays. Verify which PodiumD app creates such a zaakobject. KISS links through an Open Klant
    onderwerpobject (`kiss_onderwerpobject`), not a zaakobject. If none does, the plugin only acts on zaakobjecten
    that a test makes itself.
  - OAB's plugin health check (`check_config`: plugin disabled, or no service) as a doctor or smoke check: both
    registers enabled with a service.
  - 2.1.0 #1032: a zaak without an archiefactiedatum cannot be put on a list or queued for deletion.

How to port: extend `tests/component/openarchiefbeheer/test_vernietiging.py`, using the existing list fixtures,
`make_besluit` and `make_onderwerpobject`. These tests are tier chaos, like the module. Reimplement; do not copy
cassettes.

### 3. Open Formulieren chains with Open Klant, Referentielijsten and Objecten (high)

| | |
| --- | --- |
| URL | <https://github.com/open-formulieren/open-forms/tree/master/src/openforms/contrib/customer_interactions> (tests: `test_update_customer_interaction_data.py`, `test_de_duplicating.py`); prefill `src/openforms/prefill/contrib/customer_interactions/tests`; `src/openforms/contrib/reference_lists/tests`; `src/openforms/prefill/contrib/objects_api/tests` and `registrations/contrib/objects_api/tests` (`test_initial_data_ownership_validation.py`); stacks <https://github.com/open-formulieren/open-forms/tree/master/docker> (`docker-compose.open-klant.yml`, `objects-apis`, `open-zaak`, `referentielijsten`, `hc-brp-mock`) |
| Licence | EUPL (LICENSE.md) |
| Components | Open Formulieren, Open Klant 2, Referentielijsten, Objecten/Objecttypen; downstream: ZAC ontvangstbevestiging, OMC, Open Inwoner profile |
| Kind | executable Django tests with VCR cassettes recorded against the docker stacks; the CHANGELOG states the behaviour |
| Tool | Django TestCase + VCR |
| Size | about 9 test modules for these three features; 489 cassette files in the repository |
| Last activity | 2026-11-13 |

Port value (grep of the suite: no `customerProfile`, `customer_interactions`, reference lists or Objects API prefill
in any test):

- `customerProfile` (OF 3.4+): after a DigiD login the component is prefilled with the inwoner's digitale adressen
  from Open Klant. A changed or new address is written back to Open Klant (5711; the `referentie` attribute, 6418;
  e-mail verification, 6426).
  - Chain: OI profile e-mail (`test_profile_email_reaches_open_klant`) → OF prefill → submission writes the voorkeur.
  - Downstream: ZAC's ontvangstbevestiging to the voorkeur address (`test_productaanvraag_bevestiging.py` already
    asserts the voorkeur rule) and OMC.
  - Nothing tests the OF ↔ Open Klant leg.
- Referentielijsten as the options source of a select (OF 3.1, #5178): a form field lists the items of a
  Referentielijsten tabel and refuses an item that is not valid. PodiumD deploys Referentielijsten, and its only test
  (`test_referentielijsten.py`) does not go through a consumer.
- Objects API prefill with "update existing object" (OF 3.0, #4396 and #4398): a form opened with an
  `initial_data_reference` prefills from an object and updates that object instead of creating a new one. The
  ownership check refuses another person's object. This is the "wijzigen" flow municipalities use for products.

How to port: integration tests in `tests/integration/test_formulier_*.py`. Build a throwaway form through OF's API, as
`test_formulier_wijzigen.py` does with `OF_REDACTEUR`. This needs OF services configured for Open Klant and
Referentielijsten. Those belong to podiumd-minikube and the environment owner: request them through
`docs/handoff/podiumd-minikube.md` if they are missing (check the deployed OF config first). Mail-sending forms need
`requires(..., "mailpit")`.

### 4. Nijmegen mijn-services: Open Klant registration for OMC (medium)

| | |
| --- | --- |
| URL | <https://github.com/GemeenteNijmegen/mijn-services/tree/main/src/services/OpenKlantRegistrationService> ; repo <https://github.com/GemeenteNijmegen/mijn-services> (docs `docs/Architectuur/patronen/taken/Taken.md`, `klantbeeld`, `profiel`) |
| Licence | EUPL-1.2 |
| Components | Open Formulieren (Woweb, VrijBRP), Open Zaak, Open Notificaties, Open Klant 2, OMC (NotifyNL), Objecten (taken) |
| Kind | TypeScript tests, some live (`liveHandleNotificatie`, `liveOpenKlant`, `liveZakenApi`, `createTestZaak`), and README scenarios |
| Tool | Jest (projen/CDK) |
| Size | 12 test files in the service; 2 sample notifications (`notification-zaak.json`, `notification-rol.json`); 3 form submission samples |
| Last activity | 2026-11-11 |

Port value:

- The README records a production race. OMC gets the zaak's status notification before the initiator rol points to
  the partij, so OMC falls back to a BSN lookup and fails. Only Open Notificaties' retry delivers the mail. Gap in
  `test_omc.py`: a zaak whose initiator rol is added after its first status still mails the inwoner (or does not;
  record which). `test_failed_delivery_is_retried` covers retry in general, not this case.
- eHerkenning has no known contactpersoon, and a second zaak of the same person creates a second partij: cases for
  OMC's choice of address.

How to port: pytest in `tests/integration/test_omc.py` with `make_zaak`, `make_status` and `make_rol` in that order,
`wait_until` and the mock Notify. There is no code to copy.

### 5. OpenZaakBrug Ladybug reports: real ZDS client sequences (medium)

| | |
| --- | --- |
| URL | <https://github.com/Sudwest-Fryslan/OpenZaakBrug/tree/master/src/test/resources/ladybug> ; same files in <https://github.com/Haarlem/zds-stuf-to-zgw-api-translator> ; SoapUI `examples/soap/Open-Zaakbrug-soapui-project.xml` and `20230213 - Open Zaak performance soapui-project.xml` |
| Licence | EUPL-1.2 |
| Components | ZDS clients (GISVG, Suites4SociaalDomein, Verint KANA) → ZaakBrug → Open Zaak (Zaken, Documenten, Catalogi) |
| Kind | recorded request/response reports (Ladybug XML) used as regression tests |
| Tool | Ladybug (Java, JUnit `LadybugTests.java`) |
| Size | 9 report folders: ErrorHandling (6), Gisvg Natuurlijk Persoon (9), Gisvg Emulate Replicate (2), Suites4SociaalDomein ×2 (about 5 each), Verint KANA (`zakLv01` ×2), Issue235/329/330/332 |
| Last activity | 2026-11-08 |

Port value: PodiumD deploys wearefrank/zaakbrug, the successor; ZDS 1.2 messages are the same.

- Gaps against `tests/component/zaakbrug/test_zaakbrug.py`:
  - `zakLv01` with a gerelateerde BSN: the KCC system lists the zaken of a person;
  - error handling: an invalid SOAPAction, an action that does not match the body, invalid XML, an unknown path. Each
    should give a SOAP Fault, not a 500 or a hang;
  - Suites4SociaalDomein's full sequence: genereerZaakIdentificatie → creeerZaak → genereerDocumentIdentificatie →
    voegZaakdocumentToe → … as one test;
  - the replicate/emulate mode (Gisvg Emulate Replicate) only if an estate turns it on.
- Verify first that wearefrank/zaakbrug implements `zakLv01` (uncertain).

How to port: new builders in `src/podiumd_tests/zaakbrug.py`; reimplement the messages from the reports.

### 6. Dimpact `testscripts`: PodiumD end-to-end tests 2023-2024 (medium; private repository)

| | |
| --- | --- |
| URL | <https://github.com/Dimpact-Samenwerking/testscripts> (**private**: readable with the user's GitHub account, 404 anonymously; do not quote outside Dimpact) |
| Licence | none declared |
| Components | Open Formulieren → Objecten → e-Suite (ZRC/DRC through `zgw-apis-provider`); DigiD; Ogone/Ingenico payment; BAG address lookup in OF; Open Inwoner → e-Suite (Mijn aanvragen, contactformulier, upload) |
| Kind | executable Playwright tests plus scenario descriptions with sequence diagrams (`testopzet/release_*`) |
| Tool | Playwright (TypeScript), GitHub Actions nightly against test-* and acc-*.dimpact.nl |
| Size | 4 specs plus 1 on hold, 5 test descriptions |
| Last activity | code 2024-06-04; repo 2026-06-09 |

Port value:

- Mostly covered: the OF → Objecten → zaak chain (`test_productaanvraag.py::test_new_form_becomes_a_zac_zaak`), OF
  payment (`test_formulier_betaling.py`), and OI login, profile, contact form, Mijn zaken and upload
  (`test_portaal_*`).
- Gap 1: OF address lookup by postcode and huisnummer through the BAG (release 1.2: `/lvbag/individuelebevragingen/v2/adressen`).
  `test_formulier_api.py::test_address_search_reaches_pdok` covers only the PDOK free-text search, not OF's
  `address-autocomplete`.
- Gap 2: chains that end in the e-Suite apply only to estates with an e-Suite (capability `kiss-adapter`-like); skip
  elsewhere.

How to port: one test in `tests/component/openformulieren/test_formulier_api.py` calling
`/api/v2/geo/address-autocomplete?postcode=…&house_number=…` with a BAG test address from `basisregistraties.py`.
Verify that OF's BAG (Kadaster) configuration exists on the estates.

### 7. Datamigratie (DMT) with its FakeDet (medium, conditional)

| | |
| --- | --- |
| URL | <https://github.com/ICATT-Menselijk-Digitaal/Datamigratie> |
| Licence | none declared |
| Components | e-Suite DET (faked by `Datamigratie.FakeDet`: generated zaken, documents and 4 catalogi) → DMT → Open Zaak (zaken, rollen, statussen, resultaat, besluiten, documents); then ZAC, OI and OAB read the migrated zaken |
| Kind | unit tests (about 25 classes) and a runnable fake source system; no end-to-end test |
| Tool | xUnit (.NET) |
| Size | 25 test classes; FakeDet with ZaakFaker and TestFileGenerator |
| Last activity | 2026-11-12 |

Port value: DMT is part of some estates; the podiumd chart has a `datamigratie` Keycloak client, and
`qa-environments.md` lists datamigratie on some estates. podiumd-tests has no test for it.

- Smoke: the DMT URL answers and its Keycloak login works.
- Chain: with FakeDet as source, migrate one zaak with its mappings (zaaktype, status, roltype, resultaat). The zaak is
  in Open Zaak with its rollen and documents and shows in ZAC. A missing mapping blocks the migration
  (`ValidateStatusMappingsService`, `ValidateRoltypeMappings`).
- Only where an estate deploys DMT with FakeDet; minikube does not.

How to port: smoke first (`COMPONENTS`, `Capabilities`); the chain after a handoff on deploying FakeDet.

### 8. VNG MijnServices: Mijn Taken scenario and the Open VTB Taken aansluitprofiel (medium-low, future)

| | |
| --- | --- |
| URL | <https://github.com/VNG-Realisatie/mijn-services-documentatie> (`docs/mijn-services/scenarios/ontbrekende-informatie-aanleveren.md`, `aansluitprofielen/openvtb-taken-api/`, `aansluitprofielen/combinaties.md`) |
| Licence | EUPL-1.2 |
| Components | Open VTB Taken (`externetaken`: betaaltaak, urltaak, formuliertaak; `isGerelateerdAan` urn of a zaak), ZGW Documenten, portal |
| Kind | scenario descriptions (draft) and Arazzo workflow mappings |
| Tool | Docusaurus docs, Arazzo |
| Size | 1 worked scenario, 4 candidate scenarios, 2 candidate combinations |
| Last activity | 2026-11-11 |

Port value: "Ontbrekende informatie aanleveren": an externe taak tied to a zaak; the inwoner sees it and uploads a
document to the zaak. Open Inwoner 2.x has no Open VTB integration (no `openvtb` or `externetaken` in its code), so no
PodiumD portal shows these taken yet. API level only for now: `test_openvtb.py` has a urltaak roundtrip, so add a
taak with `isGerelateerdAan` the urn of a test zaak, and the betaaltaak and formuliertaak variants. Revisit when OI or
OMC consumes Open VTB taken. OMC's Open VTB bericht is already in `test_omc_bericht.py`.

### 9. Frank!Gateway's own Bruno tests (low)

| | |
| --- | --- |
| URL | <https://github.com/wearefrank/frank-gateway/tree/master/tests> (default branch `master`; checked through the API) |
| Licence | Apache-2.0 |
| Components | Frank!Gateway (APISIX plugins), Keycloak (oidc-client), an AuthZEN PDP; BRP as example upstream |
| Kind | executable request collections with docker-compose per plugin |
| Tool | Bruno |
| Size | auth-zen 18, cert-auth 12, soap-action-router 8, limit-size 7, oidc-client 7, jwt-client 7, generic-oauth 7, merge-config 7, frank-sender 6, opa 4, regression 6 |
| Last activity | 2026-11-12 |

Port value: the podiumd chart configures `openbao-consumer-auth` (and `fsc` once) but none of these plugins.
cert-auth's cases (no, untrusted or expired certificate) are covered by `test_inway_admits_only_the_allowed_consumer`.
Only relevant if an estate routes ZaakBrug through FG (`soap-action-router`: wrong SOAPAction → 403), or BRP through
AuthZEN doelbinding (403 for a wrong purpose).

### 10. Open Zaak DRC Test Automation System (low)

| | |
| --- | --- |
| URL | <https://github.com/open-zaak/drc-tas-restapi> |
| Licence | LICENSE.md (GitHub: NOASSERTION; verify) |
| Components | Open Zaak Documenten (also against Alfresco through the CMIS adapter), Open Notificaties in its docker stack |
| Kind | executable Java tests translated from the VNG documenten-api 1.3.0 tests, plus custom tests |
| Tool | RestAssured + TestNG |
| Size | 20 test classes |
| Last activity | 2024-04-18 |

Port value: single component, mostly covered by `test_documenten.py`. Possible additions: upload in bestandsdelen
edge cases (`test_upload_part_wrong_size`, `test_unlock_without_uploading`, `test_unlock_not_finish_upload_force`,
`test_update_metadata_set_size_zero`), which ZAC's large uploads and the Office add-in use. Check them against
`test_documenten.py` before porting.

## Looked, nothing useful

- **VNG-Realisatie/zgw-gherkin** (archived 2023, no licence; behave): 4 features (zaak, archiveren, historiemodel,
  catalogus). Single component, and already covered: zrc-008, expand, historiemodel in
  `external-test-sources-plan.md`.
- **VNG gemma-zaken `test-scenarios.md`**: points to gemma-postman-tests, already ported. **VNG notificatieservices**:
  2021/22 CloudEvents project with a scenario PDF; PodiumD uses CloudEvents only from Open VTB to OMC (covered).
  **VNG klantinteracties, Omnichannel-Archi-repository**: no scenarios or tests.
- **Dimpact Service Blueprints** (PDF customer journeys: KCC aangifte verhuizing, financiële hulp, windmolenpark,
  melding openbare ruimte; municipal permit journeys): narratives without testable steps.
- **Dimpact-OpenFormulieren-Configuraties** (4 form exports, 2024), **Dimpact-OpenZaak-ZaakTypen** (publiccode only),
  **Monitoring_PodiumD** (Grafana chart copy): no chain content.
- **Súdwest-Fryslân MijnZaakNotificaties** (EUPL-1.2; 8 Ladybug scenarios): Open Zaak to MijnOverheid Lopende Zaken,
  which PodiumD does not use. **WebformulierenVerwerker** (SoapUI): Kodison to Corsa.
- **Nijmegen**: `corsa-zgw` (ZGW notifications to the Corsa DMS; Pest tests and a test plan), `mijn-nijmegen` (own
  portal, 1 Playwright spec), `open-forms-testautomatisering` (already in the plan).
- **Den Haag**: `referentie-common-ground-implementatie` (2023 GZAC architecture docs), `helm-charts` (`http-checks`
  test hooks only). **Utrecht**: own ZAC, BPTL, old ZGW reference forks; no chain tests. **Amsterdam**: mijn-amsterdam,
  Signalen and a BRP proxy, another stack. **Rotterdam, Delft**: no relevant public repos. **Tilburg, Groningen**: no
  matching GitHub organisation; Groningen's processes are in finding 1. **Haarlem**: the ZDS translator is the same code
  as OpenZaakBrug (finding 5).
- **GemeenteArnhem/Vernietigingscockpit-stekker-openzaak**: README only.
- **rjbarendse/CommonControl** (EUPL-1.2): a beheer UI over the Common Ground APIs, no tests.
- **EduardWitteveen/launch**: a demo launcher (GZAC, Nextcloud, Haal Centraal) with its own launcher tests.
- **govtechnl/onegov2-inwoner-centraal** (Apache-2.0): synthetic personas and mock APIs for a bereavement case, not
  PodiumD components.
- **Onincx/Ketentest-Bemiddelingsregister**: another domain.
- **GZAC/Valtimo, NL Portal**: not PodiumD components (NL Portal's Playwright libraries are already in "looked").
- **podiumd-infra-extra-apps/tests**: a branch of podiumd-infra (PI source in MIGRATION.md).
- **helm-charts** `charts/test` and the `podiumd-test-podiumd-helm-chart-changes` workflow: render checks only.
- **Logius "Checklist Testen LopendeZaken"**
  (https://test-dictu.logius.nl/sites/default/files/public/bestanden/diensten/MijnOverheid/Checklist-Testen-LopendeZaken.pdf;
  answers 403 to an automated fetch, not read): MijnOverheid, not PodiumD.
- **VNG/softwarecatalogus ketentest reports** (RvdK, StUF, 2015-2016): StUF era; the ZDS ones are already in
  `external-sources-beyond-github.md`.
- **Web searches**: "ketentest Open Zaak Open Formulieren", "PodiumD ketentest", "Open Inwoner Open Klant testscenario",
  zaakgericht werken plus Playwright or Robot Framework. No public PodiumD-like chain test suite or ketentest
  scenarios beyond the above; VNG's IKT business scenarios are for the Omgevingswet (DSO), already noted.
- **GitHub code search** (ZGW API paths in `.ts`, `.robot`, `.feature` and `.py` test files outside the component
  organisations): only the hits above. The code search index is sparse, so absence is not proof.
- **Codeberg**: the search API answered 429 again, so it is still not searched.
