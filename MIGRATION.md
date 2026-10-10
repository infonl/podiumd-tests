# Migration triage

One row per source test file. Decision: **port** (carry over), **merge** (fold into another or a parametrized test),
**drop** (dead, Hetzner/KIND leftover, duplicate), **replace** (by a CLI command), or **todo** (not triaged yet).
See PLAN.md §10. Generated 2026-10-05 from the source repositories; edit the Decision and Notes columns by hand.

Sources:

- TA: `icatt-menselijk-digitaal/podiumd-testautomation/podiumd-4.9.0/test-automation/tests`
- MK: `infonl/podiumd-minikube/tests`
- PI: `icatt-menselijk-digitaal/podiumd-infra/tests`
- EX: `scctwente/ExternalsPodiumD/smoke-tests/tests/smoke`

## TA

| Test | Target | Phase | Decision | Notes |
|---|---|---|---|---|
| `debug/debug-portaal-mijn-zaken-cache.spec.ts` | — | — | drop | |
| `debug/esuite-form-selectors.spec.ts` | — | — | drop | |
| `debug/esuite-route-discovery.spec.ts` | — | — | drop | |
| `interaction/02-zaak-creatie.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openzaak/` test_zaken.py: lifecycle. |
| `interaction/03-document-koppeling.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openzaak/` test_documenten.py: document linked to zaak. |
| `interaction/09-ok2-klantcontact.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openklant/` test_klantcontacten.py: roundtrip, actor link. |
| `interaction/10-cross-component-zaak-portaal.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | Open Zaak part → `test_statussen_rollen.py` (zaak found by initiator BSN); Portaal part → `test_inwoners_zaak_is_in_mijn_zaken` (`tests/integration/test_portaal_zaken.py`). |
| `interaction/105-portaal-profiel-edit.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py` (formsets in this OI). |
| `interaction/107-portaal-zoeken.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openinwoner/test_portaal_anoniem.py` (anonymous; search needs no login). |
| `interaction/108-portaal-vraag-stellen-inwoner.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | Into the heading test of `tests/component/openinwoner/test_portaal_inwoner.py`; asking a question needs W8. |
| `interaction/111-portaal-documenten-uploaden.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | With 162 into `tests/integration/test_portaal_zaken.py`; bootstrap `openinwoner-zaaktype-config` configures only the test zaaktype, not TA's zgw_import_data. |
| `interaction/140-inwoner-vraag-over-zaak.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | Covered by TA 21 (zaak in Mijn zaken), 164 (question about a zaak) and 182 (Mijn vragen) in `test_portaal_zaken.py` and `test_portaal_openklant.py`. |
| `interaction/141-bedrijf-eherkenning-mijn-zaken.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`; the first eHerkenning login completes OI's registration (why TA landed elsewhere). |
| `interaction/142-oab-vernietigingslijst.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openarchiefbeheer/test_vernietigingslijst.py`; the list holds only the test's own zaak, never select_all. |
| `interaction/145-contact-lookup-flow.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | `tests/component/openklant/`: betrokkenen of a partij, internetaak by klantcontact. |
| `interaction/148-ita-doorsturen-flow.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | Its afdelingen/groepen reads are in 77 and 184. |
| `interaction/162-portaal-document-upload-e2e.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`: upload through the UI, document checked in Open Zaak. |
| `interaction/164-portaal-vraag-stellen-vanuit-zaak.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`; W6 sets the API group's klant_backend to openklant2 (esuite gave 500). |
| `interaction/168-oab-archivist-flow.spec.ts` | component or integration, marker `core` | 3/4/5 | port | Archivist accept → ready_to_delete in `test_vernietigingslijst.py`; the record manager's review response: `test_record_manager_response_sends_the_list_back_to_review` (keeps the zaak; changing its archiefactiedatum would change Open Zaak data for no extra coverage of OAB). |
| `interaction/180-ita-contactmoment-afsluiten.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/ita/test_ita_internetaken.py`; closing via an Open Klant PATCH is not ITA and is dropped. |
| `interaction/181-keten-ita-contactmoment-portaal-beantwoord.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_openklant.py`: answered in ITA (with `partijUuid`, or Mijn vragen does not list the answer), shown as Beantwoord with the answer. |
| `interaction/182-keten-contactformulier-mijn-vragen.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_openklant.py` (wiring W6/W8; no opt-in). |
| `interaction/20-klacht-journey-e2e.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | Every step is an API call an existing test makes: BRP lookup (`test_brp.py`), zaak with initiator, status and found by BSN (`test_statussen_rollen.py`), document (`test_documenten.py`), klantcontact about the zaak (`test_klantcontact_zaak.py`); the portal view of it: `test_portaal_zaken.py`. |
| `interaction/21-portaal-mijn-zaken-ui.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_zaken.py` (W4 group without zaken cache: no flush). |
| `interaction/31-document-portaal-ui.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | With 143 into `tests/integration/test_portaal_zaken.py`. |
| `interaction/32-of-submission-ui.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | With 76 into `tests/integration/test_formulier_zaak.py`: form API, submission and the zgw registration backend (proven by the registered zaak). |
| `interaction/35-ok2-partij-flow.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openklant/` test_partijen.py: persoon with BSN and e-mail. |
| `interaction/74-ita-claim-flow.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/ita/test_ita_internetaken.py`, with a numeric nummer. |
| `interaction/76-of-submission-end-to-end.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_formulier_zaak.py`: submission through the SDK API, zaak and PDF in Open Zaak. |
| `interaction/78-ita-add-klantcontact.spec.ts` | component or integration, marker `core` | 3/4/5 | drop | Superseded by 180 (outdated body). |
| `maintenance/cleanup-test-zaken.spec.ts` | `podiumd-tests sweep` (CLI, not a test) | 2 | replace | |
| `perf/api-perf.js` | perf (Locust) | 6 | port | `tests/perf/test_api_perf.py` with `src/podiumd_tests/perf/locustfile.py`; thresholds in `perf.yaml`. |
| `perf/fg-compare.js` | perf (Locust) | 6 | todo | Needs an environment with both a Frank!Gateway and a direct route to Open Zaak (TA used a temporary `openzaak-direct` host); minikube's outway is in-cluster only. |
| `perf/lib.js` | perf (Locust) | 6 | merge | Its auth helpers are the suite's own clients (`clients/platform.py`). |
| `regression/07-brp-persoon-zoeken.spec.ts` | component or integration | 3/4/5 | port | `tests/component/basisregistraties/test_brp.py`, through the api-proxy. |
| `regression/08-kvk-bedrijf-zoeken.spec.ts` | component or integration | 3/4/5 | port | `tests/component/basisregistraties/test_kvk.py` through the api-proxy, which routes to KvK's test API on every estate (TA called that API directly); test set Test BV Donald. |
| `regression/100-kiss-frontend-basis.spec.ts` | component or integration | 3/4/5 | port | `tests/component/kiss/test_anonymous.py`, health check → `tests/smoke/test_api_health.py`; the rendered app → `test_kiss_renders_for_the_kcc_user`. |
| `regression/106-portaal-notificatievoorkeur.spec.ts` | component or integration | 3/4/5 | merge | With 165 into `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `regression/108-probe-contactform.spec.ts` | component or integration | 3/4/5 | merge | With 109 into `tests/integration/test_portaal_openklant.py`; the contact page needs OpenklantApphook (bootstrap `openinwoner-cms-pages`). |
| `regression/109-portaal-vraag-stellen-bedrijf.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_portaal_openklant.py`: after an eHerkenning login the question belongs to the vestiging's partij. |
| `regression/11-of-brp-prefill.spec.ts` | component or integration | 3/4/5 | port | `test_brp.py`: V2 lookup and the V1 405; it never went through Open Formulieren. |
| `regression/110-portaal-anoniem-en-mobile.spec.ts` | component or integration | 3/4/5 | port | Contact part → `tests/component/openinwoner/test_portaal_anoniem.py`; mobile homepage: merged into `test_inwoners_zaak_is_in_mijn_zaken` (`test_portaal_zaken.py`, same devices, also checks the page fits the screen). |
| `regression/112-ita-toewijzen-actor-types.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openklant/` test_internetaken.py (pure Open Klant, despite the name). |
| `regression/114-portaal-multi-user-digid.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `regression/115-omc-notifynl-mock-keten.spec.ts` | component or integration | 3/4/5 | todo | Blocked on OMC upstream: OMC 1.17.19 (podiumd 4.9.4 and every estate) answers every notification 206 with an inner 422 on `source` (2.3.1 too, tried 2026-10-10), so minikube runs without OMC; port when a PodiumD release has an OMC that accepts them. NotifyNL calls go to the webhook receiver's `/notify`. |
| `regression/116-omc-mail-keten-e2e.spec.ts` | component or integration | 3/4/5 | todo | Blocked on OMC upstream: OMC 1.17.19 (podiumd 4.9.4 and every estate) answers every notification 206 with an inner 422 on `source` (2.3.1 too, tried 2026-10-10), so minikube runs without OMC; port when a PodiumD release has an OMC that accepts them. NotifyNL calls go to the webhook receiver's `/notify`. |
| `regression/117-portaal-contactmomenten-paginatie.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `regression/118-portaal-vestigingsnaam-bedrijf.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py`, against the KvK test API (wiring `openinwoner-kvk`). |
| `regression/119-infra-quick-wins.spec.ts` | component or integration | 3/4/5 | merge | Unknown BSN: `test_brp.py`; KISS `/api/me`: `test_kcc_session.py`. BRP postcode search: `test_brp.py`. Dropped: KISS `/api/zoeken`, which also accepted 500, and the `/kennisartikelen` fixme. |
| `regression/12-kiss-bff-kcc-flow.spec.ts` | component or integration | 3/4/5 | port | `tests/component/kiss/test_kcc_session.py`; KISS does not delete klantcontacten (405). |
| `regression/120-of-payment-infrastructure.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/platform/test_public_surface.py`. |
| `regression/121-continuiteit-graceful-degradation.spec.ts` | component or integration | 3/4/5 | port | `tests/component/platform/test_public_surface.py`; BRP and KvK parts wait for their ingress (handoff 6). |
| `regression/122-gemachtigde-flow.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py: indicatieMachtiging. |
| `regression/123-portaal-clamav-eicar-rejectie.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`; skips unless Open Inwoner's SiteConfiguration.enable_virus_scan is on (minikube runs no ClamAV). |
| `regression/124-cluster-pod-recovery-multi.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_continuiteit.py` (tier chaos). The graceful-degradation case is dropped: anonymous `/mijn-zaken/` always redirects to the login. |
| `regression/125-kvk-postcode-huisnummer-zoek.spec.ts` | component or integration | 3/4/5 | port | Same as 08. |
| `regression/13-va-filter-cross-component.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_autorisaties.py, with client ptest-bootstrap-zgw-openbaar. |
| `regression/14-audit-trail.spec.ts` | component or integration | 3/4/5 | merge | Into the strict xfail `test_document_audittrail_with_catalogus_rights` (`test_documenten.py`): Open Zaak serves audittrails only to clients with heeft_alle_autorisaties, and the suite keeps its clients at minimum scope. |
| `regression/143-oab-vernietigingsflow.spec.ts` | component or integration | 3/4/5 | port | `test_vernietigingslijst.py`, through the API (make_final works without 2FA here). UI: the record manager makes a list in the SPA (ABC-001 to 003) and sees the reviewer's proposals (ABC-011). |
| `regression/143-portaal-document-download.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`. |
| `regression/144-continuiteit-component-stop.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/integration/test_continuiteit.py`: every other component root must keep answering, not only the pairs TA checked. |
| `regression/146-portaal-uitbreiding.spec.ts` | component or integration | 3/4/5 | merge | Into the TA 118 test: the vestiging's eersteHandelsnaam from the KvK vestigingsprofiel. |
| `regression/147-kiss-contentbronnen.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/kiss/test_anonymous.py`. |
| `regression/149-ok2-crud-uitbreiding.spec.ts` | component or integration | 3/4/5 | merge | `tests/component/openklant/`: klantcontact and digitaal adres patch/delete; CRUD-3 (identificator PUT) dropped: it passed on any outcome. |
| `regression/15-status-transitions.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py: statussen in order. |
| `regression/150-of-prefill-foutpaden.spec.ts` | component or integration | 3/4/5 | port | `test_brp.py` (BSN failing the eleven-test) and `test_kvk.py` (invalid KvK numbers); the partner expand (FOUTPAD-4) stayed fixme in TA: drop. |
| `regression/151-pdok-externe-service.spec.ts` | component or integration | 3/4/5 | drop | Tests the public PDOK Locatieserver, not PodiumD. |
| `regression/152-of-retention-en-pdf.spec.ts` | component or integration | 3/4/5 | merge | With 76 into `tests/integration/test_formulier_zaak.py`: the PDF report downloads through reportDownloadUrl. |
| `regression/153-of-features-direct.spec.ts` | component or integration | 3/4/5 | merge | Cosign → `test_formulier_api.py`. Demo payment: as 185. NotifyNL mock (fixme in TA) and form variables (need a login): drop. |
| `regression/154-omc-cosign-direct.spec.ts` | component or integration | 3/4/5 | todo | OMC part blocked as 80. Open Formulieren: the paused submission's resume mail → `tests/integration/test_formulier_pauzeren.py`; cosign options and submission start: `test_formulier_api.py`. |
| `regression/156-esuite-ui-navigatie.spec.ts` | component or integration | 3/4/5 | todo | Blocked with smoke 155: eSuite is outside PodiumD and no profile has an `esuite` URL. |
| `regression/157-contact-haalcentraal-validatie.spec.ts` | component or integration | 3/4/5 | merge | KI-060 → `tests/component/openklant/` test_internetaken.py; KvK parts: phase 3, external services. |
| `regression/158-of-eherkenning-vestiging.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_formulier_login.py`: eHerkenning through Keycloak's mock (W1), the vestiging is the zaak's initiator. |
| `regression/159-of-zaak-keten.spec.ts` | component or integration | 3/4/5 | merge | With 158 into `tests/integration/test_formulier_login.py`. |
| `regression/16-bedrijf-aanvraag-kvk.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py: rol of a company (generated KvK number). |
| `regression/160-portaal-deactivated-on-pseudo-blokkade.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py`: inactive refused; deactivated_on a strict xfail (Open Inwoner's OIDC login ignores it). |
| `regression/161-portaal-low-prio-coverage.spec.ts` | component or integration | 3/4/5 | port | 161c/d → `tests/component/openinwoner/test_portaal_anoniem.py`; a/b/e/f read OI source files: dropped. |
| `regression/163-portaal-menu-kop-consistency.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `regression/165-portaal-notif-save.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `regression/166-oab-medebeoordelaar.spec.ts` | component or integration | 3/4/5 | port | `test_vernietigingslijst.py`. |
| `regression/167-fb-zaaktype-crud-api.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_catalogi.py: concept zaaktype CRUD and versions. |
| `regression/169-oab-process-review-flow.spec.ts` | component or integration | 3/4/5 | port | Rejection and the refused make_final in `test_vernietigingslijst.py`; review response: as 168. |
| `regression/17-document-va-handhaving.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_autorisaties.py. |
| `regression/170-oab-destruction-execute.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openarchiefbeheer/test_vernietigingslijst.py`: queue and abort (tier full); the real destruction of the test's own zaak is destructive and a strict xfail (Open Zaak 1.29.3 answers 500 on the zaak DELETE, so OAB marks the item failed). TA faked the deleted state in the Django shell. |
| `regression/171-oab-short-procedure.spec.ts` | component or integration | 3/4/5 | port | Same module: destructive, xdist_group with the destruction test; ArchiveConfig is restored after the test. |
| `regression/172-architectuur-wcag-axe.spec.ts` | component or integration | 3/4/5 | port | `tests/component/platform/test_toegankelijkheid.py`: axe-core WCAG 2.1 AA on the portal homepage and the test form; critical violations fail. Dropped: the KISS fixme and the required-fields check (the test form has one field). |
| `regression/173-fb-zaaktype-versie-isolatie.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openzaak/` test_catalogi.py test_zaaktype_versions. |
| `regression/174-oab-config-persist-filter.spec.ts` | component or integration | 3/4/5 | merge | r47/r48 (short-procedure zaaktypen kept in ArchiveConfig): the short-procedure test in `test_vernietigingslijst.py` sets them and depends on their effect. r9 dropped: it only checked that an input keeps typed text. |
| `regression/175-continuiteit-alertmanager-fber.spec.ts` | component or integration | 3/4/5 | drop | Alertmanager is disabled in podiumd-infra and ExternalsPodiumD; TA tested its own Alertmanager and webhook. |
| `regression/176-formulier-update-keten.spec.ts` | component or integration | 3/4/5 | drop | r102 renames the form, which plays no part in registration (covered by the TA 76 chain); r97 checks that a later submission has a later timestamp. Both fixme in TA. A real form change would alter the shared test form under parallel tests. |
| `regression/177-pen-admin-niet-publiek.spec.ts` | component or integration | 3/4/5 | port | `tests/component/platform/test_public_surface.py`. |
| `regression/178-blacklist-upload.spec.ts` | component or integration | 3/4/5 | port | Open Formulieren: `test_formulier_api.py` (a text file named .pdf, a file without extension: 400 with a reason). Open Inwoner: `test_portaal_zaken.py` (.html keeps the upload button disabled). |
| `regression/179-portaal-profiel-naar-openklant.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_portaal_openklant.py`. |
| `regression/18-klantcontact-zaak-koppeling.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_klantcontact_zaak.py`. |
| `regression/183-of-digid-zaak-rol.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_formulier_login.py` (DigiD through Keycloak's mock, wiring W1). |
| `regression/184-ita-doorsturen-mutatie.spec.ts` | component or integration | 3/4/5 | port | `tests/component/ita/test_ita_internetaken.py`; ITA wants `{"afdeling"|"groep": identificatie}`, TA's actorType body gets 400. |
| `regression/185-of-betaalstatus-zaak.spec.ts` | component or integration | 3/4/5 | drop | Needs Open Formulieren's demo payment plugin, which no estate enables (ENABLE_DEMO_PLUGINS is unset in podiumd-infra, ExternalsPodiumD and the chart); Ogone and Worldline need a real payment provider. TA kept it fixme. |
| `regression/19-notificaties-e2e.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`, with the webhook receiver of `infra/`. |
| `regression/190-kiss-contentbronnen-gevuld.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_kiss_kennis.py`: a VAC and a kennisartikel in Objecten become findable in KISS's search after their elastic-sync job. This KISS has no `/api/elasticsearch` proxy; it searches through `/api/search`. |
| `regression/191-ita-poller-split.spec.ts` | component or integration | 3/4/5 | drop | CronJob names and schedules are estate configuration; failed Jobs are caught by `tests/smoke/test_cluster.py`. The reminder job `ita-verlopen-cv-notify` is off in every estate (podiumd default, DRT-726). |
| `regression/193-frankgateway-zac-openzaak-e2e.spec.ts` | component or integration | 3/4/5 | port | ZAC's BRP and KvK lookups → `tests/component/zac/test_zac_klanten.py`. The Frank!Gateway route ZAC → Open Zaak exists in no estate; rollen: `test_statussen_rollen.py`. |
| `regression/22-negative-auth.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_autorisaties.py, with client ptest-bootstrap-zgw-noauth. |
| `regression/23-va-escalatie.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openzaak/` test_autorisaties.py. |
| `regression/24-zaakeigenschappen.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_besluiten_eigenschappen.py, on bootstrap eigenschap kenteken. |
| `regression/25-abonnement-filter.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`. |
| `regression/26-multi-subscriber.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`. |
| `regression/27-status-event-keten.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`. |
| `regression/28-gerelateerde-zaken.spec.ts` | component or integration | 3/4/5 | merge | With 59 into `tests/component/openzaak/` test_zaken.py test_relevante_andere_zaken. |
| `regression/29-besluit-op-zaak.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_besluiten_eigenschappen.py, on the bootstrap besluittype. |
| `regression/30-rol-event.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`. |
| `regression/33-zaak-update-event.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`. |
| `regression/34-zio-events.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`. |
| `regression/36-zaakobject-koppeling.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_zaken.py. |
| `regression/37-ok2-partij-events.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`. |
| `regression/38-concurrency-uniqueness.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_zaken.py: unique identificatie under parallel creates. |
| `regression/39-zaak-lifecycle-close.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py, extended with closing by resultaat and eindstatus. |
| `regression/40-brp-zoek-criteria.spec.ts` | component or integration | 3/4/5 | port | `tests/component/basisregistraties/test_brp.py`. |
| `regression/41-multi-rollen-zaak.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py. |
| `regression/42-notif-retry.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`. |
| `regression/43-pagineren-filtering.spec.ts` | component or integration | 3/4/5 | merge | With 55 into `tests/component/openzaak/` test_zaken.py (ApiClient.list follows every page). |
| `regression/44-validation-edge-cases.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_validatie.py, each invalid field named in invalidParams. |
| `regression/45-internetaak-event.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`. |
| `regression/46-rol-delete-event.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_notificaties.py`. |
| `regression/47-kvk-edge-cases.spec.ts` | component or integration | 3/4/5 | port | `test_kvk.py`, with the KvK test set, as 08. |
| `regression/48-audit-trail-acties.spec.ts` | component or integration | 3/4/5 | merge | As 14. |
| `regression/49-document-download.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openzaak/` test_documenten.py test_document_versions_and_definitief. |
| `regression/50-zaak-zoeken.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openzaak/` test_statussen_rollen.py test_zaak_found_by_initiator_bsn. |
| `regression/51-document-crud-edges.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openzaak/` test_documenten.py. |
| `regression/52-zaak-geometrie.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_zaken.py. |
| `regression/53-on-kanaal-validation.spec.ts` | component or integration | 3/4/5 | port | `tests/component/opennotificaties/`; abonnement validation uses the webhook receiver of `infra/`; unreachable callback gives 500 (xfail). |
| `regression/54-ok2-conversation-tree.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openklant/` test_partijen.py test_betrokkenen_of_a_partij. |
| `regression/55-multi-zaaktype.spec.ts` | component or integration | 3/4/5 | merge | With 43 into `tests/component/openzaak/` test_zaken.py. |
| `regression/56-zaak-rel-batch.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py; its inpBsn__in filter does not exist (xfail: _zoek ignores unknown filters). |
| `regression/57-kvk-prefill.spec.ts` | component or integration | 3/4/5 | port | `tests/component/basisregistraties/test_kvk.py`, with the KvK test set. |
| `regression/58-ok2-expand.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openklant/` test_partijen.py. |
| `regression/59-zaak-relatie-keten.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_zaken.py test_relevante_andere_zaken. |
| `regression/60-seed-data-health.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openzaak/` test_catalogi.py, on the bootstrap zaaktype. |
| `regression/61-mobile-mijn-zaken.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`: iPhone 13 and Pixel 5 descriptors in Chromium; no cache flush (W4 has no zaken cache), so no retries. |
| `regression/62-vergetelheid-categorieen.spec.ts` | component or integration | 3/4/5 | drop | Its assertions check the test's own classification logic, not PodiumD; the Open Klant objects it creates are covered by `tests/component/openklant/`. |
| `regression/63-klacht-bezwaar-keten.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_klacht_bezwaar.py`; the audit trail check is left out (needs `heeft_alle_autorisaties`, see 14/48). |
| `regression/64-document-lifecycle.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_documenten.py; its audittrail part is an xfail. |
| `regression/65-oi-cache-webhook.spec.ts` | component or integration | 3/4/5 | port | 65a/b → `tests/component/openinwoner/test_portaal_anoniem.py`; 65c/d: dropped (hardcoded kube context). |
| `regression/67-pabc-functional-roles.spec.ts` | component or integration | 3/4/5 | port | `tests/component/pabc/test_management.py` (browser session). |
| `regression/68-pabc-decision.spec.ts` | component or integration | 3/4/5 | port | 68b/68c → `tests/component/pabc/test_api_key.py`; 68a → `test_management.py`. |
| `regression/69-pabc-domains-entity-types.spec.ts` | component or integration | 3/4/5 | port | `tests/component/pabc/test_management.py`. |
| `regression/70-pabc-groups-lookup.spec.ts` | component or integration | 3/4/5 | drop | TA's GET passed on PABC's SPA page (200 HTML); the endpoint answers POST 401 even with the API key. PABC's API: `tests/component/pabc/`. |
| `regression/71-pabc-zac-integration-coherence.spec.ts` | component or integration | 3/4/5 | port | `tests/component/pabc/test_management.py`. |
| `regression/73-ita-assigned-list.spec.ts` | component or integration | 3/4/5 | merge | Into the claim test of `tests/component/ita/test_ita_internetaken.py`. |
| `regression/75-ita-forward-flow.spec.ts` | component or integration | 3/4/5 | drop | Superseded by 184. |
| `regression/75-of-zaaktype-matching.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openformulieren/test_formulier_api.py`: active form, its field, login options. |
| `regression/76-ita-close-with-klantcontact.spec.ts` | component or integration | 3/4/5 | drop | The route does not exist (405); covered by 180. |
| `regression/77-ita-afdelingen-groepen.spec.ts` | component or integration | 3/4/5 | port | `tests/component/ita/test_ita_internetaken.py`. |
| `regression/79-of-form-cosign-config.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openformulieren/test_formulier_api.py`: the published settings. |
| `regression/80-brp-kvk-prefill-foutpaden.spec.ts` | component or integration | 3/4/5 | port | BRP parts → `test_brp.py`, basisprofiel and searches → `test_kvk.py` (KvK test set). |
| `regression/80-omc-listen-event.spec.ts` | component or integration | 3/4/5 | todo | Blocked on OMC upstream: OMC 1.17.19 (podiumd 4.9.4 and every estate) answers every notification 206 with an inner 422 on `source` (2.3.1 too, tried 2026-10-10), so minikube runs without OMC; port when a PodiumD release has an OMC that accepts them. NotifyNL calls go to the webhook receiver's `/notify`. |
| `regression/81-omc-confirm-callback.spec.ts` | component or integration | 3/4/5 | todo | Blocked on OMC upstream: OMC 1.17.19 (podiumd 4.9.4 and every estate) answers every notification 206 with an inner 422 on `source` (2.3.1 too, tried 2026-10-10), so minikube runs without OMC; port when a PodiumD release has an OMC that accepts them. NotifyNL calls go to the webhook receiver's `/notify`. |
| `regression/82-omc-zaak-e2e.spec.ts` | component or integration | 3/4/5 | todo | Blocked on OMC upstream: OMC 1.17.19 (podiumd 4.9.4 and every estate) answers every notification 206 with an inner 422 on `source` (2.3.1 too, tried 2026-10-10), so minikube runs without OMC; port when a PodiumD release has an OMC that accepts them. NotifyNL calls go to the webhook receiver's `/notify`. |
| `regression/83-portaal-anonieme-pagina-bereikbaarheid.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_anoniem.py`. |
| `regression/84-portaal-ingelogd-sessie.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_login.py`: Mijn zaken while logged in, the login page after /digid-oidc/logout/. |
| `regression/85-ok2-bedrijf-partij.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openklant/` test_partijen.py: organisatie with KvK or RSIN. |
| `regression/86-ok2-klantcontact-bedrijf.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openklant/`. |
| `regression/87-ok2-klantcontact-zoeken.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openklant/` test_klantcontacten.py. |
| `regression/88-pdok-locatieserver.spec.ts` | component or integration | 3/4/5 | drop | Tests the public PDOK Locatieserver, not PodiumD. |
| `regression/89-cluster-pod-recovery.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/integration/test_continuiteit.py` (openinwoner is one of the stopped components). |
| `regression/90-fb-oz-catalogi-integriteit.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openzaak/` test_catalogi.py. |
| `regression/91-fb-keycloak-realm-snapshot.spec.ts` | component or integration | 3/4/5 | port | `tests/component/keycloak/test_realm.py`. |
| `regression/95-portaal-filtering.spec.ts` | component or integration | 3/4/5 | merge | Test 1 → `test_portaal_inwoner.py`-style login, test 2 → `tests/integration/test_portaal_zaken.py`. |
| `regression/96-portaal-profiel-navigatie.spec.ts` | component or integration | 3/4/5 | merge | Into the heading test of `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `smoke/00-environment-preflight.spec.ts` | smoke | 1 | port | 00c/00d/00h/00i/00j/00k/00l → `test_reachability.py`, `test_api_health.py`; 00f → `test_cluster.py` (all workloads ready). Phase 3: 00e (ZAC schemas, psql) and 00g (OZ Applicatie scopes for Open Inwoner). 00i form slug needs bootstrap data (phase 2). |
| `smoke/01-zgw-auth.spec.ts` | smoke | 1 | port | `test_zgw_auth.py`: token accepted, wrong secret refused. Phase 2: the catalogus domein and test zaaktype checks need seeded data. |
| `smoke/04-portaal-homepage.spec.ts` | smoke | 1 | port | HTTP part → `test_reachability.py`; the rendered homepage → `tests/component/openinwoner/test_portaal_anoniem.py` and the WCAG scan in `test_toegankelijkheid.py`. |
| `smoke/05-portaal-digid-login.spec.ts` | smoke | 1 | port | 5a and the first leg of 5b → `test_oidc.py`; the DigiD login → `tests/component/openinwoner/test_portaal_login.py`. |
| `smoke/06-kiss-bff-healthz.spec.ts` | smoke | 1 | port | `/healthz` and `/api/healthcheck` → `test_api_health.py`; the rendered app → `test_kiss_renders_for_the_kcc_user` (`tests/component/kiss/test_kcc_session.py`). |
| `smoke/113-kiss-kcc-login-flow.spec.ts` | smoke | 1 | port | `tests/component/kiss/test_kcc_session.py` (`ui`). |
| `smoke/155-esuite-smoke-login.spec.ts` | smoke | 1 | todo | Blocked: eSuite is outside PodiumD and no profile has an `esuite` URL and credentials. |
| `smoke/192-frankgateway-health.spec.ts` | smoke | 1 | port | `test_frankgateway.py`; skips unless the profile has a `frankgateway` (outway) URL. Not in EX. |
| `smoke/66-pabc-health.spec.ts` | smoke | 1 | port | API-key checks → `test_api_health.py`; the app version after login → `test_app_version_is_shown_after_login` (`tests/component/pabc/test_management.py`). |
| `smoke/72-ita-health-kanalen.spec.ts` | smoke | 1 | port | Anonymous → `test_api_health.py`; logged in → `test_kanalen_answer_the_kcc_user` (`tests/component/ita/test_ita_internetaken.py`). |
| `smoke/79-omc-health.spec.ts` | smoke | 1 | port | Anonymous check → `test_api_health.py`. Phase 3: `/Events/Version` with an OMC JWT (needs OMC secret settings). |
| `smoke/81-continuiteit-pings.spec.ts` | smoke | 1 | merge | Into `test_reachability.py` (root of every component under 5 s, admin login pages) and `test_api_health.py`. |
| `smoke/82-portaal-login-config.spec.ts` | smoke | 1 | port | `test_oidc.py`: theme, DigiD links, 'Log in met DigiD', redirect to Keycloak. The exact count of 2 DigiD links (mobile and desktop) is not asserted: it is layout, not wiring. |
| `smoke/92-fb-cross-component-sso.spec.ts` | smoke | 1 | port | `tests/integration/test_sso.py`, for every Django app whose admin logs in through Keycloak, with the test admin from bootstrap. |
| `smoke/99-portaal-eherkenning-login.spec.ts` | smoke | 1 | port | Test 1 and the first leg of test 2 → `test_oidc.py`; the eHerkenning login → `test_portaal_login.py`; the account's KvK → `test_company_profile_shows_kvk_names`. |

## MK

| Test | Target | Phase | Decision | Notes |
|---|---|---|---|---|
| `test_browser.py` | smoke, marker `ui` | 1/5 | port | `tests/component/zac/test_zac_login.py` (ZAC dashboard after the Keycloak login). |
| `test_database.py` | component, marker `cluster` | 3 | port | `tests/component/platform/test_django_apps.py`, through each app's own Django connection. |
| `test_django_admin_login.py` | component, marker `cluster` | 3 | port | `tests/component/platform/test_django_apps.py`; skips where admin login is SSO. |
| `test_login_flow.py` | smoke (ZAC OIDC login) | 1 | port | First leg → `test_oidc.py`; the login → `test_zac_login.py`. |
| `test_mailpit.py` | integration | 4 | merge | `tests/integration/test_mail.py`: every Django app's mail, and a sent mail shown in Mailpit's web UI (`test_sent_mail_shows_in_the_mailpit_ui`). |
| `test_metrics.py` | smoke | 1 | merge | With `test_monitoring_logging.py` into `test_metrics.py`; datasources found by type, not by name. |
| `test_monitoring_logging.py` | smoke | 1 | merge | Into `test_metrics.py`; the Loki check runs where a Loki datasource exists. |
| `test_pabc_migrations_guard.py` | component, marker `destructive` | 3 | drop | Tests a podiumd-minikube script, and changes the cluster. |
| `test_pkce.py` | component (keycloak) | 3 | port | `tests/component/keycloak/test_pkce.py`, with PABC's PKCE login round trip and the ita/kiss clients not requiring PKCE (handed over 2026-10-08); ZAC's experimental PKCE not ported (a minikube chart switch). |
| `test_pods.py` | smoke | 1 | port | `test_cluster.py`: pods judged by owner (Job, CronJob) instead of per-estate prefix lists; core pod list dropped (every Deployment and StatefulSet must be ready). |
| `test_productaanvraag_flow.py` | integration, marker `core` | 4 | merge | `tests/integration/test_productaanvraag.py`; the Objects API registration check → `test_objects_api_registrations_are_valid` (every active form); Job and kanaal checks via `test_jobs_succeeded` and the kanalen tests. |
| `test_reachability.py` | smoke | 1 | port | `test_reachability.py`: redirects followed (R14), status < 500 per component plus admin login pages; no per-host expected codes. |
| `test_zgw_service_reachability.py` | integration, marker `cluster` | 4 | port | `tests/component/platform/test_django_apps.py` (snippet `zgw_services`), for every Django app and also external APIs. |
| `test_api_proxy.py` | component | 3 | port | KvK and BRP → `test_kvk.py`, `test_brp.py`; BAG → `tests/component/basisregistraties/test_bag.py`. |
| `test_clamav.py` | — | — | drop | clamdscan in minikube's ClamAV pod (its EICAR-only database); the application check is `test_infected_upload_is_refused`. |
| `test_edge.py` | — | — | drop | The body limit of minikube's edge, which imitates ExternalsPodiumD's gateway; an estate setting, not PodiumD behaviour. |
| `test_frankgateway.py` | smoke | 1 | merge | Outway routes → `tests/smoke/test_frankgateway.py` (now BRP V2 `/personen`); OpenBao unsealed and ZAC's ConfigMap: minikube's own deploy. |
| `test_kiss_ita.py` | component | 3 | merge | Health and anonymous ITA → `test_api_health.py`; objecttypes → `tests/component/objecten/test_objecttypen.py` (by name); Elasticsearch health and chunked forwarding: minikube's deploy (forwarding also through `test_kiss_reads_itas_logboek`). |
| `test_memory.py` | — | — | drop | minikube's memory budget and baseline. |
| `test_omc.py` | smoke | 1 | todo | Anonymous `/Events/Listen` → `test_api_health.py`; `/Events/Version` with a JWT blocked with the OMC tests (spec 80). |

## PI

| Test | Target | Phase | Decision | Notes |
|---|---|---|---|---|
| `test_4_8_5_upgrade.py` | component (deployment hygiene) + known_issues | 3 | drop | Pinned images of one environment's 4.8.5 upgrade. |
| `test_browser.py` | smoke, marker `ui` | 1/5 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_database.py` | component, marker `cluster` | 3 | port | `tests/component/platform/test_django_apps.py`, through each app's own Django connection. |
| `test_django_admin_login.py` | component, marker `cluster` | 3 | port | `tests/component/platform/test_django_apps.py`; skips where admin login is SSO. |
| `test_login_flow.py` | smoke (ZAC OIDC login) | 1 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_mailpit.py` | integration | 4 | merge | `tests/integration/test_mail.py`: every Django app's mail, and a sent mail shown in Mailpit's web UI (`test_sent_mail_shows_in_the_mailpit_ui`). |
| `test_metrics.py` | smoke | 1 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_monitoring_logging.py` | smoke | 1 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_pabc_migrations_guard.py` | component, marker `destructive` | 3 | drop | Tests a podiumd-minikube script, and changes the cluster. |
| `test_pkce.py` | component (keycloak) | 3 | port | `tests/component/keycloak/test_pkce.py`, with PABC's PKCE login round trip and the ita/kiss clients not requiring PKCE (handed over 2026-10-08); ZAC's experimental PKCE not ported (a minikube chart switch). |
| `test_pods.py` | smoke | 1 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_productaanvraag_flow.py` | integration, marker `core` | 4 | merge | `tests/integration/test_productaanvraag.py`; the Objects API registration check → `test_objects_api_registrations_are_valid` (every active form); Job and kanaal checks via `test_jobs_succeeded` and the kanalen tests. |
| `test_reachability.py` | smoke | 1 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_zac_zaakafhandelparameters.py` | component (zac) | 3 | port | `tests/component/zac/test_zac_zaakafhandelparameters.py`, for the profile's `productaanvraag_zaaktype`. |
| `test_zgw_service_reachability.py` | integration, marker `cluster` | 4 | merge | same test in MK and PI: one environment-neutral test in `test_django_apps.py`. |

## EX

| Test | Target | Phase | Decision | Notes |
|---|---|---|---|---|
| `00-environment-preflight.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `01-zgw-auth.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `04-portaal-homepage.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `05-portaal-digid-login.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `06-kiss-bff-healthz.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `113-kiss-kcc-login-flow.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `155-esuite-smoke-login.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `66-pabc-health.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `72-ita-health-kanalen.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `79-omc-health.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `81-continuiteit-pings.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `82-portaal-login-config.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `92-fb-cross-component-sso.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |
| `99-portaal-eherkenning-login.spec.ts` | smoke | 1 | merge | same spec number as TA `smoke/`; port once, environment-neutral |

## Draaiboek

Draaiboek cases of class A or B that no test covers on purpose, and why; `python -m podiumd_tests.draaiboek` reports
them as out of scope with this reason.

| Cases | Reason |
|---|---|
| OF-055, OF-057, OF-058, OF-072, OI-022, OI-024, OI-030, OI-032, OI-047, OI-049, OI-052, OI-053, OI-067, KI-021, KI-022 | eSuite, outside PodiumD |
| ARCH-008, ARCH-014 | legal check, no system behaviour |
| OI-016, OI-070 | DigiD machtigen, which Open Inwoner 2.4.3 does not support |
| OF-074 | a gemeente's own TSA |
| OFA-001, OFA-003, OFA-005, OFA-006, OFA-011 | Office add-in, outside PodiumD |
| FB-001, FB-002, ZAC-001 | AD login, which no estate has |
| ABC-003 | traceable selection, not in Open Archiefbeheer 2.0.0 |
| ITA-022 | organisation-wide list, not in ITA 3.3 |
| INT-006 | Signicat's real DigiD broker |
| CONT-056, CONT-057, CONT-058, CONT-059 | DigiD or eHerkenning down needs the real broker chain; the mocks log in at Keycloak |
| CONT-045 | SmartDocuments down needs a SmartDocuments mock, which no environment has |
| CONT-001, CONT-002, CONT-006, KETEN-001 | heading, no case |
| CONT-046, CONT-047, CONT-050, CONT-051, CONT-052, CONT-053, CONT-054, CONT-055 | expected result "?", and the catalog lost which connection |
| OF-066, OF-069 | the case does not say what to check |
| OI-100 | no case: "beheer tests toevoegen" |
