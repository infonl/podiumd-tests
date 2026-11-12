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

| Suite | Rows | Covered | Partial | Gap |
| --- | --- | --- | --- | --- |
| KISS 3.2.0 | 33 | 32 | 1 | 0 |
| ITA 3.3.4 | 35 | 35 | 0 | 0 |

A row can group several upstream scenarios (their number in parentheses). Scenarios not to port are listed under each
section. UI-only remainders are noted in a row's "Not asserted" column.

## KISS

### AfhandelingFormScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | An anonymous contactmoment with kanaal, gespreksresultaat and afdeling is saved | covered |  | `test_klantcontact_through_kiss`, `test_klantcontact_keeps_the_kanaal_chosen_in_kiss`, `test_contactmoment_saved_in_kiss_names_the_medewerker`, `test_kiss_keeps_the_contactmoment_details` | bff-api | Open Klant |
| medium | The afdeling is filled from the kennisartikel (4 variants: `afdelingnaam`, `afdelingNaam`, two articles) | partial | VAC with `afdelingnaam` and kennisartikel with `afdelingNaam`: the estate's objecttypes refuse those keys, so they cannot be seeded; KISS reads both spellings | `test_object_is_found_in_kiss_search[kennisartikel]`, `test_kennisartikel_hit_names_its_afdeling` | bff-api | Objecten, Elasticsearch sync |

