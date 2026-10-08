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
| `interaction/10-cross-component-zaak-portaal.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | Open Zaak part → `tests/component/openzaak/` test_statussen_rollen.py (zaak found by initiator BSN); Portaal part: phase 5. |
| `interaction/105-portaal-profiel-edit.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py` (formsets in this OI). |
| `interaction/107-portaal-zoeken.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openinwoner/test_portaal_anoniem.py` (anonymous; search needs no login). |
| `interaction/108-portaal-vraag-stellen-inwoner.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | Into the heading test of `tests/component/openinwoner/test_portaal_inwoner.py`; asking a question needs W8. |
| `interaction/111-portaal-documenten-uploaden.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | With 162 into `tests/integration/test_portaal_zaken.py`; bootstrap `openinwoner-zaaktype-config` configures only the test zaaktype, not TA's zgw_import_data. |
| `interaction/140-inwoner-vraag-over-zaak.spec.ts` | component or integration, marker `core` | 3/4/5 | todo | |
| `interaction/141-bedrijf-eherkenning-mijn-zaken.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`; the first eHerkenning login completes OI's registration (why TA landed elsewhere). |
| `interaction/142-oab-vernietigingslijst.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openarchiefbeheer/test_vernietigingslijst.py`; the list holds only the test's own zaak, never select_all. |
| `interaction/145-contact-lookup-flow.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | `tests/component/openklant/`: betrokkenen of a partij, internetaak by klantcontact. |
| `interaction/148-ita-doorsturen-flow.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | Its afdelingen/groepen reads are in 77 and 184. |
| `interaction/162-portaal-document-upload-e2e.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`: upload through the UI, document checked in Open Zaak. |
| `interaction/164-portaal-vraag-stellen-vanuit-zaak.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`; W6 sets the API group's klant_backend to openklant2 (esuite gave 500). |
| `interaction/168-oab-archivist-flow.spec.ts` | component or integration, marker `core` | 3/4/5 | port | Archivist accept → ready_to_delete in `test_vernietigingslijst.py`; review-responses that change archiefactiedatum: todo. |
| `interaction/180-ita-contactmoment-afsluiten.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/ita/test_ita_internetaken.py`; closing via an Open Klant PATCH is not ITA and is dropped. |
| `interaction/181-keten-ita-contactmoment-portaal-beantwoord.spec.ts` | component or integration, marker `core` | 3/4/5 | todo | |
| `interaction/182-keten-contactformulier-mijn-vragen.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_openklant.py` (wiring W6/W8; no opt-in). |
| `interaction/20-klacht-journey-e2e.spec.ts` | component or integration, marker `core` | 3/4/5 | todo | |
| `interaction/21-portaal-mijn-zaken-ui.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_portaal_zaken.py` (W4 group without zaken cache: no flush). |
| `interaction/31-document-portaal-ui.spec.ts` | component or integration, marker `core` | 3/4/5 | merge | With 143 into `tests/integration/test_portaal_zaken.py`. |
| `interaction/32-of-submission-ui.spec.ts` | component or integration, marker `core` | 3/4/5 | todo | |
| `interaction/35-ok2-partij-flow.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/openklant/` test_partijen.py: persoon with BSN and e-mail. |
| `interaction/74-ita-claim-flow.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/component/ita/test_ita_internetaken.py`, with a numeric nummer. |
| `interaction/76-of-submission-end-to-end.spec.ts` | component or integration, marker `core` | 3/4/5 | port | `tests/integration/test_formulier_zaak.py`: submission through the SDK API, zaak and PDF in Open Zaak. |
| `interaction/78-ita-add-klantcontact.spec.ts` | component or integration, marker `core` | 3/4/5 | drop | Superseded by 180 (outdated body). |
| `maintenance/cleanup-test-zaken.spec.ts` | `podiumd-tests sweep` (CLI, not a test) | 2 | replace | |
| `perf/api-perf.js` | perf (Locust) | 6 | todo | |
| `perf/fg-compare.js` | perf (Locust) | 6 | todo | |
| `perf/lib.js` | perf (Locust) | 6 | todo | |
| `regression/07-brp-persoon-zoeken.spec.ts` | component or integration | 3/4/5 | port | `tests/component/basisregistraties/test_brp.py`, through the api-proxy. |
| `regression/08-kvk-bedrijf-zoeken.spec.ts` | component or integration | 3/4/5 | port | `tests/component/basisregistraties/test_kvk.py` through the api-proxy, which routes to KvK's test API on every estate (TA called that API directly); test set Test BV Donald. |
| `regression/100-kiss-frontend-basis.spec.ts` | component or integration | 3/4/5 | port | `tests/component/kiss/test_anonymous.py`; the Vue shell check is phase 5. |
| `regression/106-portaal-notificatievoorkeur.spec.ts` | component or integration | 3/4/5 | merge | With 165 into `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `regression/108-probe-contactform.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/109-portaal-vraag-stellen-bedrijf.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/11-of-brp-prefill.spec.ts` | component or integration | 3/4/5 | port | `test_brp.py`: V2 lookup and the V1 405; it never went through Open Formulieren. |
| `regression/110-portaal-anoniem-en-mobile.spec.ts` | component or integration | 3/4/5 | port | Contact part → `tests/component/openinwoner/test_portaal_anoniem.py`; mobile homepage: todo. |
| `regression/112-ita-toewijzen-actor-types.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openklant/` test_internetaken.py (pure Open Klant, despite the name). |
| `regression/114-portaal-multi-user-digid.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `regression/115-omc-notifynl-mock-keten.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/116-omc-mail-keten-e2e.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/117-portaal-contactmomenten-paginatie.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `regression/118-portaal-vestigingsnaam-bedrijf.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/119-infra-quick-wins.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/12-kiss-bff-kcc-flow.spec.ts` | component or integration | 3/4/5 | port | `tests/component/kiss/test_kcc_session.py`; KISS does not delete klantcontacten (405). |
| `regression/120-of-payment-infrastructure.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/platform/test_public_surface.py`. |
| `regression/121-continuiteit-graceful-degradation.spec.ts` | component or integration | 3/4/5 | port | `tests/component/platform/test_public_surface.py`; BRP and KvK parts wait for their ingress (handoff 6). |
| `regression/122-gemachtigde-flow.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py: indicatieMachtiging. |
| `regression/123-portaal-clamav-eicar-rejectie.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`; skips unless Open Inwoner's SiteConfiguration.enable_virus_scan is on (minikube runs no ClamAV). |
| `regression/124-cluster-pod-recovery-multi.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/125-kvk-postcode-huisnummer-zoek.spec.ts` | component or integration | 3/4/5 | port | Same as 08. |
| `regression/13-va-filter-cross-component.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_autorisaties.py, with client ptest-bootstrap-zgw-openbaar. |
| `regression/14-audit-trail.spec.ts` | component or integration | 3/4/5 | todo | Open Zaak audittrails need heeft_alle_autorisaties (xfail in test_documenten.py); decide on a client with full rights. |
| `regression/143-oab-vernietigingsflow.spec.ts` | component or integration | 3/4/5 | port | `test_vernietigingslijst.py`, through the API (make_final works without 2FA here); UI steps: todo. |
| `regression/143-portaal-document-download.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_portaal_zaken.py`. |
| `regression/144-continuiteit-component-stop.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/146-portaal-uitbreiding.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/147-kiss-contentbronnen.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/kiss/test_anonymous.py`. |
| `regression/149-ok2-crud-uitbreiding.spec.ts` | component or integration | 3/4/5 | merge | `tests/component/openklant/`: klantcontact and digitaal adres patch/delete; CRUD-3 (identificator PUT) dropped: it passed on any outcome. |
| `regression/15-status-transitions.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py: statussen in order. |
| `regression/150-of-prefill-foutpaden.spec.ts` | component or integration | 3/4/5 | port | `test_brp.py` (BSN failing the eleven-test) and `test_kvk.py` (invalid KvK numbers); the partner expand (FOUTPAD-4) stayed fixme in TA: drop. |
| `regression/151-pdok-externe-service.spec.ts` | component or integration | 3/4/5 | drop | Tests the public PDOK Locatieserver, not PodiumD. |
| `regression/152-of-retention-en-pdf.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/153-of-features-direct.spec.ts` | component or integration | 3/4/5 | merge | Cosign → `test_formulier_api.py`. Demo payment: as 185. NotifyNL mock (fixme in TA) and form variables (need a login): drop. |
| `regression/154-omc-cosign-direct.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/156-esuite-ui-navigatie.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/157-contact-haalcentraal-validatie.spec.ts` | component or integration | 3/4/5 | merge | KI-060 → `tests/component/openklant/` test_internetaken.py; KvK parts: phase 3, external services. |
| `regression/158-of-eherkenning-vestiging.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/159-of-zaak-keten.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/16-bedrijf-aanvraag-kvk.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py: rol of a company (generated KvK number). |
| `regression/160-portaal-deactivated-on-pseudo-blokkade.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/161-portaal-low-prio-coverage.spec.ts` | component or integration | 3/4/5 | port | 161c/d → `tests/component/openinwoner/test_portaal_anoniem.py`; a/b/e/f read OI source files: dropped. |
| `regression/163-portaal-menu-kop-consistency.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `regression/165-portaal-notif-save.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `regression/166-oab-medebeoordelaar.spec.ts` | component or integration | 3/4/5 | port | `test_vernietigingslijst.py`. |
| `regression/167-fb-zaaktype-crud-api.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_catalogi.py: concept zaaktype CRUD and versions. |
| `regression/169-oab-process-review-flow.spec.ts` | component or integration | 3/4/5 | port | Rejection and the refused make_final in `test_vernietigingslijst.py`; review-responses: todo. |
| `regression/17-document-va-handhaving.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_autorisaties.py. |
| `regression/170-oab-destruction-execute.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openarchiefbeheer/test_vernietigingslijst.py`: queue and abort (tier full); the real destruction of the test's own zaak is destructive and a strict xfail (Open Zaak 1.29.3 answers 500 on the zaak DELETE, so OAB marks the item failed). TA faked the deleted state in the Django shell. |
| `regression/171-oab-short-procedure.spec.ts` | component or integration | 3/4/5 | port | Same module: destructive, xdist_group with the destruction test; ArchiveConfig is restored after the test. |
| `regression/172-architectuur-wcag-axe.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/173-fb-zaaktype-versie-isolatie.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openzaak/` test_catalogi.py test_zaaktype_versions. |
| `regression/174-oab-config-persist-filter.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/175-continuiteit-alertmanager-fber.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/176-formulier-update-keten.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/177-pen-admin-niet-publiek.spec.ts` | component or integration | 3/4/5 | port | `tests/component/platform/test_public_surface.py`. |
| `regression/178-blacklist-upload.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/179-portaal-profiel-naar-openklant.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_portaal_openklant.py`. |
| `regression/18-klantcontact-zaak-koppeling.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_klantcontact_zaak.py`. |
| `regression/183-of-digid-zaak-rol.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_formulier_digid.py` (DigiD through Keycloak's mock, wiring W1). |
| `regression/184-ita-doorsturen-mutatie.spec.ts` | component or integration | 3/4/5 | port | `tests/component/ita/test_ita_internetaken.py`; ITA wants `{"afdeling"|"groep": identificatie}`, TA's actorType body gets 400. |
| `regression/185-of-betaalstatus-zaak.spec.ts` | component or integration | 3/4/5 | drop | Needs Open Formulieren's demo payment plugin, which no estate enables (ENABLE_DEMO_PLUGINS is unset in podiumd-infra, ExternalsPodiumD and the chart); Ogone and Worldline need a real payment provider. TA kept it fixme. |
| `regression/19-notificaties-e2e.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_zaak_notificaties.py`, with the webhook receiver of `infra/`. |
| `regression/190-kiss-contentbronnen-gevuld.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/191-ita-poller-split.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/193-frankgateway-zac-openzaak-e2e.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/22-negative-auth.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_autorisaties.py, with client ptest-bootstrap-zgw-noauth. |
| `regression/23-va-escalatie.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openzaak/` test_autorisaties.py. |
| `regression/24-zaakeigenschappen.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_besluiten_eigenschappen.py, on bootstrap eigenschap kenteken. |
| `regression/25-abonnement-filter.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/26-multi-subscriber.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/27-status-event-keten.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/28-gerelateerde-zaken.spec.ts` | component or integration | 3/4/5 | merge | With 59 into `tests/component/openzaak/` test_zaken.py test_relevante_andere_zaken. |
| `regression/29-besluit-op-zaak.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_besluiten_eigenschappen.py, on the bootstrap besluittype. |
| `regression/30-rol-event.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/33-zaak-update-event.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/34-zio-events.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/36-zaakobject-koppeling.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_zaken.py. |
| `regression/37-ok2-partij-events.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/38-concurrency-uniqueness.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_zaken.py: unique identificatie under parallel creates. |
| `regression/39-zaak-lifecycle-close.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py, extended with closing by resultaat and eindstatus. |
| `regression/40-brp-zoek-criteria.spec.ts` | component or integration | 3/4/5 | port | `tests/component/basisregistraties/test_brp.py`. |
| `regression/41-multi-rollen-zaak.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_statussen_rollen.py. |
| `regression/42-notif-retry.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/43-pagineren-filtering.spec.ts` | component or integration | 3/4/5 | merge | With 55 into `tests/component/openzaak/` test_zaken.py (ApiClient.list follows every page). |
| `regression/44-validation-edge-cases.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_validatie.py, each invalid field named in invalidParams. |
| `regression/45-internetaak-event.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/46-rol-delete-event.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/47-kvk-edge-cases.spec.ts` | component or integration | 3/4/5 | port | `test_kvk.py`, with the KvK test set, as 08. |
| `regression/48-audit-trail-acties.spec.ts` | component or integration | 3/4/5 | todo | As 14: audittrails need heeft_alle_autorisaties. |
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
| `regression/62-vergetelheid-categorieen.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/63-klacht-bezwaar-keten.spec.ts` | component or integration | 3/4/5 | port | `tests/integration/test_klacht_bezwaar.py`; the audit trail check is left out (needs `heeft_alle_autorisaties`, see 14/48). |
| `regression/64-document-lifecycle.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openzaak/` test_documenten.py; its audittrail part is an xfail. |
| `regression/65-oi-cache-webhook.spec.ts` | component or integration | 3/4/5 | port | 65a/b → `tests/component/openinwoner/test_portaal_anoniem.py`; 65c/d: dropped (hardcoded kube context). |
| `regression/67-pabc-functional-roles.spec.ts` | component or integration | 3/4/5 | port | `tests/component/pabc/test_management.py` (browser session). |
| `regression/68-pabc-decision.spec.ts` | component or integration | 3/4/5 | port | 68b/68c → `tests/component/pabc/test_api_key.py`; 68a → `test_management.py`. |
| `regression/69-pabc-domains-entity-types.spec.ts` | component or integration | 3/4/5 | port | `tests/component/pabc/test_management.py`. |
| `regression/70-pabc-groups-lookup.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/71-pabc-zac-integration-coherence.spec.ts` | component or integration | 3/4/5 | port | `tests/component/pabc/test_management.py`. |
| `regression/73-ita-assigned-list.spec.ts` | component or integration | 3/4/5 | merge | Into the claim test of `tests/component/ita/test_ita_internetaken.py`. |
| `regression/75-ita-forward-flow.spec.ts` | component or integration | 3/4/5 | drop | Superseded by 184. |
| `regression/75-of-zaaktype-matching.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openformulieren/test_formulier_api.py`: active form, its field, login options. |
| `regression/76-ita-close-with-klantcontact.spec.ts` | component or integration | 3/4/5 | drop | The route does not exist (405); covered by 180. |
| `regression/77-ita-afdelingen-groepen.spec.ts` | component or integration | 3/4/5 | port | `tests/component/ita/test_ita_internetaken.py`. |
| `regression/79-of-form-cosign-config.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openformulieren/test_formulier_api.py`: the published settings. |
| `regression/80-brp-kvk-prefill-foutpaden.spec.ts` | component or integration | 3/4/5 | port | BRP parts → `test_brp.py`, basisprofiel and searches → `test_kvk.py` (KvK test set). |
| `regression/80-omc-listen-event.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/81-omc-confirm-callback.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/82-omc-zaak-e2e.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/83-portaal-anonieme-pagina-bereikbaarheid.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openinwoner/test_portaal_anoniem.py`. |
| `regression/84-portaal-ingelogd-sessie.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/85-ok2-bedrijf-partij.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openklant/` test_partijen.py: organisatie with KvK or RSIN. |
| `regression/86-ok2-klantcontact-bedrijf.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openklant/`. |
| `regression/87-ok2-klantcontact-zoeken.spec.ts` | component or integration | 3/4/5 | port | `tests/component/openklant/` test_klantcontacten.py. |
| `regression/88-pdok-locatieserver.spec.ts` | component or integration | 3/4/5 | drop | Tests the public PDOK Locatieserver, not PodiumD. |
| `regression/89-cluster-pod-recovery.spec.ts` | component or integration | 3/4/5 | todo | |
| `regression/90-fb-oz-catalogi-integriteit.spec.ts` | component or integration | 3/4/5 | merge | Into `tests/component/openzaak/` test_catalogi.py. |
| `regression/91-fb-keycloak-realm-snapshot.spec.ts` | component or integration | 3/4/5 | port | `tests/component/keycloak/test_realm.py`. |
| `regression/95-portaal-filtering.spec.ts` | component or integration | 3/4/5 | merge | Test 1 → `test_portaal_inwoner.py`-style login, test 2 → `tests/integration/test_portaal_zaken.py`. |
| `regression/96-portaal-profiel-navigatie.spec.ts` | component or integration | 3/4/5 | merge | Into the heading test of `tests/component/openinwoner/test_portaal_inwoner.py`. |
| `smoke/00-environment-preflight.spec.ts` | smoke | 1 | port | 00c/00d/00h/00i/00j/00k/00l → `test_reachability.py`, `test_api_health.py`; 00f → `test_cluster.py` (all workloads ready). Phase 3: 00e (ZAC schemas, psql) and 00g (OZ Applicatie scopes for Open Inwoner). 00i form slug needs bootstrap data (phase 2). |
| `smoke/01-zgw-auth.spec.ts` | smoke | 1 | port | `test_zgw_auth.py`: token accepted, wrong secret refused. Phase 2: the catalogus domein and test zaaktype checks need seeded data. |
| `smoke/04-portaal-homepage.spec.ts` | smoke | 1 | port | HTTP part → `test_reachability.py` (root and admin login of `openinwoner`). Phase 5: the rendered-page checks need a browser. |
| `smoke/05-portaal-digid-login.spec.ts` | smoke | 1 | port | 5a and the first leg of 5b → `test_oidc.py`. Phase 5: the login itself needs a DigiD test identity (phase 2) and a browser. |
| `smoke/06-kiss-bff-healthz.spec.ts` | smoke | 1 | port | `/healthz` and `/api/healthcheck` → `test_api_health.py`. The rendered-page check moves to phase 5. |
| `smoke/113-kiss-kcc-login-flow.spec.ts` | smoke | 1 | port | `tests/component/kiss/test_kcc_session.py` (`ui`). |
| `smoke/155-esuite-smoke-login.spec.ts` | smoke | 1 | port | Phase 5 (`ui`): eSuite is outside PodiumD; needs a `esuite` URL and credentials in the profile. |
| `smoke/192-frankgateway-health.spec.ts` | smoke | 1 | port | `test_frankgateway.py`; skips unless the profile has a `frankgateway` (outway) URL. Not in EX. |
| `smoke/66-pabc-health.spec.ts` | smoke | 1 | port | API-key checks → `test_api_health.py`. Phase 5: app version behind the OIDC cookie login. |
| `smoke/72-ita-health-kanalen.spec.ts` | smoke | 1 | port | Anonymous check → `test_api_health.py`. Phase 5: logged-in `/api/kanalen` needs a KCC identity and a browser. |
| `smoke/79-omc-health.spec.ts` | smoke | 1 | port | Anonymous check → `test_api_health.py`. Phase 3: `/Events/Version` with an OMC JWT (needs OMC secret settings). |
| `smoke/81-continuiteit-pings.spec.ts` | smoke | 1 | merge | Into `test_reachability.py` (root of every component under 5 s, admin login pages) and `test_api_health.py`. |
| `smoke/82-portaal-login-config.spec.ts` | smoke | 1 | port | `test_oidc.py`: theme, DigiD links, 'Log in met DigiD', redirect to Keycloak. The exact count of 2 DigiD links (mobile and desktop) is not asserted: it is layout, not wiring. |
| `smoke/92-fb-cross-component-sso.spec.ts` | smoke | 1 | port | Phase 5 (`ui`): needs an admin identity from bootstrap instead of the hardcoded `testadmin` password. |
| `smoke/99-portaal-eherkenning-login.spec.ts` | smoke | 1 | port | Test 1 and the first leg of test 2 → `test_oidc.py`. Phase 5: login with an eHerkenning identity, and the KVK check in the Django shell. |

## MK

| Test | Target | Phase | Decision | Notes |
|---|---|---|---|---|
| `test_browser.py` | smoke, marker `ui` | 1/5 | port | Phase 5 (`ui`). |
| `test_database.py` | component, marker `cluster` | 3 | port | `tests/component/platform/test_django_apps.py`, through each app's own Django connection. |
| `test_django_admin_login.py` | component, marker `cluster` | 3 | port | `tests/component/platform/test_django_apps.py`; skips where admin login is SSO. |
| `test_login_flow.py` | smoke (ZAC OIDC login) | 1 | port | First leg (ZAC redirects to the Keycloak login form) → `test_oidc.py`. The login itself needs a test identity: phase 5. |
| `test_mailpit.py` | integration | 4 | merge | `tests/integration/test_mail.py` (every Django app, not only Open Zaak); web UI check: phase 5. |
| `test_metrics.py` | smoke | 1 | merge | With `test_monitoring_logging.py` into `test_metrics.py`; datasources found by type, not by name. |
| `test_monitoring_logging.py` | smoke | 1 | merge | Into `test_metrics.py`; the Loki check runs where a Loki datasource exists. |
| `test_pabc_migrations_guard.py` | component, marker `destructive` | 3 | drop | Tests a podiumd-minikube script, and changes the cluster. |
| `test_pkce.py` | component (keycloak) | 3 | port | `tests/component/keycloak/test_pkce.py`; MK's login round trip and ZAC experiment not ported. |
| `test_pods.py` | smoke | 1 | port | `test_cluster.py`: pods judged by owner (Job, CronJob) instead of per-estate prefix lists; core pod list dropped (every Deployment and StatefulSet must be ready). |
| `test_productaanvraag_flow.py` | integration, marker `core` | 4 | merge | `tests/integration/test_productaanvraag.py`; Job and kanaal checks are covered by `test_jobs_succeeded` and the kanalen tests. |
| `test_reachability.py` | smoke | 1 | port | `test_reachability.py`: redirects followed (R14), status < 500 per component plus admin login pages; no per-host expected codes. |
| `test_zgw_service_reachability.py` | integration, marker `cluster` | 4 | todo |  |

## PI

| Test | Target | Phase | Decision | Notes |
|---|---|---|---|---|
| `test_4_8_5_upgrade.py` | component (deployment hygiene) + known_issues | 3 | drop | Pinned images of one environment's 4.8.5 upgrade. |
| `test_browser.py` | smoke, marker `ui` | 1/5 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_database.py` | component, marker `cluster` | 3 | port | `tests/component/platform/test_django_apps.py`, through each app's own Django connection. |
| `test_django_admin_login.py` | component, marker `cluster` | 3 | port | `tests/component/platform/test_django_apps.py`; skips where admin login is SSO. |
| `test_login_flow.py` | smoke (ZAC OIDC login) | 1 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_mailpit.py` | integration | 4 | merge | `tests/integration/test_mail.py`; the PI-only skip is the `mailpit` capability. |
| `test_metrics.py` | smoke | 1 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_monitoring_logging.py` | smoke | 1 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_pabc_migrations_guard.py` | component, marker `destructive` | 3 | drop | Tests a podiumd-minikube script, and changes the cluster. |
| `test_pkce.py` | component (keycloak) | 3 | port | `tests/component/keycloak/test_pkce.py`; MK's login round trip and ZAC experiment not ported. |
| `test_pods.py` | smoke | 1 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_productaanvraag_flow.py` | integration, marker `core` | 4 | merge | `tests/integration/test_productaanvraag.py`, with profile settings instead of hard-coded types; PI's ZAC parameter check goes to the ZAC component tests. |
| `test_reachability.py` | smoke | 1 | merge | same test in MK and PI: merge into one environment-neutral test |
| `test_zac_zaakafhandelparameters.py` | component (zac) | 3 | todo |  |
| `test_zgw_service_reachability.py` | integration, marker `cluster` | 4 | merge | same test in MK and PI: merge into one environment-neutral test |

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
