# KISS and ITA end-to-end scenarios against podiumd-tests

What KISS's and ITA's own end-to-end suites check, and what podiumd-tests checks of it. Sources: KISS-frontend
`Kiss.Bff.EndToEndTest` at tag v3.2.0 (119 test methods in 13 classes) and ITA
`InterneTaakAfhandeling.EndToEndTest` at tag v3.3.4 (129 active test methods), the versions the environments run.
Phase 2 of [upstream-tests.md](upstream-tests.md) ported a first selection; this is the full comparison, made
2026-11-11. The batches that close the gaps: [kiss-ita-port-plan.md](kiss-ita-port-plan.md).

Columns: priority (high: a core KCC flow; medium: beheer, search variants, secondary flows; low: layout and labels),
status (covered, partial: what ours does not assert, gap), our tests, and how a test would reach it (bff-api: KISS's
BFF routes; api: ITA's backend or Open Klant and Objecten; browser: only visible in the UI). Scenarios that only test
UI state whose API path is covered are listed per class under "Not to port", with the reason.

## Findings

- **KISS's write routes are never called.** `kcc.kiss_klantcontact` posts through KISS's generic Open Klant proxy
  (`/api/klantinteracties/api/v1/klantcontacten`). KISS's frontend saves every contactmoment through
  `POST /api/postklantcontacten`, which links the logged-in medewerker as actor, and a contactverzoek through
  `POST /api/postinternetaak`; `PUT/GET /api/contactmomentdetails` (gespreksresultaat, afdeling, bronnen, KISS's own
  database), `/api/zaken/zaken` and `POST /api/search/medewerkers` (smoelenboek) are not called either.
- **ITA's closing and history are untested.** `POST /api/internetaken/close-with-klantcontact`, the historie
  lists, forwarding to a medewerker, `koppel-zaak` and the content of `/logboek` have no test.
- `tests/integration/test_portaal_openklant.py::test_question_answered_in_ita_shows_as_answered` says "ITA has no
  call to close the taak"; ITA 3.3.4 has `close-with-klantcontact`, so that test can close through ITA.

## Summary

| Suite | Scenarios | Covered | Partial | Gap | Not to port |
| --- | --- | --- | --- | --- | --- |
| KISS 3.2.0 | 119 | 23 | 31 | 26 | 39 |
| ITA 3.3.4 | 129 | 29 | 14 | 42 | 44 |

Open work (gap or partial, to port) by priority: KISS high 15, medium 41; ITA high 12, medium 38.

## KISS

### AfhandelingFormScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | An anonymous contactmoment with kanaal, gespreksresultaat and afdeling is saved | partial | saved through `/api/postklantcontacten`; medewerker actor; gespreksresultaat and afdeling (contactmomentdetails) | `test_klantcontact_through_kiss`, `test_klantcontact_keeps_the_kanaal_chosen_in_kiss` | bff-api | Open Klant |
| medium | The afdeling is filled from the kennisartikel (4 variants: `afdelingnaam`, `afdelingNaam`, two articles) | partial | the search hit's `afdelingen[]` | `test_object_is_found_in_kiss_search[kennisartikel]` | bff-api | Objecten, Elasticsearch sync |

Not to port: the notitie carried into the afhandeling, the 8 Annuleren variants (client state only); the required
fields (HTML5 validation in KISS's bundle).

### AnonymousContactmomentScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | A search in Smoelenboek finds medewerkers | gap | | | bff-api | Objecten Medewerker, smoelenboek sync |
| medium | A search filtered on VAC gives only VACs | partial | the source filter | `test_object_is_found_in_kiss_search[vac]` | bff-api | Objecten, Elasticsearch |
| medium | A search filtered on Kennisbank gives only kennisartikelen | partial | the source filter | `test_object_is_found_in_kiss_search[kennisartikel]` | bff-api | Objecten, Elasticsearch |
| medium | A search filtered on a website finds its pages | covered | | `test_crawled_website_is_found_in_kiss_search` | bff-api | crawler |
| medium | Reading a kennisartikel section fills vraag and afdeling | partial | the afdeling in the hit | `test_object_is_found_in_kiss_search[kennisartikel]` | bff-api | Objecten, Elasticsearch |

Not to port: 10 hits labelled per source (page size and labels are UI; hits per source are covered).

### AnonymousContactmomentZaakScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | The KCC finds a zaak by its identificatie | gap | | | bff-api `/api/zaken/zaken` | Open Zaak |
| high | A contactmoment is registered on the zaak | partial | through KISS (ours creates the onderwerpobject in Open Klant) | `test_klantcontact_about_a_zaak_is_found_by_the_zaak` | bff-api | Open Klant, Open Zaak |
| high | The zaak's Contactmomenten tab shows it | partial | read through KISS's proxy | same | bff-api | Open Klant, Open Zaak |

Not to port: the zaak shown checked as gerelateerde zaak (UI; the API path is the row above).

### AnonymousContactVerzoekPersonCompany

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | A contactverzoek for a person (BSN) shows on the person's Contactverzoeken tab | gap | | | bff-api | Open Klant, BRP, Objecten afdeling |
| high | A contactverzoek for a vestiging shows on the company's Contactverzoeken tab | gap | | | bff-api | Open Klant, KvK, Objecten afdeling |

Not to port: the form prefill for a person and a vestiging (UI; the BRP, KvK and partij reads are covered), the two
cancel variants.

### AnonymousContactVerzoekScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | A contactverzoek to an afdeling, by phone, found by that phone number | partial | registration through `postklantcontacten` and `postinternetaak`; digitale adressen; search by phone | `test_contactverzoek_from_kiss_shows_in_full_in_ita` | bff-api | Open Klant, Objecten Afdeling, ITA |
| high | The same, by e-mail | partial | same; search by e-mail | same | bff-api | same |
| high | A contactverzoek to a groep, by phone and by e-mail | partial | same, assigned to a groep | same, `test_forwarded_internetaak_is_assigned_to_the_afdeling_or_groep` | bff-api | Objecten Groep, ITA |
| high | A contactverzoek to a medewerker from the smoelenboek, within an afdeling or groep | gap | | | bff-api `/api/search/medewerkers` + `postinternetaak` | Objecten Medewerker, smoelenboek |

Not to port: no phone or e-mail, an invalid phone or e-mail (HTML5 validation).

### Beheer: Gespreksresultaten, Kanalen, Skills

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | Add, edit and delete a gespreksresultaat, a kanaal and a skill (9 scenarios) | covered | | `test_beheerder_adds_changes_and_deletes` | bff-api | ADMIN |

Not to port: the 3 navigation scenarios.

### ContactMomentCreation

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | A contactmoment for a person (BSN) is saved and shows on the person's Contactmomenten tab | partial | `postklantcontacten`; the person's partij as betrokkene; read back for the person | `test_klantcontact_through_kiss` | bff-api | Open Klant, BRP |
| high | A contactmoment for a vestiging is saved and shows on the company's tab | partial | the same for the vestiging | `test_klantcontact_through_kiss` | bff-api | Open Klant, KvK |

Not to port: the two cancel variants and the two parallel-session scenarios (client state).

### SearchCompanyScenarios and SearchPersonScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | Company by naam, KvK-nummer, vestigingsnummer, postcode and huisnummer; unknown KvK-nummer (5) | covered | | `test_company_search` | bff-api | KvK |
| high | Unknown bedrijfsnaam, unknown postcode and huisnummer | gap | | | bff-api | KvK |
| medium | Naam, KvK-nummer, postcode and huisnummer with several results (3) | partial | that there are several | `test_company_search` | bff-api | KvK test set |
| high | Person by achternaam and geboortedatum, BSN, postcode and huisnummer, found and not found (5) | covered | | `test_person_search` | bff-api | BRP |
| medium | Part of the achternaam with geboortedatum gives 2 persons | gap | | | bff-api | BRP test set (Melap*) |
| medium | Postcode and huisnummer filtered on achternaam, on part of it, on huisletter (3) | gap | | | bff-api | BRP test set |

Not to port: a BSN failing the elfproef and a 2-letter achternaam filter (client validation; the unknown BSN is
covered).

### NieuwsEnWerkInstructiesScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | The count of important berichten; marking read hides the body; a past publicatiedatum is shown (3) | covered | | `test_published_bericht_reaches_the_kcc_and_is_marked_read` | bff-api | ADMIN, KCC |
| medium | Marking unread; search over both types; belangrijk set by an update; a new nieuwsbericht in the beheer list and its detail; deleting a nieuwsbericht (6) | partial | unread, the werkinstructie, the update, the beheer list and detail, the delete | same | bff-api | ADMIN, KCC |
| medium | Filters on one, several or no skills; type filter with search (5) | gap | | | bff-api `skillIds`, `type`, `search` | ADMIN, KCC |
| medium | Beheer list, detail, changed titel and publicatiedatum, delete of a werkinstructie, new werkinstructie (7) | gap | | | bff-api `/api/Berichten` | ADMIN |
| medium | Future publicatiedatum hidden; publicatie-einddatum past hidden, future shown (3) | gap | | | bff-api | ADMIN, KCC |
| low | Skills shown as labels on a nieuwsbericht and a werkinstructie | partial, gap | the skills in the answer | same | bff-api | ADMIN, KCC |

Not to port: the home page rendering, paging (4), clearing the search, the table's columns.

### VraagScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | The VACs and kennisartikel looked at are saved as gerelateerde bronnen | gap | | | bff-api contactmomentdetails `bronnen` | KISS database |
| medium | A long VAC title, a long specifieke vraag, or both, are cut to fit the onderwerp (3) | gap | | | browser (the frontend builds the onderwerp) | a long-title VAC |

Not to port: two vragen in one contactmoment (two `postklantcontacten` calls; one is ported in batch K1), two vragen
for a vestiging (same path), the vraag field taking the last section read, a notitieblok over 1000 characters.

## ITA

### DagelijkseHerinneringScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | Aggregated mail; afdeling reminder; none for verwerkt; none without overdue; afdeling without e-mail skipped (5) | covered | | `test_afdeling_gets_one_reminder_for_its_overdue_contactverzoeken` | api | CronJob, Mailpit |
| high | A medewerker gets a reminder with a link to the werkvoorraad | gap | | | api | CronJob, Mailpit, Objecten medewerker |
| high | Assigned to a medewerker and an afdeling: both get one | gap | | | api | same |
| high | The body has no personal data | partial | the klantnaam (no betrokkene seeded), the instruction sentence | same | api | Open Klant betrokkene |

### KanalenScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | Beheerder adds, edits and deletes a kanaal; a duplicate name is refused (4) | gap | | (`test_kanalen_answer_the_kcc_user` only lists) | api `/api/kanaal` | ITA_BEHEERDER |

### Access, authentication and routing

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | Log in and reach the home page | covered | | `test_login_ends_on_the_keycloak_form`, every `kcc_login` | browser | Keycloak |
| high | Beheerder opens Alle contactverzoeken | covered | | `test_only_the_beheerder_lists_all_contactverzoeken` | api | ITA_BEHEERDER |

Not to port: row links by contactmoment nummer, the menu entry, the old route `/contactverzoek/{nummer}` (frontend).

### ContactverzoekDoorsturenScenarios and ContactverzoekDoorsturenGroepsmailboxScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | Forward to a groep; to an afdeling with a mailbox; afdeling without mailbox and medewerker refused (3) | covered | | `test_forwarded_internetaak_is_assigned_to_the_afdeling_or_groep`, `test_forward_to_an_afdeling_without_mailbox_is_refused` | api | Mailpit |
| high | Forward to a medewerker; to a medewerker with their afdeling (2) | gap | | | api forward | Objecten Medewerker, Mailpit |
| high | Medewerker and afdeling with a mailbox: both mailed; without a mailbox: only the medewerker, with the warning (2) | gap | | | api | Objecten, Mailpit |
| high | An afdeling without a mailbox but with a medewerker is allowed | gap | | | api | Objecten Medewerker |
| high | A groep without a mailbox and without a medewerker is refused | partial | the groep case | `test_forward_to_an_afdeling_without_mailbox_is_refused` | api | Objecten Groep |
| medium | Search medewerkers by name, by afdeling, by groep, without hits (4) | gap | | | api `/api/medewerkers` | Objecten Medewerker |
| medium | Mode medewerker without afdeling or groep refused; a medewerker without e-mail gets a warning (2) | gap | | | api | an extra medewerker without e-mail |
| medium | `heeftGroepsmailbox` of afdelingen and groepen, with and without (4) | partial | the flag | `test_afdelingen_and_groepen_are_seeded_together` | api | Objecten |
| medium | The success message of a forward | partial | `notificationResult` | `test_forwarded_internetaak_is_assigned_to_the_afdeling_or_groep` | api | |

Not to port: form defaults, mode order, field layout and live required/optional switching (10).

### ContactverzoekScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | Contact niet gelukt; assign to self; read-only when verwerkt (5 actions); changes allowed on te_verwerken | covered | | `test_answering_an_internetaak_registers_a_klantcontact`, `test_claimed_internetaak_is_on_my_list`, `test_a_verwerkt_contactverzoek_is_read_only` | api | Open Klant |
| high | Contact gelukt | partial | gelukt, kanaal, status stays te_verwerken | `test_answering_an_internetaak_registers_a_klantcontact` | api | Open Klant |
| high | Opslaan en afsluiten sets verwerkt and afgehandeldOp | gap | | | api `close-with-klantcontact` | Open Klant |
| high | Unassigned, assign to self, close, in historie | gap | | | api chain | Open Klant, KCC |
| medium | Detail page data | covered | | `test_contactverzoek_from_kiss_shows_in_full_in_ita` | api | Open Klant |
| medium | Klantnaam from a BSN partij | partial | the betrokkene's partij | same | api | Open Klant partij |
| medium | Mijn historie, its order; Afdelings- and Groephistorie; the user's afdelingen and groepen (5) | gap | | | api historie routes | KCC, ITA_GROEP |
| medium | Link a zaak; unknown zaaknummer; a second zaak replaces it; the zaak on the detail (4) | gap | | | api `koppel-zaak` | Open Zaak |
| medium | Logboek lines for assign, zaak, replaced zaak, contact gelukt, close (5) | partial, gap | the content of `/logboek` | `test_kiss_reads_itas_logboek` | api `/logboek` | Objecten |
| medium | Regression #425: assigned through the medewerker's object-register id counts as the user's | gap | | | api | Objecten Medewerker = KCC |
| medium | Alle contactverzoeken lists an open one and drops a closed one (2) | partial, gap | the contactverzoek in the list | `test_only_the_beheerder_lists_all_contactverzoeken` | api | ITA_BEHEERDER |
| medium | Informatie required when closing | gap | | | api or browser (check whether ITA refuses an empty one) | |

Not to port: dialogs, button visibility (5), headings, router links, a dash for a blank e-mail.

### DigitaleAdressenFallbackScenarios, HeropenContactverzoekScenarios, KlantcontactZoekenScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | The partij's addresses when the betrokkene has none; the betrokkene's own win; empty without a partij or addresses (4) | gap | | | api detail | Open Klant partij |
| high | Beheerder reopens a closed contactverzoek; no reason refused (2) | covered | | `test_beheerder_reopens_a_closed_contactverzoek` | api | ITA_BEHEERDER |
| medium | The logboek shows the reopen | partial | the logboek | same | api | Objecten |
| medium | Find by klantcontactnummer; unknown; outside the user's rights (3) | covered | | `test_contactverzoek_is_found_by_its_klantcontactnummer` | api | ITA_GROEP |
| medium | A nummer with several contactverzoeken gives the generic error | gap | | | api (409) | two internetaken on one klantcontact |

Not to port: the reopen button, Annuleren, the inactive-behandelaar toast (ignored upstream), the search icon.

### WerklijstUrgentieScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | Green, orange and red labels; weekends do not count (4) | covered | | `test_werklijst_shows_the_urgency_of_each_contactverzoek` | api | |
| low | Rounding up ("nog 1u"); the label on the afdeling and Alle lists (2) | partial | the label text; the other lists | same | api | ITA_BEHEERDER |

Not to port: columns, row click, hover and the arrow link (6).