Not to port: the notitie carried into the afhandeling, the 8 Annuleren variants (client state only); the required
fields (HTML5 validation in KISS's bundle).

### AnonymousContactmomentScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | A search in Smoelenboek finds medewerkers | covered |  | bff-api, `test_object_is_found_in_kiss_search` | Objecten Medewerker, smoelenboek sync |
| medium | A search filtered on VAC gives only VACs | covered |  | `test_object_is_found_in_kiss_search[vac]`, `test_source_filter_gives_only_that_source` | bff-api | Objecten, Elasticsearch |
| medium | A search filtered on Kennisbank gives only kennisartikelen | covered |  | `test_object_is_found_in_kiss_search[kennisartikel]`, `test_source_filter_gives_only_that_source` | bff-api | Objecten, Elasticsearch |
| medium | A search filtered on a website finds its pages | covered | | `test_crawled_website_is_found_in_kiss_search` | bff-api | crawler |
| medium | Reading a kennisartikel section fills vraag and afdeling | covered | Filling the vraag field is UI only (not planned) | `test_object_is_found_in_kiss_search[kennisartikel]`, `test_kennisartikel_hit_names_its_afdeling` | bff-api | Objecten, Elasticsearch |

Not to port: 10 hits labelled per source (page size and labels are UI; hits per source are covered).

### AnonymousContactmomentZaakScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | The KCC finds a zaak by its identificatie | covered |  | bff-api `/api/zaken/zaken`, `test_kcc_finds_a_zaak_in_kiss_by_its_zaaknummer` | Open Zaak |
| high | A contactmoment is registered on the zaak | covered |  | `test_klantcontact_about_a_zaak_is_found_by_the_zaak`, `test_contactmoment_on_a_zaak_in_kiss_is_listed_for_the_zaak` | bff-api | Open Klant, Open Zaak |
| high | The zaak's Contactmomenten tab shows it | covered |  | same, `test_contactmoment_on_a_zaak_in_kiss_is_listed_for_the_zaak` | bff-api | Open Klant, Open Zaak |

Not to port: the zaak shown checked as gerelateerde zaak (UI; the API path is the row above).

### AnonymousContactVerzoekPersonCompany

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | A contactverzoek for a person (BSN) shows on the person's Contactverzoeken tab | covered |  | bff-api, `test_contactverzoek_for_a_klant_is_listed_for_that_klant` | Open Klant, BRP, Objecten afdeling |
| high | A contactverzoek for a vestiging shows on the company's Contactverzoeken tab | covered |  | bff-api, `test_contactverzoek_for_a_klant_is_listed_for_that_klant` | Open Klant, KvK, Objecten afdeling |

Not to port: the form prefill for a person and a vestiging (UI; the BRP, KvK and partij reads are covered), the two
cancel variants.

### AnonymousContactVerzoekScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | A contactverzoek to an afdeling, by phone, found by that phone number | covered |  | `test_contactverzoek_from_kiss_shows_in_full_in_ita`, `test_contactverzoek_from_kiss_is_found_by_the_klants_adres` | bff-api | Open Klant, Objecten Afdeling, ITA |
| high | The same, by e-mail | covered |  | same, `test_contactverzoek_from_kiss_is_found_by_the_klants_adres` | bff-api | same |
| high | A contactverzoek to a groep, by phone and by e-mail | covered |  | same, `test_forwarded_internetaak_is_assigned_to_the_afdeling_or_groep`, `test_contactverzoek_from_kiss_is_found_by_the_klants_adres`, `test_contactverzoek_from_kiss_shows_in_full_in_ita` | bff-api | Objecten Groep, ITA |
| high | A contactverzoek to a medewerker from the smoelenboek, within an afdeling or groep | covered |  | bff-api `/api/search/medewerkers` + `postinternetaak`, `test_contactverzoek_to_a_medewerker_from_the_smoelenboek` | Objecten Medewerker, smoelenboek |

Not to port: no phone or e-mail, an invalid phone or e-mail (HTML5 validation).

### Beheer: Gespreksresultaten, Kanalen, Skills

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | Add, edit and delete a gespreksresultaat, a kanaal and a skill (9 scenarios) | covered | | `test_beheerder_adds_changes_and_deletes` | bff-api | ADMIN |

Not to port: the 3 navigation scenarios.

### ContactMomentCreation

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | A contactmoment for a person (BSN) is saved and shows on the person's Contactmomenten tab | covered |  | `test_klantcontact_through_kiss`, `test_contactmoment_for_a_klant_is_listed_for_that_klant` | bff-api | Open Klant, BRP |
| high | A contactmoment for a vestiging is saved and shows on the company's tab | covered |  | `test_klantcontact_through_kiss`, `test_contactmoment_for_a_klant_is_listed_for_that_klant` | bff-api | Open Klant, KvK |

Not to port: the two cancel variants and the two parallel-session scenarios (client state).

### SearchCompanyScenarios and SearchPersonScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | Company by naam, KvK-nummer, vestigingsnummer, postcode and huisnummer; unknown KvK-nummer (5) | covered | | `test_company_search` | bff-api | KvK |
| high | Unknown bedrijfsnaam, unknown postcode and huisnummer | covered |  | bff-api, `test_company_search` | KvK |
| medium | Naam, KvK-nummer, postcode and huisnummer with several results (3) | covered |  | `test_company_search` | bff-api | KvK test set |
| high | Person by achternaam and geboortedatum, BSN, postcode and huisnummer, found and not found (5) | covered | | `test_person_search` | bff-api | BRP |
| medium | Part of the achternaam with geboortedatum gives 2 persons | covered |  | bff-api, `test_person_search` | BRP test set (Melap*) |
| medium | Postcode and huisnummer filtered on achternaam, on part of it, on huisletter (3) | covered |  | bff-api, `test_person_search` | BRP test set |

Not to port: a BSN failing the elfproef and a 2-letter achternaam filter (client validation; the unknown BSN is
covered).

### NieuwsEnWerkInstructiesScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | The count of important berichten; marking read hides the body; a past publicatiedatum is shown (3) | covered | | `test_published_bericht_reaches_the_kcc_and_is_marked_read` | bff-api | ADMIN, KCC |
| medium | Marking unread; search over both types; belangrijk set by an update; a new nieuwsbericht in the beheer list and its detail; deleting a nieuwsbericht (6) | covered |  | same, `test_published_bericht_reaches_the_kcc_and_is_marked_read`, `test_bericht_is_changed_and_deleted_in_beheer`, `test_berichten_are_filtered_on_skill_and_type` | bff-api | ADMIN, KCC |
| medium | Filters on one, several or no skills; type filter with search (5) | covered |  | bff-api `skillIds`, `type`, `search`, `test_berichten_are_filtered_on_skill_and_type` | ADMIN, KCC |
| medium | Beheer list, detail, changed titel and publicatiedatum, delete of a werkinstructie, new werkinstructie (7) | covered |  | bff-api `/api/Berichten`, `test_bericht_is_changed_and_deleted_in_beheer` | ADMIN |
| medium | Future publicatiedatum hidden; publicatie-einddatum past hidden, future shown (3) | covered |  | bff-api, `test_bericht_shows_within_its_publication_window` | ADMIN, KCC |
| low | Skills shown as labels on a nieuwsbericht and a werkinstructie | covered |  | same, `test_berichten_are_filtered_on_skill_and_type`, `test_bericht_is_changed_and_deleted_in_beheer` | bff-api | ADMIN, KCC |

Not to port: the home page rendering, paging (4), clearing the search, the table's columns.

### VraagScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | The VACs and kennisartikel looked at are saved as gerelateerde bronnen | covered | KISS 3.2.0 returns bronnen only on its managementinformatie route; fails on minikube until its KISS key is 32+ characters (handoff) | bff-api contactmomentdetails `bronnen`, `test_kiss_reports_the_bronnen_of_a_contactmoment` | KISS database |
| medium | A long VAC title, a long specifieke vraag, or both, are cut to fit the onderwerp (3) | covered | The cutting happens in KISS's browser code (not planned); the 200-character onderwerp is kept whole | browser (the frontend builds the onderwerp), `test_onderwerp_of_maximum_length_is_kept_whole` | a long-title VAC |

Not to port: two vragen in one contactmoment (two `postklantcontacten` calls; one is ported in batch K1), two vragen
for a vestiging (same path), the vraag field taking the last section read, a notitieblok over 1000 characters.

## ITA

### DagelijkseHerinneringScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | Aggregated mail; afdeling reminder; none for verwerkt; none without overdue; afdeling without e-mail skipped (5) | covered | | `test_afdeling_gets_one_reminder_for_its_overdue_contactverzoeken` | api | CronJob, Mailpit |
| high | A medewerker gets a reminder with a link to the werkvoorraad | covered |  | api, `test_afdeling_gets_one_reminder_for_its_overdue_contactverzoeken` | CronJob, Mailpit, Objecten medewerker |
| high | Assigned to a medewerker and an afdeling: both get one | covered |  | api, `test_afdeling_gets_one_reminder_for_its_overdue_contactverzoeken` | same |
| high | The body has no personal data | covered |  | same, `test_afdeling_gets_one_reminder_for_its_overdue_contactverzoeken` | api | Open Klant betrokkene |

### KanalenScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | Beheerder adds, edits and deletes a kanaal; a duplicate name is refused (4) | covered |  | api `/api/kanaal`, `test_beheerder_manages_kanalen` | ITA_BEHEERDER |

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
| high | Forward to a medewerker; to a medewerker with their afdeling (2) | covered |  | api forward, `test_forward_to_a_medewerker_mails_one_party`, `test_forward_needs_exactly_one_afdeling_or_groep` | Objecten Medewerker, Mailpit |
| high | Medewerker and afdeling with a mailbox: both mailed; without a mailbox: only the medewerker, with the warning (2) | covered | ITA 3.3.4 mails one party: the medewerker, otherwise the groepsmailbox (the scenario's both is outdated) | api, `test_forward_to_a_medewerker_mails_one_party` | Objecten, Mailpit |
| high | An afdeling without a mailbox but with a medewerker is allowed | covered |  | api, `test_forward_to_a_medewerker_mails_one_party` | Objecten Medewerker |
| high | A groep without a mailbox and without a medewerker is refused | covered |  | `test_forward_to_an_afdeling_without_mailbox_is_refused`, `test_forward_without_any_mailbox_is_refused` | api | Objecten Groep |
| medium | Search medewerkers by name, by afdeling, by groep, without hits (4) | covered |  | api `/api/medewerkers`, `test_medewerkers_are_found_by_name_afdeling_and_groep` | Objecten Medewerker |
| medium | Mode medewerker without afdeling or groep refused; a medewerker without e-mail gets a warning (2) | covered | ITA falls back to the groepsmailbox instead of warning | api, `test_forward_needs_exactly_one_afdeling_or_groep` | an extra medewerker without e-mail |
| medium | `heeftGroepsmailbox` of afdelingen and groepen, with and without (4) | covered |  | `test_afdelingen_and_groepen_are_seeded_together`, `test_afdelingen_and_groepen_tell_their_groepsmailbox` | api | Objecten |
| medium | The success message of a forward | covered |  | `test_forwarded_internetaak_is_assigned_to_the_afdeling_or_groep`, `test_forward_to_a_medewerker_mails_one_party` | api | |

Not to port: form defaults, mode order, field layout and live required/optional switching (10).

### ContactverzoekScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| high | Contact niet gelukt; assign to self; read-only when verwerkt (5 actions); changes allowed on te_verwerken | covered | | `test_answering_an_internetaak_registers_a_klantcontact`, `test_claimed_internetaak_is_on_my_list`, `test_a_verwerkt_contactverzoek_is_read_only` | api | Open Klant |
| high | Contact gelukt | covered |  | `test_answering_an_internetaak_registers_a_klantcontact` | api | Open Klant |
| high | Opslaan en afsluiten sets verwerkt and afgehandeldOp | covered |  | api `close-with-klantcontact`, `test_closing_a_contactverzoek_moves_it_to_mijn_historie` | Open Klant |
| high | Unassigned, assign to self, close, in historie | covered |  | api chain, `test_closing_a_contactverzoek_moves_it_to_mijn_historie` | Open Klant, KCC |
| medium | Detail page data | covered | | `test_contactverzoek_from_kiss_shows_in_full_in_ita` | api | Open Klant |
| medium | Klantnaam from a BSN partij | covered |  | same, `test_detail_names_the_klant_of_a_bsn_partij` | api | Open Klant partij |
| medium | Mijn historie, its order; Afdelings- and Groephistorie; the user's afdelingen and groepen (5) | covered |  | api historie routes, `test_mijn_historie_lists_the_latest_first`, `test_afdelings_and_groepshistorie_list_the_closed_contactverzoeken`, `test_afdelingshistorie_offers_the_medewerkers_groepen` | KCC, ITA_GROEP |
| medium | Link a zaak; unknown zaaknummer; a second zaak replaces it; the zaak on the detail (4) | covered |  | api `koppel-zaak`, `test_zaak_is_linked_and_replaced_by_zaaknummer` | Open Zaak |
| medium | Logboek lines for assign, zaak, replaced zaak, contact gelukt, close (5) | covered |  | `test_kiss_reads_itas_logboek`, `test_logboek_lists_each_action` | api `/logboek` | Objecten |
| medium | Regression #425: assigned through the medewerker's object-register id counts as the user's | covered |  | api, `test_contactverzoek_assigned_by_objectregister_id_is_mine` | Objecten Medewerker = KCC |
| medium | Alle contactverzoeken lists an open one and drops a closed one (2) | covered |  | `test_only_the_beheerder_lists_all_contactverzoeken`, `test_alle_contactverzoeken_lists_only_open_ones` | api | ITA_BEHEERDER |
| medium | Informatie required when closing | covered | UI only (not planned): ITA's API accepts an empty informatie (finding, not yet filed) | api or browser (check whether ITA refuses an empty one) | |

Not to port: dialogs, button visibility (5), headings, router links, a dash for a blank e-mail.

### DigitaleAdressenFallbackScenarios, HeropenContactverzoekScenarios, KlantcontactZoekenScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | The partij's addresses when the betrokkene has none; the betrokkene's own win; empty without a partij or addresses (4) | covered |  | api detail, `test_detail_falls_back_to_the_partijs_adressen` | Open Klant partij |
| high | Beheerder reopens a closed contactverzoek; no reason refused (2) | covered | | `test_beheerder_reopens_a_closed_contactverzoek` | api | ITA_BEHEERDER |
| medium | The logboek shows the reopen | covered |  | same, `test_beheerder_reopens_a_closed_contactverzoek` | api | Objecten |
| medium | Find by klantcontactnummer; unknown; outside the user's rights (3) | covered | | `test_contactverzoek_is_found_by_its_klantcontactnummer` | api | ITA_GROEP |
| medium | A nummer with several contactverzoeken gives the generic error | covered |  | api (409), `test_klantcontactnummer_of_two_contactverzoeken_is_refused` | two internetaken on one klantcontact |

Not to port: the reopen button, Annuleren, the inactive-behandelaar toast (ignored upstream), the search icon.

### WerklijstUrgentieScenarios

| Priority | Scenario | Status | Not asserted | Our tests | Via | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| medium | Green, orange and red labels; weekends do not count (4) | covered | | `test_werklijst_shows_the_urgency_of_each_contactverzoek` | api | |
| low | Rounding up ("nog 1u"); the label on the afdeling and Alle lists (2) | covered | The afdelingen-groepen overview has no urgentie in ITA 3.3.4 | same, `test_werklijst_shows_the_urgency_of_each_contactverzoek`, `test_alle_contactverzoeken_lists_only_open_ones` | api | ITA_BEHEERDER |

Not to port: columns, row click, hover and the arrow link (6).
