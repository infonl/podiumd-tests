# KISS and ITA scenario gaps: porting plan

The batches that close the gaps of [`kiss-ita-scenario-gaps.md`](kiss-ita-scenario-gaps.md): KISS 3.2.0's and ITA
3.3.4's own end-to-end scenarios that no test of this suite asserts. The order across KISS, ITA and the ZAC plan
([`zac-port-plan.md`](zac-port-plan.md)) is at the end. The user picks the batches to port.

## What the batches build on

- **KISS's BFF.** Tests call the routes KISS's frontend calls, logged in as the KCC user (`kcc_login`,
  `kiss_register` for the register header). KISS's source at the deployed version's tag is read before each batch.
- **ITA's backend.** `/api/internetaken/...` as the KCC user or `ITA_BEHEERDER`; `ita_detail_text` for the detail.
- **Seeding.** Bootstrap `objecten-medewerker-kcc` (afdeling, groep, medewerker for the KCC user) and
  `openklant-actor-kcc`; Open Klant objects through `seed/openklant.py` (`make_partij`, `make_klantcontact`,
  `make_digitaal_adres`), cleaned up by the registry.
- **Mail.** Mailpit (`received_message`, `wait_for_mail`) where the environment tests mail.

## Summary

| Batch | Area | Gaps closed | Tests | Bootstrap | Days |
| --- | --- | --- | --- | --- | --- |
| K1 | Contactmoment through KISS's own routes | 5 high, 4 medium | 3 (done) | none | 1.5 |
| K2 | Contactverzoek through KISS, to afdeling, groep and medewerker | 6 high | 4 (done) | none | 2 |
| K3 | Zaak in KISS | 3 high | 2 | none | 1 |
| K4 | Search variants (person, company) | 2 high, 7 medium | 0 (parameters) | none; check the BRP and KvK test sets | 0.5 |
| K5 | Search sources: smoelenboek, source filter, afdeling on a kennisartikel | 7 medium | 3 | a kennisartikel with afdelingen | 1 |
| K6 | Nieuws en werkinstructies | 23 medium | 5 | none | 1.5 |
| I1 | Forward to a medewerker, groepsmailbox rules | 7 high, 8 medium | 4 | a medewerker without e-mail | 2 |
| I2 | Afsluiten and historie | 3 high, 8 medium | 5 (done) | none | 2 |
| I3 | Reminder to a medewerker | 3 high | 1 (extended) | none | 0.5 |
| I4 | Zaak koppelen and the logboek | 10 medium | 3 | none | 1.5 |
| I5 | Beheer and forward-form data | 9 medium | 3 | none | 1 |
| I6 | Detail data: digitale adressen fallback, klantnaam, duplicate nummer | 6 medium | 3 | none | 1 |
| | **Total** | **27 high, 82 medium** | **37** | | **about 16** |

## Batches

### K1: contactmoment through KISS's own routes (done: 3 tests, 4 cases)

