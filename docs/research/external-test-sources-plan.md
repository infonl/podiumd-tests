# External test suites: porting plan

Scanned 2026-11-10, read-only, on each repository's default branch. For each case of an external suite: does
podiumd-tests already check it, and is it worth a test against a deployed PodiumD environment. The user picks
the batches to port.

Coverage: **covered** (a test checks it; named), **partly** (a test checks part of it), **gap**, **n/a** (not
applicable to a PodiumD environment). Decision: **port** (new test), **merge** (into an existing test or its
parameters), **skip**.

Versions: PodiumD 4.10 runs Open Zaak 1.29.3, which implements Zaken API 1.5, Documenten API 1.4 and Catalogi
API 1.3 (Open Zaak's changelog: Documenten 1.5 and 1.6 in 1.31.0, Zaken 1.7 in 1.31.1). Cases of later API
versions are n/a until PodiumD ships that Open Zaak.

Rights of the suite's ZGW clients (bootstrap `openzaak-client*`): `ptest-bootstrap-zgw` has every atomic
`zaken.*`, `documenten.*`, `besluiten.*` and `audittrails.*` scope on the test catalogus up to `zeer_geheim`,
including `zaken.geforceerd-bijwerken`, `zaken.heropenen` and `documenten.geforceerd-unlock`, plus
`catalogi.lezen` and `catalogi.schrijven`; `ptest-bootstrap-zgw-openbaar` the same without `verwijderen` and up
to `openbaar`; `ptest-bootstrap-zgw-noauth` none. No client has Autorisaties API scopes.

## Summary

| # | Source @ commit | Licence | Unit | Total | Covered | Partly | Gap | n/a | Proposed tests | Days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1a | `OneGround/ZGW-APIs-postman-tests` "ZGW business rules" | BSD-3-Clause | rule (659 requests, 357 `pm.test`) | 55 | 1 | 17 | 28 | 9 | 26 | 10 |
| 1b | same, "ZGW features" (ZGW 1.5 and 1.7) | BSD-3-Clause | folder (299 requests, 277 `pm.test`) | 31 | 3 | 13 | 10 | 5 | 5 | 1.5 |
| 2a | `VNG-Realisatie/gemma-postman-tests` `ZGW_api_postman_tests.json` (standaard.md) | EUPL | rule (859 requests, 401 `pm.test`) | 56 | 52 shared with 1a | | 4 | | 1 | 0.5 |
| 2b | same, `ZGW_OAS_tests.json` | EUPL | folder (228 requests, 243 `pm.test`) | 27 | 7 | 14 | 4 | 2 | 1 | 0.5 |
| 2c | same, `issues_openzaak.md` | EUPL | note | 7 | | | 4 to recheck | 3 | 0 | 0 |
| 3 | `GemeenteNijmegen/open-forms-testautomatisering` | EUPL-1.2 | pattern (21 specs) | 7 | 0 | 3 | 2 | 2 | 3 | 2.5 |
| 4 | `VNG-Realisatie/gemma-zaken-test-integratie` (archived 2019) | none declared | test module | 10 | 5 | 3 | 2 | 0 | 0 (merged into 1a) | in 1a |
| 5 | `Baseflow/cg-dmf-poc` `k6/perf.js`, Open Notificaties `docs/development/performance/scenarios.rst` | EUPL | operation or profile feature | 10 | 1 | 1 | 8 | 0 | 2 perf changes | 2 |
| 6 | `ICATT-Menselijk-Digitaal/podiumd-adapter` xUnit tests | EUPL | test class | 9 | 0 | 0 | 8 | 1 | 2 (4 with a mock e-Suite) | 1 (3) |
| | **Total** | | | | | | | | **38 tests, 2 perf changes** | **about 18** |

Sources 1a and 2a are one rule set: VNG's collection numbers the rules of the ZGW standard, and OneGround's is a
later edit of it (52 of 56 rule groups have the same ids). Table 1a maps them once; table 2a lists only the four
VNG-only rule groups. Source 4 adds no test of its own: its exact-date checks sharpen tests of batch 3 and 4.

Probable defect hits of the gaps (xfail ids from podiumd-known-issues):

- `open-zaak-1` (DELETE of a zaak with a resultaat answers 500, fixed in 1.31.0): zrc-023, zrc-007e (DELETE of a
  resultaat recalculates the same ETag).
- `open-zaak-3` (audittrail endpoints need all rights): drc-008c, brc-009d.
- `open-zaak-4` (same-name large uploads lose content): the document create of the perf mix (batch 10) when it
  reuses one bestandsnaam.
- `open-notificaties-1` and `-2` (500 for an unreachable callback, and when an abonnement is deleted during a
  delivery): the Open Notificaties perf scenario.
- Not registered yet: Open Zaak #2577 (stale `ETag`, a conditional GET answers 304 for a changed resource after
  deleting a rol or resultaat or closing a hoofdzaak; fixed in 1.31.1). The ETag cases of 1b would likely
  reproduce it on 1.29.3; register as `open-zaak-5` only after reproducing.
- `issues_openzaak.md` (2019, Open Zaak 1.0) lists four behaviours the planned tests recheck: ZaakInformatieObject
  with an invalid URL answers 500 (zrc-003d), besluit on a zaak gives `zaaktype-mismatch` (brc-007), a
  Zaaktype-Informatieobjecttype does not appear in `Zaaktype.informatieobjecttypen` (2b historiemodel),
  resultaattype validation missing (ztc-003 to 008, n/a here).

## 1a. OneGround "ZGW business rules"

Folders per rule of the ZGW standard (`<api>-<nnn>`), letters per case. "Positive case" means the request that
must succeed; most rules test POST, PUT and PATCH alike.

