# Tests in the components' own repositories

Scanned 2026-10-21, read-only, on each repository's default branch: which tests of PodiumD's components could
become podiumd-tests tests. podiumd-tests tests a deployed environment, so only scenarios that work against a
running instance count; unit tests count only as hints for edge cases. ZAC's e2e suite is already ported
(`tests/component/zac`, source marker `ZAC`).

Verdict: **port** (worth a test here), **maybe** (only under a condition), **no**.

## Summary

| Component | Repository @ commit | Tests that run against an instance | Verdict |
| --- | --- | --- | --- |
| KISS | klantinteractie-servicesysteem/KISS-frontend @ 90a79fa | `Kiss.Bff.EndToEndTest`: Playwright (C#), ~120 scenarios | port, largest gain |
| ITA | interne-taak-afhandeling/ITA @ 54056be | `InterneTaakAfhandeling.EndToEndTest`: Playwright (C#), ~140 scenarios | port, largest gain |
| ZaakBrug | wearefrank/zaakbrug @ cdd465f | `e2e/SoapUI/zaakbrug-e2e-soapui-project.xml`: 127 ZDS cases against Open Zaak | port a selection |
| ZGW Office Add-in | infonl/zgw-office-addin @ 3b74f94 | `e2e/tests`: Playwright, 10 tests (Office mocked) | maybe |
| Open Beheer | maykinmedia/open-beheer @ 7ce9f34 | ~25 Gherkin Playwright scenarios (VCR against Open Zaak) | port the write path |
| Open Archiefbeheer | maykinmedia/open-archiefbeheer @ 7d77889 | ~60 Gherkin Playwright scenarios (Open Zaak mocked) | port 3, rest covered |
| Open Inwoner | maykinmedia/open-inwoner @ 18a50ae | Playwright e2e, OIDC e2e against Keycloak, locust | port 3 |
| Open Formulieren | open-formulieren/open-forms @ 52e9a04 | Django Playwright e2e, VCR, `bin/report_component_problems.py` | port 2 |
| Open Formulieren SDK | open-formulieren/open-forms-sdk @ f9f9e4c | Storybook play tests against MSW mocks | no |
| Objecten | maykinmedia/objects-api @ b8215b2 | Postman quickstart collection, locust | port 3 |
| Open Zaak | open-zaak/open-zaak @ 9f6a26e | `performance_test/` (pytest-benchmark), performance docs | port perf endpoints, edge cases |
| Open Notificaties | open-zaak/open-notificaties @ 729ade3 | performance scenario doc only | maybe (perf) |
| OMC (NotifyNL) | Worth-NL/NotifyNL-OMC @ 0cde7cf | `EventsHandler.IntegrationTests`: 6 checks of `/Events` | covered (expired token new) |
| PABC | platform-autorisatie-beheer-component/PABC-API @ ea770ae | unit and controller tests only | no |
| Objecttypen, Open Klant, Referentielijsten, Open VTB | maykinmedia | unit tests and the shared quick-start check | no |

The Maykin repositories have no tests against a deployed stack: their e2e tests run in Django's live test server
with factories and mocked or recorded (VCR) external APIs. Their scenarios still port as podiumd-tests flows.
KISS and ITA log in through Azure AD in their own tests; here the same flows log in through Keycloak.

## Ranked: what to port first

1. **ITA**: forwarding a contactverzoek to an afdeling or groep with and without a groepsmailbox (17 cases), the
   daily reminder mail for expired contactverzoeken (8 cases, checkable in Mailpit: aggregated mail, afdeling
   without address, no personal data in the body), reopening a closed contactverzoek with logboek line (7),
   search by klantcontactnummer including one outside the user's rights (6), access to Alle contactverzoeken
   for beheerder vs medewerker (4), urgency labels with weekends excluded (12).
2. **KISS**: contactverzoek forms for afdeling and groep by phone and e-mail, with prefill from a BSN or
   vestigingsnummer and field validation (14); person search by name and date of birth, BSN, postcode and
   huisnummer, and company search by name, KvK and vestigingsnummer, found and not found (21); contactmoment
   registered on a zaak (4); two vragen in one contactmoment (8); beheer of kanalen, gespreksresultaten and
   skills (12, cleaned up afterwards); nieuws en werkinstructies with read markers and pagination.
3. **Open Beheer**: create a concept zaaktype from the template, edit it, add statustype and roltype, delete
   the concept through the Catalogi API (`test_22`, `test_24`, `test_25`). Publishing leaves residue: maybe.
4. **Objecten**: an object that breaks its objecttype's JSON schema gets 400 naming the field; PUT/PATCH adds
   a record, `/history` lists both, `?date=` and `?registrationDate=` return the older one; creating an object
   notifies kanaal `objecten`.
5. **ZaakBrug**: a selection of the SoapUI cases in Python: verlenging (valid, duur 0, empty reden ignored),
   kenmerken, status with an existing datumStatusGezet, document update refused once definitief, role changes
   by verwerkingssoort (T, W, V, I). Each suite creates and deletes its own zaaktype.
6. **Open Formulieren**: follow the mailed resume link, finish and submit the paused submission
   (`test_resume_form.py`; `test_formulier_pauzeren.py` stops at the mail); the admin designer pages render
   their JS bundle marker `data-testid="e2e-test-id"` (`test_admin_js.py`).
7. **Open Archiefbeheer**: a zaak deleted in Open Zaak while on a list does not break review and processing;
   reassign the reviewer, also after changes were requested; delete a new list, refused past status new.
8. **Open Inwoner**: a repeat DigiD or eHerkenning login reuses the account (one User per BSN or KvK);
   admin OIDC login through Keycloak; profile edit validation (duplicate or malformed e-mail, malformed phone)
   and adding and deleting a contact detail.
9. **Open Zaak**: perf endpoints for the documenten list with a deep page and ordering, and the zaken list for
   a client limited to a few vs many zaaktypen (PodiumD's clients are never superuser); two documents with the
   same file name created at the same time keep their own content (CHANGELOG #2592); `laatstGemuteerd` follows
   a new status, rol or document (#2308).
10. **Maybe**: Office Add-in zaak search and upload through its frontend (needs its Office mock page); Open
    Formulieren backend refusal of an invalid BSN, e-mail or date (needs those fields in the test form) and
    `report_component_problems.py` as a post-upgrade check; Open Inwoner Mijn zaken cards for paused
    submissions where an estate shows them; OMC `/Events/Listen` with an expired token; Open Notificaties and
    Objecten throughput in the perf tier; CloudEvents only where an estate turns on `ENABLE_CLOUD_EVENTS`.

## Not ported, and why

- Admin and designer UI details (Open Formulieren form designer, Open Zaak object history, Objecten permission
  admin, sorting and filter widgets of Open Archiefbeheer and Open Beheer): no system behaviour beyond the UI.
- Writes to shared configuration (Open Inwoner CMS homepage editing, publishing objecttypes or zaaktypen,
  select-all in Open Archiefbeheer): they leave residue or touch other users' data.
- Recorded or mocked integrations (VCR tests of BRP, BRK, Signicat; SDK MSW stories): replay, not a test of
  the environment; the live paths are covered by `test_brp.py` and `test_formulier_login.py`.
- eIDAS logins and appointment plugins (JCC, Qmatic): no estate configures them.