- Covered in `tests/component/kiss/test_kcc_session.py`: a contactmoment saved through `POST /api/postklantcontacten`
  names the KCC medewerker as actor; one for a persoon and one for an organisatie is listed for that partij (the
  Contactmomenten tab's query); KISS keeps gespreksresultaat, afdeling and vraag in `contactmomentdetails` and adds
  the medewerker. `kcc.kiss_klantcontact` uses KISS's own route now, so every KISS klantcontact test does.
- Not covered: the bronnen (KISS's GET leaves them out; they feed only its reports); the onderwerp cut to fit
  (browser; deferred).
- Leftovers: KISS has no call to delete contactmomentdetails; one row per test run stays, run-tagged.
- Finding: KISS names the medewerker by the token's `email` claim, else `preferred_username`
  (`AuthenticationSetup.GetEmail`). On kees00 and minikube it gets no email claim although the client's default scopes
  include `email`, so it uses the username and creates a second actor for the KCC user (objectId the username, code
  email) next to bootstrap's actor with the e-mail.

### K2: contactverzoek through KISS (done: 4 tests, 9 cases)

- Covered in `tests/integration/test_kiss_contactverzoek.py`: a contactverzoek saved as KISS's frontend does
  (`postklantcontacten`, betrokkene, digitaal adres and actor through KISS's proxy, `postinternetaak`) to an afdeling
  or groep, by phone or e-mail, is assigned to it and found by that address with KISS's contactverzoek search; one for
  ITA_GROEP shows in full in ITA (replaces the hand-built contactverzoek, test id ITA-035); one for a persoon or an
  organisatie is listed for that partij; a medewerker created in Objecten is found in KISS's smoelenboek within
  ITA_GROEP after the smoelenboek sync, and a contactverzoek to that medewerker and the groep is assigned to both and
  shows in ITA.
- The test creates its own actoren; KISS's frontend reuses an existing actor with the same identificator.
- Skipped where KISS takes a medewerker's e-mail address instead of the smoelenboek (`USE_MEDEWERKEREMAIL`).

### K3: zaak in KISS (1 day, 2 tests)

- Gaps: find a zaak through `/api/zaken/zaken`; register a contactmoment on it through KISS and read it back through
  KISS. Extends `tests/integration/test_klantcontact_zaak.py`.

### K4: search variants (0.5 day, parameters only)

- Gaps: unknown bedrijfsnaam, unknown postcode and huisnummer; several results by naam, KvK-nummer, postcode;
  person by part of the achternaam, and postcode filtered on achternaam, part of it, or huisletter.
- New parameters on `test_person_search` and `test_company_search`. First check that the BRP and KvK test sets hold
  KISS's test persons (Melap*, 2511CA 21, 1074HK 1) and a KvK-nummer with several vestigingen.

### K5: search sources (1 day, 3 tests)

- Gaps: a smoelenboek hit; the source filter (VAC, Kennisbank); the afdeling of a kennisartikel hit (`afdelingnaam`
  and `afdelingNaam`). Builds on `test_kiss_kennis`.

### K6: nieuws en werkinstructies (1.5 days, 5 tests)

- Gaps: the lifecycle of both types in beheer (list, detail, change titel, publicatiedatum and belangrijk, delete
  asserted); the publication window (future start hidden, past end hidden, future end shown); skill and type filters
  with search; marking unread. In `tests/component/kiss/test_kiss_beheer.py`.

### I1: forward to a medewerker (2 days, 4 tests)

- Gaps: forward to a medewerker, alone and with their afdeling; the mails to medewerker and afdeling with and
  without a groepsmailbox and the warning; an afdeling without mailbox allowed with a medewerker; a groep without
  mailbox refused; mode medewerker without afdeling or groep refused; a medewerker without e-mail gets a warning;
  `/api/medewerkers` by search, afdeling and groep; regression #425 (assigned through the object-register id).
- Bootstrap: one more Objecten medewerker without e-mail (extend `objecten-medewerker-kcc`).

### I2: afsluiten and historie (done: 5 tests)

- Covered in `tests/component/ita/test_ita_afsluiten.py`: an unassigned contactverzoek assigned to self and closed with
  `close-with-klantcontact` is verwerkt with afgehandeldOp in Open Klant, its klantcontact gelukt, and moves to Mijn
  historie; Mijn historie lists the latest first (ITA sorts on toegewezenOp); Afdelings- and Groepshistorie list the
  closed ones; `gebruiker-groepen-and-afdelingen` offers the medewerker's groep. In `test_ita_beheer.py`: Alle
  contactverzoeken lists an open one, not a closed one. Contact gelukt and niet gelukt keep it te_verwerken
  (`test_answering_an_internetaak_registers_a_klantcontact`).
- `test_question_answered_in_ita_shows_as_answered` closes through ITA's `close-with-klantcontact`.
- ITA's helpers and fixtures are in `src/podiumd_tests/ita.py`.

### I3: reminder to a medewerker (0.5 day, 1 test extended)

- Gaps: a medewerker's reminder with the werkvoorraad link; a contactverzoek for a medewerker and an afdeling reminds
  both; the klantnaam of a betrokkene is not in the body. Extends the destructive CronJob test.

### I4: zaak koppelen and the logboek (1.5 days, 3 tests)

- Gaps: `koppel-zaak` with a valid zaak, an unknown zaaknummer, a second zaak replacing the first, the zaak on the
  detail; `/logboek` lines for assign, zaak, replaced zaak, contact gelukt, close and reopen (parametrized).

### I5: beheer and forward-form data (1 day, 3 tests)

- Gaps: kanalen create, edit, delete, duplicate refused, the KCC user refused; `heeftGroepsmailbox` on afdelingen and
  groepen; the forward's success message.

### I6: detail data (1 day, 3 tests)

- Gaps: the partij's digitale adressen when the betrokkene has none, the betrokkene's own winning, empty without;
  the klantnaam from a BSN partij; a klantcontactnummer with two contactverzoeken gives 409.

## Order across KISS, ITA and ZAC

By high-priority gaps per day, then the medium batches that share their setup:

1. K1, K2, I1, I2 (core KCC flows; K1 first: K2 and I2 build on its helper), then K3 and I3.
2. ZAC Z6 (documents) and Z9 (productaanvraag), then Z10 (zaakafhandelparameters, hoofd- and deelzaak).
3. K4 (cheap), I4, I6, K5, I5, K6, then ZAC Z7, Z8, Z11, Z12.