| Rule | Checks | Coverage | Decision | Reason | Target |
| --- | --- | --- | --- | --- | --- |
| ac-001 | Applicatie with several clientIds; a used clientId refused | n/a | skip | needs Autorisaties API write rights, which would let the suite grant itself any right | |
| ac-002 | heeftAlleAutorisaties with explicit autorisaties, or neither, refused | n/a | skip | as ac-001 | |
| ac-003 | zrc/drc autorisatie needs maxVertrouwelijkheidaanduiding and type; brc without besluittype allowed | n/a | skip | as ac-001 | |
| zrc-001 | Zaak PUT/PATCH; zaaktype URL that does not resolve, is no zaaktype, or is a concept: 400 | partly: `test_validatie.py::test_invalid_zaak_names_the_field` (unknown-zaaktype), `test_zaken.py::test_zaak_lifecycle` (PATCH) | merge | add "URL of another resource" and "concept zaaktype" (`make_concept_zaaktype`) to the parameters | `tests/component/openzaak/test_validatie.py` |
| zrc-002 | identificatie unique per bronorganisatie on POST, PUT, PATCH; generated identificatie unique | partly: `test_zaken.py::test_identificatie_is_unique_under_concurrent_creates` (POST) | merge | PATCH to an existing identificatie is how a client overwrites a zaak's number | `tests/component/openzaak/test_zaken.py` |
| zrc-003 | ZaakInformatieObject POST/PUT/PATCH; informatieobject URL that does not resolve: 400 | partly: `test_documenten.py::test_document_linked_to_zaak` (POST) | merge | the invalid URL answered 500 in 2019 (`issues_openzaak.md`) | `tests/component/openzaak/test_documenten.py` |
| zrc-004 | ZIO gets aardRelatie `hoort_bij` and registratiedatum now; its zaak and informatieobject cannot change | gap | port | the zaak-document link ZAC and the portal show must not move | `tests/component/openzaak/test_documenten.py` |
| zrc-005 | creating a ZIO creates the ObjectInformatieObject in Documenten; deleting it deletes the OIO | gap | port | Zaken and Documenten API keep two copies of one relation; with drc-00x | `tests/component/openzaak/test_documenten.py` |
| zrc-006 | zaken list filtered by the client's autorisaties; read or create without the scope: 403 | covered: `test_autorisaties.py` (`test_zaakvertrouwelijke_zaak_is_hidden_from_an_openbaar_client`, `test_client_without_autorisaties`) | skip | covered | |
| zrc-007 | eindstatus sets einddatum to its datumStatusGezet (a, r); closing needs indicatieGebruiksrecht on every document (b, q); a closed zaak and its status, resultaat, rol, ZIO, zaakobject, zaakeigenschap and klantcontact change only with `zaken.geforceerd-bijwerken` (c to p) | partly: `test_statussen_rollen.py::test_zaak_closes_with_resultaat_and_eindstatus` (einddatum set, not its value) | port | ZAC closes zaken; a closed zaak must stay closed for clients without the scope; bootstrap: a client without `geforceerd` | `tests/component/openzaak/test_zaak_afsluiten.py` (new) |
| zrc-008 | a non-eindstatus reopens a closed zaak and clears einddatum, archiefactiedatum, archiefnominatie; without `zaken.heropenen`: 403 | gap | port | ZAC's heropenen (`test_zac_rollen.py` checks only ZAC's rights); same client as zrc-007 | `tests/component/openzaak/test_zaak_afsluiten.py` |
| zrc-009 | explicit vertrouwelijkheidaanduiding kept; without it, the zaaktype's | partly: `test_autorisaties.py` sets it explicitly | merge | the derived value decides what the openbaar client sees | `tests/component/openzaak/test_zaken.py` |
| zrc-010 | communicatiekanaal URL that does not resolve or is no communicatiekanaal: 400; a valid one accepted | gap | port | negative cases only: PodiumD's Referentielijsten is not the VNG Referentielijsten API Open Zaak expects for the positive case | `tests/component/openzaak/test_validatie.py` |
| zrc-011 | relevanteAndereZaken with an invalid URL: 400 | partly: `test_zaken.py::test_relevante_andere_zaken` (valid) | merge | one parameter | `tests/component/openzaak/test_validatie.py` |
| zrc-012 | opschorting without indicatie and reden, verlenging without reden and duur: 400; null allowed | gap (ZaakBrug's verlenging: `test_zaakbrug.py::test_update_zaak_ignores_an_incomplete_verlenging`) | merge | ZAC sets both | `tests/component/openzaak/test_validatie.py` |
| zrc-013 | hoofdzaak that is no zaak, or the zaak itself: 400 | gap | merge | two parameters | `tests/component/openzaak/test_validatie.py` |
| zrc-014 | betalingsindicatie `nvt` with laatsteBetaaldatum: 400 on POST; PUT/PATCH to `nvt` clears laatsteBetaaldatum | gap | merge | Open Formulieren's payment sets betalingsindicatie (`test_formulier_betaling.py`) | `tests/component/openzaak/test_validatie.py` |
| zrc-015 | productenOfDiensten not in the zaaktype's: 400 | gap | merge | one parameter | `tests/component/openzaak/test_validatie.py` |
| zrc-016 | status with a statustype of another zaaktype: 400 | gap | port | one parametrized test for zrc-016 to 020, with the types of the bootstrap's BPMN zaaktype in the same catalogus | `tests/component/openzaak/test_zaaktype_consistentie.py` (new) |
| zrc-017 | ZIO whose informatieobjecttype is not in the zaaktype's: 400 | gap | port | as zrc-016 | same |
| zrc-018 | zaakeigenschap with an eigenschap of another zaaktype: 400 | gap | port | as zrc-016 | same |
| zrc-019 | rol with a roltype of another zaaktype: 400 (folder named ztc-019) | gap | port | as zrc-016 | same |
| zrc-020 | resultaat with a resultaattype of another zaaktype: 400 | gap | port | as zrc-016 | same |
| zrc-021 | without archiefnominatie, closing derives archiefnominatie and archiefactiedatum from the resultaattype's afleidingswijze: afgehandeld, hoofdzaak, eigenschap, ingangsdatum_besluit, vervaldatum_besluit, ander_datumkenmerk | partly: `test_zaak_closes_with_resultaat_and_eindstatus` (afgehandeld; archiefactiedatum set, not its value) | port | Open Archiefbeheer destroys by this date; bootstrap: a zaaktype with one resultaattype per afleidingswijze | `tests/component/openzaak/test_archivering.py` (new) |
| zrc-022 | archiefstatus defaults to `nog_te_archiveren`; another value needs archiefnominatie and archiefactiedatum | partly: `test_statussen_rollen.py::test_archiefnominatie_can_be_set_and_filtered` | merge | the refusals are the gap | `tests/component/openzaak/test_archivering.py` |
| zrc-023 | deleting a zaak deletes its resultaat, status, rol, zaakobject, zaakeigenschap, ZIO, OIO, klantcontact | partly: `test_zaak_lifecycle` (zaak gone), `test_closed_zaak_delete_answers_204` (xfail `open-zaak-1`) | port | Open Archiefbeheer deletes zaken; leftovers stay in Documenten | `tests/component/openzaak/test_verwijderen.py` (new) |
| drc-001 | EIO created; with a concept informatieobjecttype: 400 | partly: every `make_document` | merge | concept case only | `tests/component/openzaak/test_documenten.py` |
| drc-002 | OIO with an object URL that does not resolve or is no zaak/besluit: 400 | gap | port | one parametrized test for drc-002 to 004 | `tests/component/openzaak/test_documenten.py` |
| drc-003 | a second OIO for the same object and informatieobject: 400 | gap | port | as drc-002 | same |
| drc-004 | OIO without the ZIO or BIO in Zaken or Besluiten: 400 | gap | port | as drc-002 | same |
| drc-006 | indicatieGebruiksrecht null by default; true needs gebruiksrechten; creating gebruiksrechten sets it true, deleting them null | partly: `test_document_versions_and_definitief` (null at create) | merge | needed to close a zaak (zrc-007b) | `tests/component/openzaak/test_documenten.py` |
| drc-007 | explicit vertrouwelijkheidaanduiding kept; without it, the informatieobjecttype's | partly: `test_autorisaties.py` (explicit) | merge | as zrc-009 | `tests/component/openzaak/test_documenten.py` |
| drc-008 | EIO with an OIO cannot be deleted; deleting it deletes gebruiksrechten and audittrail | gap | port | audittrail part reads with catalogus rights (`open-zaak-3`) | `tests/component/openzaak/test_verwijderen.py` |
| drc-009 | PUT/PATCH without lock or with a wrong lockId: 400; lock returns a lockId; forced unlock needs `documenten.geforceerd-unlock` | partly: `test_document_versions_and_definitief` (lock, PUT, unlock) | merge | the refusals and the forced unlock ZAC's beheer uses; forced unlock without the scope needs the client of zrc-007 to exclude `geforceerd` too | `tests/component/openzaak/test_documenten.py` |
| drc-00x | a ZIO creates an OIO with objectType zaak, also for a client with limited rights | gap | merge | into zrc-005 | `tests/component/openzaak/test_documenten.py` |
| brc-001 | besluit POST/PUT/PATCH; besluittype that does not resolve, is no besluittype, or is a concept: 400; besluittype cannot change | partly: `test_besluiten_eigenschappen.py::test_besluit_on_a_zaak` (POST) | merge | refusals as parameters | `tests/component/openzaak/test_besluiten.py` (split from `test_besluiten_eigenschappen.py`) |
| brc-002 | identificatie unique per verantwoordelijkeOrganisatie; both cannot change; generated identificatie unique | gap | port | ZAC numbers besluiten | `tests/component/openzaak/test_besluiten.py` |
| brc-003 | BIO with an informatieobject URL that does not resolve: 400 | gap | port | one test for brc-003, 004, 008 | same |
| brc-004 | BIO's besluit and informatieobject cannot change | gap | port | as brc-003 | same |
| brc-005 | a BIO creates the OIO with objectType besluit; deleting it deletes the OIO | gap | port | as zrc-005 for besluiten | same |
| brc-006 | a besluit on a zaak shows in the zaak's `/besluiten` | partly: `test_besluit_on_a_zaak` (found through the Besluiten API) | merge | one assertion | same |
| brc-007 | a besluit on a zaak whose zaaktype lacks the besluittype: 400 | gap | port | `zaaktype-mismatch` was wrong in 2019 (`issues_openzaak.md`) | same |
| brc-008 | BIO whose informatieobjecttype is not in the besluittype's: 400 | gap | port | needs the test besluittype to list the test informatieobjecttype (check snippet `openzaak_zaaktype`) | same |
| brc-009 | deleting a besluit deletes its BIOs, audittrail and OIOs | gap | port | audittrail part: `open-zaak-3` | `tests/component/openzaak/test_verwijderen.py` |
| ztc-001 | zaaktype created; a selectielijstProcestype URL that is no procestype: 400 | partly: `test_catalogi.py::test_concept_zaaktype_crud` | merge | checks Open Zaak's link to the Selectielijst API | `tests/component/openzaak/test_catalogi.py` |
| ztc-002 | resultaattype: omschrijvingGeneriek from its resultaattypeomschrijving; archiefnominatie and archiefactietermijn default to the selectielijstklasse's; wrong URLs refused | gap | port | depends on the Selectielijst API the environment reaches | `tests/component/openzaak/test_catalogi.py` |
| ztc-003 | selectielijstklasse procestermijn versus afleidingswijze (20 cases) | n/a | skip | validation matrix without environment input; Open Zaak's own tests | |
| ztc-004 | afleidingswijze versus datumkenmerk (12 cases) | n/a | skip | as ztc-003 | |
| ztc-005 | afleidingswijze versus einddatumBekend (11 cases) | n/a | skip | as ztc-003 | |
| ztc-006 | afleidingswijze zaakobject versus objecttype (11 cases) | n/a | skip | as ztc-003 | |
| ztc-007 | afleidingswijze versus registratie (10 cases) | n/a | skip | as ztc-003 | |
| ztc-008 | afleidingswijze versus procestermijn (10 cases) | n/a | skip | as ztc-003 | |
| ztc-009 | a published zaaktype, besluittype or informatieobjecttype: PUT, PATCH and DELETE refused, PATCH of eindeGeldigheid allowed | gap | port | a published type that changes breaks every zaak of it; throwaway types, removed with a Django snippet because the API refuses it | `tests/component/openzaak/test_catalogi_publicatie.py` (new) |
| ztc-010 | eigenschap, resultaattype, roltype, statustype, ZIOT of a published zaaktype: no PUT, PATCH, DELETE; which may still be added | gap | port | as ztc-009; one parametrized test | same |
| ztc-0xx | lists and details return only valid URLs (`datumGeldigheid`) | partly: `test_catalogi.py::test_zaaktype_versions` | merge | the version valid on a date | `tests/component/openzaak/test_catalogi.py` |

## 1b. OneGround "ZGW features"

| Folder | Checks | Coverage | Decision | Reason | Target |
| --- | --- | --- | --- | --- | --- |
| ZTC catalogi | read the catalogus | covered: bootstrap and `test_test_zaaktype_is_published_and_complete` | skip | covered | |
| ZTC informatieobjecttype | IOT CRUD, filters (catalogus, status, datumGeldigheid, omschrijving), HEAD ETag, DELETE of a published IOT refused | partly: bootstrap creates one | merge | refusal into ztc-009; filters skip | `test_catalogi_publicatie.py` |
| ZTC zaaktype | build a zaaktype with types, publish, statustype volgnummer order, roltype added after publishing, expand | partly: `test_concept_zaaktype_crud`, `test_zaaktype_versions` | merge | "added after publishing" is ztc-010 | `test_catalogi_publicatie.py` |
| zaakobjecttype | zaakobjecttype CRUD on a concept, DELETE after publishing | gap | port | Open Archiefbeheer reads zaakobjecttypen (Catalogi 1.3) | `test_catalogi.py` |
| Geldigheid | overlapping validity: two concepts or concept and published allowed, two published refused | partly: `test_zaaktype_versions` (adjacent) | merge | the refusal | `test_catalogi_publicatie.py` |
| Besluittype | besluittype with zaaktypen and IOTs, PATCH, resultaattype with besluittype | partly: bootstrap | skip | the rules are brc-007, brc-008 | |
| different catalogi | same IOT, BT, ZT in two catalogi | gap | skip | needs a second catalogus; the client must stay on the test catalogus | |
| ZRC zaak maken en wijzigen | deelzaak, eigenschap, resultaat, rol per betrokkeneType (NP, NNP, vestiging, medewerker, organisatorische eenheid), locatie, contactmoment, HEAD, ETag | partly: `test_rollen_of_two_kinds`, `test_rol_of_a_company`, `test_zaakgeometrie_and_zoek_within` | merge | rol of a vestiging, medewerker and organisatorische eenheid as parameters; ETag as below | `test_statussen_rollen.py` |
| ZRC zaak zoekopties | 55 filters on GET /zaken and `_zoek` | partly: BSN, zaaktype, archiefnominatie, geometry, paging | merge | one parametrized test on identificatie, startdatum, einddatum, archiefactiedatum, rol filters; ZAC and OAB filter this way | `tests/component/openzaak/test_zaken_zoeken.py` (new) |
| ZRC rollen | rol by vestigingsNummer, ETag, rol without naam refused | partly: `test_rol_of_a_company` | merge | into the rol parameters | `test_statussen_rollen.py` |
| ZRC contactmomenten | zaakcontactmoment | n/a | skip | needs a Contactmomenten API v1; PodiumD links klantcontacten in Open Klant 2 (`test_klantcontact_zaak.py`) | |
| Voeg documenten aan de zaak toe | upload and link | covered: `test_document_linked_to_zaak` | skip | covered | |
| ZRC ZaakInformatieObjecten | PUT, PATCH; zaak and informatieobject fixed | gap | merge | zrc-004 | `test_documenten.py` |
| ZRC zaakstatus | statussen by statustype, `indicatieLaatstGezetteStatus`, zaak | partly: `test_statussen_in_order` | merge | one assertion | `test_statussen_rollen.py` |
| ZRC archiefactiedatum obv datumeigenschap | archiefactiedatum from a date eigenschap | gap | merge | zrc-021c | `test_archivering.py` |
| ZRC Zaakresultaat | list, detail, ETag, HEAD | partly: `test_zaak_closes_with_resultaat_and_eindstatus` | skip | the ETag check goes in the ETag test | |
| ZRC zaakobject | read a zaakobject | covered: `test_zaakobject_adres` | skip | covered | |
| ZRC zaakvertrouwelijkheid | vertrouwelijkheid from the zaaktype | partly | merge | zrc-009 | `test_zaken.py` |
| CHECK expand | `expand` on zaak, deelzaak, resultaat, rol, documents | gap | port | Open Zaak 1.29.3 fixed expand showing objects the token may not read: expand as the openbaar client must not show a vertrouwelijk document | `test_autorisaties.py` |
| zaakklantcontact | ZRC klantcontacten | n/a | skip | as ZRC contactmomenten | |
| DRC Voeg info toe aan laatste document | gebruiksrechten, lock, PATCH of verschijningsvorm, vervallen, trefwoorden, read an older version | partly: `test_document_versions_and_definitief` | merge | read `?versie=1` after version 3 | `test_documenten.py` |
| DRC Identificatie uniek | document identificatie unique per bronorganisatie on POST and PATCH | gap | port | ZAC and the Office add-in number documents | `test_documenten.py` |
| DRC Maak verzending aan en check | verzending CRUD, filters, ETag | gap | skip | no PodiumD flow in this suite writes verzendingen; revisit when one does | |
| DRC Expand | expand on EIO and gebruiksrechten | n/a | skip | Documenten API 1.6, Open Zaak 1.31.0 | |
| DRC zoekopties | EIO by informatieobjecttype, bronorganisatie, trefwoorden | partly: perf `oz_documenten_ordered` | skip | low value | |
| DRC ETag | HEAD and GET with `If-None-Match`, new ETag after a change | gap | port | one ETag test for zaak, rol, resultaat and document; likely reproduces Open Zaak #2577 on 1.29.3 | `tests/component/openzaak/test_etag.py` (new) |
| Besluit | besluit with BIO | partly: `test_besluit_on_a_zaak` | merge | brc-003 to 005 | `test_besluiten.py` |
| DRC 1.7 | tonenAanInitiator, isGereedVoorPublicatie, `_zoek` on EIO | n/a | skip | not in Open Zaak 1.29.3; tonenAanInitiator (Documenten 1.6) decides what Open Inwoner shows: port once PodiumD ships Open Zaak 1.31 | |
| ZRC 1.7 | expand on `_zoek`, medewerker with a long identificatie, `reserveer_zaaknummer` | gap | port | `reserveer_zaaknummer` exists since Open Zaak 1.18; `_zoek` expand from 1.30.0 (skip below) | `test_zaken.py` |
| AC | alleenIsGereedVoorPublicatie | n/a | skip | Autorisaties API rights | |
| Bug fix single zaakinformatieobject handler | a client without rights on the document cannot create or read the ZIO | gap | port | rights leak between Zaken and Documenten | `test_autorisaties.py` |

## 2a. VNG `ZGW_api_postman_tests.json`: rules not in 1a

The other 52 rule groups have the ids of table 1a and the same cases.

| Rule | Checks | Coverage | Decision | Reason | Target |
| --- | --- | --- | --- | --- | --- |
| drc-005 | ontvangstdatum with status `in_bewerking` or `ter_vaststelling`: 400 on POST, PUT, PATCH | gap | merge | one parameter set of the document validation | `test_documenten.py` |
| ztc-011 | besluittype, eigenschap, resultaattype, roltype, statustype or zaaktype relating to a published zaaktype: refused; ZIOT allowed | gap | merge | into ztc-010 | `test_catalogi_publicatie.py` |
| ztc-012 | publishing a zaaktype with a concept besluittype or informatieobjecttype: 400 | gap | port | concepts only, deletable | `test_catalogi_publicatie.py` |
| ztc-013 | relations to types of another catalogus refused | gap | skip | needs a second catalogus | |

## 2b. VNG `ZGW_OAS_tests.json`

Per resource the status codes of its operations, plus expand and the Catalogi historiemodel.

| Folder | Checks | Coverage | Decision | Reason | Target |
| --- | --- | --- | --- | --- | --- |
| ZRC zaken | zaak CRUD, `_zoek`, audittrail, zaakbesluiten, zaakeigenschappen CRUD | partly: `test_zaak_lifecycle`, `test_zaakeigenschap` | skip | the zaak audittrail is the only gap; low value | |
| ZRC klantcontacten | ZRC klantcontacten | n/a | skip | as 1b | |
| ZRC resultaten | resultaat CRUD | partly | skip | status codes only | |
| ZRC statussen | list, create | covered: `test_statussen_in_order` | skip | covered | |
| ZRC rollen | list, create | covered: `test_rollen_of_two_kinds` | skip | covered | |
| ZRC zaakobjecten | zaakobject CRUD | partly: `test_zaakobject_adres` | skip | status codes only | |
| ZRC zaakinformatieobjecten | ZIO CRUD | partly | merge | zrc-003, 004 | `test_documenten.py` |
| ZRC expand | 10 expand paths on a zaak, keys and non-empty arrays | gap | merge | into the expand test of 1b | `test_autorisaties.py` |
| DRC enkelvoudiginformatieobjecten | EIO CRUD, lock, download, audittrail | covered: `test_documenten.py` | skip | covered | |
| DRC gebruiksrechten | gebruiksrechten CRUD | partly | merge | drc-006 | `test_documenten.py` |
| DRC objectinformatieobjecten | list | gap | merge | zrc-005 | `test_documenten.py` |
| ZTC zaaktypen | CRUD, publish | covered: `test_catalogi.py` | skip | covered | |
| ZTC catalogussen | read | covered | skip | covered | |
| ZTC besluittypen, eigenschappen, informatieobjecttypen, resultaattypen, roltypen, statustypen, zaaktype-informatieobjecttypen (7 folders) | CRUD and publish per type | partly: bootstrap snippet `openzaak_zaaktype` creates them in Django, not through the API | skip | the publication rules are ztc-009 to 012 | |
| ZTC historiemodel | relations named by omschrijving or identificatie resolve to the latest version; a ZIOT adds its IOT to the zaaktype | gap | port | ZAC and Open Formulieren name types by identificatie; recheck of `issues_openzaak.md` | `test_catalogi_publicatie.py` |
| BRC besluiten | besluit CRUD, audittrail | partly: `test_besluit_on_a_zaak` | merge | brc-001 | `test_besluiten.py` |
| BRC besluitinformatieobjecten | BIO CRUD | gap | merge | brc-003 to 005 | `test_besluiten.py` |
| NRC abonnement | abonnement CRUD | partly: `test_kanalen_abonnementen.py` (create, refusals) | skip | PUT and PATCH: low value | |
| NRC kanaal | list, create, read | covered: `test_kanaal_has_the_filters_tests_use`, `test_kanaal_name_is_unique` | skip | covered | |
| NRC notificaties | publish | covered: `tests/integration/test_notificaties.py` | skip | covered | |
| AC applicaties | applicatie CRUD | n/a | skip | Autorisaties API rights | |

## 3. Nijmegen Open Forms Playwright suite

21 specs for Nijmegen's own forms against its acceptance Open Forms with Signicat's DigiD simulator. The forms do
not exist in PodiumD; only the patterns port.

| Pattern | Source | Coverage | Decision | Reason | Target |
| --- | --- | --- | --- | --- | --- |
| P1 fail with a clear message when Open Forms answers "Bad Request (400)" after the DigiD callback | `authentication/digid-simulator.ts` | partly: `test_formulier_login.py::submit_after_login` waits until the URL leaves `/callback`, then the submission fails without naming the 400 | merge | a broken OIDC chain then fails at the login with the page's heading | `tests/integration/test_formulier_login.py` (or `browser.keycloak_login` if more flows need it) |
| P2 form logic blocks "Volgende" with a message (8 `disable-next` and `blokkeert` specs) | `forms/*/*-disable-next.pw.ts` | gap | port | logic rules are form configuration that upgrades break (`test_open_formulieren_finds_no_broken_forms` only checks definitions); bootstrap: a logic rule on the test form | `tests/integration/test_formulier_logica.py` (new) |
| P3 uploads of 109 B, 13 kB, 555 kB, 1.5 MB | `helpers/file-upload.ts`, `upload-fixtures/` | partly: `test_upload_of_a_false_file_is_refused` (content type) | port | a file above the form's maximum size refused, below it accepted and in the zaak's PDF bijlage; fixtures generated at run time | `tests/component/openformulieren/test_formulier_api.py` |
| P4 repeating group: add, save and edit a row | `helpers/repeating-group.ts` | gap | port, last | an editgrid field mapped to the registration; needs a second field type in the test form | `tests/integration/test_formulier_zaak.py` |
| P5 Flatpickr date fields by label | `helpers/open-forms-date.ts` | n/a | skip | the suite fills forms through the API | |
| P6 happy flows of Nijmegen's forms (12 specs) | `forms/*-happy-flow.pw.ts` | n/a | skip | forms are not in PodiumD | |
| P7 one capture per form step, lanes per BSN | `utils/form-artifacts.ts`, `docs/parallel-testresources.md` | partly: pytest-playwright's failure traces; `xdist_group` per shared identity | skip | covered by the runner | |

## 4. VNG `gemma-zaken-test-integratie`

| Module | Checks | Coverage | Decision | Reason | Target |
| --- | --- | --- | --- | --- | --- |
| `test_notificatie_zrc_to_drc.py` | kanaal, abonnement, a zaak notifies the subscriber | covered: `test_notificaties.py::test_zaak_changes_are_notified_with_their_resource` | skip | covered | |
| `test_registreer_besluiten.py` | besluit on a zaak; BIO once; the relation must exist in Besluiten before Documenten | gap | merge | brc-005, drc-003, drc-004 | `test_besluiten.py`, `test_documenten.py` |
| `test_registreer_zaakdocument.py` | ZIO once; the relation must exist in Zaken before Documenten | gap | merge | zrc-005, drc-003, drc-004 | `test_documenten.py` |
| `test_userstory_171.py` | document added to a zaak | covered: `test_document_linked_to_zaak` | skip | covered | |
| `test_userstory_39.py` | melding overlast: zaak with location, status and document | covered: `test_zaakgeometrie_and_zoek_within`, `test_statussen_in_order`, `test_document_linked_to_zaak` | skip | covered | |
| `test_userstory_42.py` | zaken within a geometry | covered: `test_zaakgeometrie_and_zoek_within` | skip | covered | |
| `test_userstory_45.py` | behandelaar rol from the zaaktype's roltype | partly: `test_rollen_of_two_kinds` | skip | covered enough | |
| `test_userstory_52.py` | zaakeigenschappen | covered: `test_zaakeigenschap` | skip | covered | |
| `test_zaak_afsluiten.py` | einddatum equals the eindstatus' datumStatusGezet; eindstatus refused while a document lacks indicatieGebruiksrecht | partly | merge | zrc-007a, b, q | `test_zaak_afsluiten.py` |
| `test_zaak_archiefactiedatum.py` | archiefactiedatum = brondatum + the resultaattype's archiefactietermijn, exact date | partly | merge | the bootstrap resultaattype has archiefactietermijn 3650 days and afleidingswijze afgehandeld: assert einddatum + 3650 days | `test_statussen_rollen.py::test_zaak_closes_with_resultaat_and_eindstatus` |

## 5. Performance profiles

`tests/perf` runs Locust (`src/podiumd_tests/perf/locustfile.py`): each user makes every call of `ENDPOINTS` once
per round, 1 s apart; `perf.yaml` holds the p95 and failure thresholds, per endpoint where set.

| Case | Checks | Coverage | Decision | Reason | Target |
| --- | --- | --- | --- | --- | --- |
| dmf `eio_list` (25 %) | EIO list | partly: `oz_documenten_ordered` | skip | covered | |
| dmf `eio_get` (40 %) | EIO detail | gap | port | ZAC and the portal read documents one by one | `locustfile.py` `_openzaak_calls`, `runs.ENDPOINTS` |
| dmf `eio_create` (15 %) | EIO create with content | gap | port | the write path ZAC and Open Formulieren use; distinct bestandsnamen (`open-zaak-4`) | same |
| dmf `eio_patch` (10 %) | lock, PATCH, unlock | gap | port | timed as one call | same |
| dmf `oio_list` (5 %) | OIO list | gap | port | Open Zaak resolves the relation on every document page of ZAC | same |
| dmf `oio_create` (5 %) | OIO create | gap | port as `oz_zio_create` | in Open Zaak an OIO without a ZIO is refused (drc-004): time the ZIO create, which creates the OIO | same |
| dmf weighted mix | 40/25/15/10/5/5 | gap | skip | the round of calls gives each endpoint its own p95; weights add no check | |
| dmf ramp | ramping-vus 1 m up, 5 m steady, 1 m down, 50 VUs | gap | skip | `--users` and `--run-time` already set the load; a ramp only shapes it | |
| dmf per-operation p50/p95 thresholds | p50 < 60 ms, p95 < 200 ms | covered: `perf.yaml` `endpoints` overrides | skip | covered; dmf's numbers fit its own PoC, not Open Zaak | |
| Open Notificaties `POST /notificaties`, 1 to 100 VUs | the one call that matters for Open Notificaties | gap | port | bootstrap: a kanaal `ptest-bootstrap-perf` whose only abonnement is the mock server, so no app receives the load | `locustfile.py`, `runs.ENDPOINTS` |

## 6. podiumd-adapter

The adapter (chart `podiumd`, `kiss.adapter`, service `kiss-adapter`) translates KISS's ZGW and Klanten calls to
the e-Suite; Smoelenboek reads the Objecten registration. podiumd-infra deploys it with `deploy-adapter.yml` to
test00 to test02; minikube and kees00 do not run it. Its tests mock every upstream call.

| Test class | Checks | Coverage | Decision | Reason | Target |
| --- | --- | --- | --- | --- | --- |
| `AuthTests` | `/healthz` 200; every route 401 without a token | gap | port | needs only the adapter; capability `kiss-adapter` | `tests/smoke/test_kiss_adapter.py` (new) |
| `SmoelenboekTests` | volledige naam mapped to achternaam | gap | port | reads Objecten, which PodiumD has; needs a Medewerker object, whose objecttype bootstrap already has (`ITA_OBJECTTYPES`); check it is the adapter's `SMOELENBOEK_OBJECT_TYPE_URL` | `tests/component/kiss/test_kiss_adapter.py` (new) |
| `GetZakenTests` | forward to the e-Suite, intern zaaknummer as identificatie, ordering mapped | gap | port with a mock e-Suite, else skip | the e-Suite is external | same |
| `ContactmomentenTests` | GET and POST forwarded, contactverzoek mapped | gap | as `GetZakenTests` | | same |
| `PostZaakContactmomentenTests` | 204 | gap | as `GetZakenTests` | | same |
| `KlantenTests` | forward | gap | as `GetZakenTests` | | same |
| `InterneTaakTests` | POST answers the adapter's URL, mapping, filters, paging | gap | as `GetZakenTests` | | same |
| `UrlRewriteIntegrationTest` | URLs in bodies rewritten both ways | gap | as `GetZakenTests` | | same |
| `UrlRewritePipeWriterTest` | buffer splitting | n/a | skip | unit test | |

Feasible: a smoke test (`/healthz`, 401 without a token, 200 with KISS's client token from the adapter's Secret)
on an environment that runs the adapter. The forwarding and mapping cases need the e-Suite; on a test environment
the mock server (`infra/`) could play it, as it plays Worldline, but pointing the adapter's `ESUITE_BASE_URL` at it
is the environment owner's configuration: a request in `docs/handoff/` to podiumd-minikube or podiumd-infra.

## Order of work

Each batch is one or a few commits. Days include unit tests for new `src/` helpers and a run on minikube and
kees00.

### Batch 1: validation of a zaak's own fields (1 day, 2 tests)

- Rules: zrc-001 (other resource, concept zaaktype), zrc-002 (PATCH), zrc-009, zrc-010 (negative), zrc-011, zrc-012,
  zrc-013, zrc-014, zrc-015.
- Files: extend the parameters of `tests/component/openzaak/test_validatie.py` with a PUT/PATCH variant of the same
  test; zrc-002 and zrc-009 in `test_zaken.py`.
- Bootstrap: none; the concept zaaktype comes from `make_concept_zaaktype`, the second zaak's identificatie from
  `make_zaak`.
- Risks: refused writes leave nothing. A communicatiekanaal URL makes Open Zaak call out; a network policy that
  blocks it turns 400 into a timeout or 500 (check egress on kees00).

### Batch 2: zaak relations and the zaak-document link (1.5 days, 5 tests)

- Rules: zrc-003, zrc-004, zrc-005, zrc-016 to 020, drc-001 (concept IOT), drc-002 to 004, drc-00x; recheck of
  `issues_openzaak.md` (ZIO with an invalid URL); integration modules `test_registreer_zaakdocument.py` and the
  OIO half of `test_registreer_besluiten.py`.
- Files: `test_documenten.py` (ZIO fixed fields, OIO mirrors ZIO, OIO refusals), new `test_zaaktype_consistentie.py`
  (types of the BPMN zaaktype refused on a zaak of the test zaaktype).
- Bootstrap: none; the BPMN zaaktype (step `zac-bpmn-process`) is in the test catalogus. Without ZAC that step does
  not run: skip zrc-016 to 020 there, or add a minimal second zaaktype to snippet `openzaak_zaaktype`.
- Risks: a wrongly accepted OIO or ZIO is a relation `delete_zaak(with_documents=True)` must also remove; register
  each one in `ResourceRegistry`.

### Batch 3: closing and reopening (1.5 days, 4 tests)

- Rules: zrc-007, zrc-008, zrc-022, drc-006, drc-009 forced unlock; integration module `test_zaak_afsluiten.py`.
- Files: new `tests/component/openzaak/test_zaak_afsluiten.py`; drc-006 and drc-009 in `test_documenten.py`.
- Bootstrap: client `ptest-bootstrap-zgw-gesloten` via `openzaak_client_step(exclude=("geforceerd", "heropenen"))`,
  its secret in the credentials Secret; fixture next to `openzaak_openbaar`.
- Risks: a closed zaak with a resultaat answers 500 on DELETE (`open-zaak-1`) while it is deleted: cleanup must
  accept that (`delete_zaak` does). DELETE of a resultaat on a closed zaak may hit the same defect. A wrong 2xx
  changes only the test's own zaak.

### Batch 4: archiving dates (2 days, 3 tests)

- Rules: zrc-021 (all six afleidingswijzen), zrc-022 refusals, 1b "archiefactiedatum obv datumeigenschap"; exact
  date of `test_zaak_archiefactiedatum.py` in `test_zaak_closes_with_resultaat_and_eindstatus`.
- Files: new `tests/component/openzaak/test_archivering.py`.
- Bootstrap: zaaktype `ptest-bootstrap-archief` in snippet `openzaak_zaaktype`, with a date eigenschap, a hoofdzaaktype
  and one resultaattype per afleidingswijze (same Selectielijst procestype as the test zaaktype).
- Risks: needs the Selectielijst API at bootstrap (skips as today). Closed zaken with an archiefactiedatum are what
  Open Archiefbeheer lists for destruction: choose termijnen that put every archiefactiedatum years ahead, and run
  with the `openarchiefbeheer` tests in one `xdist_group` if their lists select by date.

### Batch 5: deleting and its cascades (1 day, 3 tests)

- Rules: zrc-023, drc-008, brc-009.
- Files: new `tests/component/openzaak/test_verwijderen.py`.
- Bootstrap: none.
- Risks: the zaak with a resultaat hits `open-zaak-1` (build the cascade without a resultaat, plus one xfail case);
  audittrail reads need the catalogus rights of `test_document_audittrail_with_catalogus_rights` (`open-zaak-3`).

### Batch 6: besluiten (1 day, 4 tests)

- Rules: brc-001 to 008; integration module `test_registreer_besluiten.py`.
- Files: split `test_besluiten_eigenschappen.py` into `test_besluiten.py` and `test_zaakeigenschappen.py`.
- Bootstrap: the test besluittype lists the test informatieobjecttype (snippet `openzaak_zaaktype`; check before).
- Risks: `make_besluit` registers the besluit; BIOs and their OIOs go with it.

### Batch 7: documents (1 day, 3 tests)

- Rules: drc-005, drc-007, 1b "DRC Identificatie uniek", 1b "read an older version".
- Files: `test_documenten.py`.
- Risks: none beyond the registry.

### Batch 8: catalogus publication (2 days, 5 tests)

- Rules: ztc-001, ztc-002, ztc-009 to 012, ztc-0xx, 1b Geldigheid and zaakobjecttype, 2b historiemodel.
- Files: new `tests/component/openzaak/test_catalogi_publicatie.py`; ztc-001, ztc-002 and ztc-0xx in
  `test_catalogi.py`.
- Bootstrap: a snippet that deletes published types with the run tag in their omschrijving, since the API refuses it
  (rule ztc-009 itself); `sweep` calls it for leftovers.
- Risks: `catalogi.schrijven` is not limited to the test catalogus: every request names the test catalogus, never
  the bootstrap zaaktypen. Never PUT the bootstrap's published types: if Open Zaak wrongly accepts it, every other
  test's zaaktype changes.

### Batch 9: reads across rights (1.5 days, 4 tests)

- Rules: 1b CHECK expand and 2b ZRC expand (expand as the openbaar client hides a vertrouwelijk document), 1b ZIO
  rights fix, 1b zoekopties, 1b rol per betrokkeneType, `reserveer_zaaknummer`; 1b and 2b ETag cases as one test.
- Files: `test_autorisaties.py`, new `test_zaken_zoeken.py`, `test_statussen_rollen.py`, new `test_etag.py`.
- Risks: the ETag test likely fails on Open Zaak 1.29.3 (#2577, fixed in 1.31.1): reproduce, register, then xfail
  below 1.31.1.

### Batch 10: performance (2 days)

- Cases: `oz_document_get`, `oz_document_create`, `oz_document_patch`, `oz_oio_list`, `oz_zio_create`;
  `onrc_notificatie`.
- Files: `src/podiumd_tests/perf/locustfile.py` (`_openzaak_calls`, a new `_opennotificaties_calls`),
  `runs.ENDPOINTS`, `perf.yaml` if a threshold differs.
- Bootstrap: kanaal `ptest-bootstrap-perf` with one abonnement on the mock server (bootstrap may add kanalen; it never
  removes those of podiumd-minikube).
- Risks: write-heavy, so a non-smoke run that takes the minikube lock. Each write's cleanup runs after its timing
  (`ResourceRegistry`). Deleting the abonnement during a delivery answers 500 (`open-notificaties-2`): remove it
  only after the run.

### Batch 11: Open Formulieren patterns (2.5 days, 3 tests)

- Patterns: P1, P2, P3; P4 only if the user wants it.
- Files: `test_formulier_login.py`, new `test_formulier_logica.py`, `test_formulier_api.py`.
- Bootstrap: snippet `openformulieren_form`: a logic rule that disables the next step on one answer, and a file field
  with a maximum size.
- Risks: changes to the shared test form reach every Open Formulieren test: add a second step instead of changing
  the first.

### Batch 12: podiumd-adapter (1 day; 2 more with a mock e-Suite)

- Cases: `AuthTests`, `SmoelenboekTests`; the rest only after the handoff.
- Files: `tests/smoke/test_kiss_adapter.py`, `tests/component/kiss/test_kiss_adapter.py`; `COMPONENTS` and
  `Capabilities` learn `kiss-adapter`.
- Risks: no environment of this suite runs the adapter today: the tests skip until one does.

## Licence notes

podiumd-tests declares no licence (no LICENSE file, no `license` in `pyproject.toml`). Until it does, copying from
an EUPL source has no compatible target; reimplement instead. Rule ids and rule texts come from the ZGW standard
itself, so naming them in `@pytest.mark.source` is fine for every source.

| Source | Licence | Copy test data or text? | Plan |
| --- | --- | --- | --- |
| OneGround `ZGW-APIs-postman-tests` | BSD-3-Clause, © 2025 Visma Roxit B.V. | yes, with the copyright notice and licence text kept next to what is copied; no endorsement | reimplement in Python anyway (Postman scripts do not port); cite in `@pytest.mark.source` |
| VNG `gemma-postman-tests` | EUPL (version not stated), © VNG Realisatie 2019 | not without licensing podiumd-tests under the EUPL or a compatible licence | reimplement the scenarios; no request bodies or test texts |
| Nijmegen `open-forms-testautomatisering` | EUPL-1.2 | as VNG; the upload fixtures are not needed: generate files of the sizes at run time | reimplement the patterns |
| VNG `gemma-zaken-test-integratie` | none declared (all rights reserved by default) | no | reimplement only |
| Baseflow `cg-dmf-poc` | EUPL (`LICENSE.md`, © 2025) | as VNG; the mix and thresholds are facts | reimplement |
| Open Notificaties docs | EUPL, © Dimpact 2019 to 2020 | as VNG | reimplement (one call) |
| `podiumd-adapter` | EUPL, © VNG Realisatie 2018 (template licence file) | as VNG | reimplement; nothing of the C# tests is reusable |
