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
| K3 | Zaak in KISS | 3 high | 2 (done) | none | 1 |
| K4 | Search variants (person, company) | 2 high, 7 medium | 0 (parameters, done) | none | 0.5 |
| K5 | Search sources: smoelenboek, source filter, afdeling on a kennisartikel | 7 medium | 3 (done) | a kennisartikel with afdelingen | 1 |
| K6 | Nieuws en werkinstructies | 23 medium | 4 (done) | none | 1.5 |
| I1 | Forward to a medewerker, groepsmailbox rules | 7 high, 8 medium | 6 (done) | none | 2 |
| I2 | Afsluiten and historie | 3 high, 8 medium | 5 (done) | none | 2 |
| I3 | Reminder to a medewerker | 3 high | 1 (extended, done) | none | 0.5 |
| I4 | Zaak koppelen and the logboek | 10 medium | 3 (done) | none | 1.5 |
| I5 | Beheer and forward-form data | 9 medium | 2 (done) | none | 1 |
| I6 | Detail data: digitale adressen fallback, klantnaam, duplicate nummer | 6 medium | 3 (done) | none | 1 |
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

### K3: zaak in KISS (done: 2 tests)

- Covered in `tests/integration/test_klantcontact_zaak.py`: KISS finds a zaak by its zaaknummer (`/api/zaken/zaken`)
  and opens it; a contactmoment saved through KISS with an onderwerpobject for the zaak (`zgw-Zaak`, as KISS records
  it) is listed for the zaak by KISS's Contactmomenten query.
- Not covered: the contactmoment on the zaak in Open Zaak (KISS has it commented out: Open Zaak takes only Open Klant 1
  contactmomenten); the zaak checked as gerelateerde zaak (frontend).

### K4: search variants (done: 10 parameters)

- Covered in `tests/component/kiss/test_kiss_zoeken.py`: person search by part of the name with geboortedatum, by
  postcode and huisnummer with the exact count, filtered on (part of) the achternaam and on huisletter; company search
  with several results by naam, KvK-nummer and address, an unknown bedrijfsnaam and an unknown address. The BRP and
  KvK test sets behind Frank!Gateway hold KISS's test persons and companies with the same counts.
- Not covered: client-side validation (an invalid BSN, a 2-letter achternaam filter).

### K5: search sources (done: 3 tests, 5 cases)

- Covered in `tests/integration/test_kiss_kennis.py`: a smoelenboek hit after the smoelenboek sync; the source filter
  on VAC or Kennisbank gives hits of that index only; KISS takes the afdeling of a kennisartikel (`afdelingnaam`) and
  a VAC (`afdelingNaam`) from the hit. The Kennisartikel objecttype refuses `afdelingNaam`.

### K6: nieuws en werkinstructies (done: 4 tests, 8 cases)

- Covered in `tests/component/kiss/test_kiss_beheer.py`: a nieuwsbericht or werkinstructie in the beheer list and
  detail, changed (titel, publicatiedatum, belangrijk) and deleted; the publication window (future publicatiedatum
  and past einddatum hidden, future einddatum shown); skill filters (one, several, none) and the type filter with a
  search, skills as labels; marking unread.
- The tests that change the count of important berichten share an xdist group.

### I1: forward to a medewerker (done: 6 tests, 11 cases)

- Covered in `tests/component/ita/test_ita_doorsturen.py`: forward to an afdeling or groep with a groepsmailbox
  (moved there); to a medewerker with their afdeling or groep, assigned to both, one recipient (the medewerker, or the
  groepsmailbox when the medewerker has no e-mail address) and ITA's warning for an afdeling without mailbox; an
  afdeling or groep without mailbox and without medewerker refused; a medewerker alone, or an afdeling and a groep at
  once, refused; `/api/medewerkers` by name, afdeling and groep, and no hits; regression #425 (assigned through the
  user's object-register id is on their own list).
- Each test creates its own afdeling, groep and medewerkers in Objecten (unique identificaties), so no bootstrap change.

### I2: afsluiten and historie (done: 5 tests)

- Covered in `tests/component/ita/test_ita_afsluiten.py`: an unassigned contactverzoek assigned to self and closed with
  `close-with-klantcontact` is verwerkt with afgehandeldOp in Open Klant, its klantcontact gelukt, and moves to Mijn
  historie; Mijn historie lists the latest first (ITA sorts on toegewezenOp); Afdelings- and Groepshistorie list the
  closed ones; `gebruiker-groepen-and-afdelingen` offers the medewerker's groep. In `test_ita_beheer.py`: Alle
  contactverzoeken lists an open one, not a closed one. Contact gelukt and niet gelukt keep it te_verwerken
  (`test_answering_an_internetaak_registers_a_klantcontact`).
- `test_question_answered_in_ita_shows_as_answered` closes through ITA's `close-with-klantcontact`.
- ITA's helpers and fixtures are in `src/podiumd_tests/ita.py`.

### I3: reminder to a medewerker (done: 1 test extended)

- Covered in `test_afdeling_gets_one_reminder_for_its_overdue_contactverzoeken`: an overdue contactverzoek of a klant
  assigned to a medewerker and an afdeling reminds both ("1 contactverzoek wacht op jou"), the medewerker's mail
  linking to `/`, the afdeling's to `/afdelings-contacten`, neither with the klant's name.
- The reminder CronJob is off in podiumd 4.10.1 (DRT-726); the test runs ITA's poller in reminder mode from the
  `-nieuw-cv-notify` CronJob instead (destructive, tier chaos; passed on minikube 2026-11-12). Every reminder carries
  ITA's instruction sentence.

### I4: zaak koppelen and the logboek (done: 3 tests)

- Covered in `tests/component/ita/test_ita_zaak.py`: koppel-zaak by zaaknummer (onderwerpobject in Open Klant,
  zaaknummer on the detail), a second zaak replaces it, an unknown zaaknummer is refused; `/logboek` lists toegewezen,
  zaak-gekoppeld, zaakkoppeling-gewijzigd, klantcontact and verwerkt.
- Finding ita-3 (security): koppel-zaak works without a login (strict xfail `test_koppel_zaak_needs_a_login`).
- ITA's ZGW secret must be at least 32 characters for HS256 (fixed on minikube; kees00 waits for podiumd-infra).
- The reopen in the logboek: `test_beheerder_reopens_a_closed_contactverzoek` (newest entry `heropend`, reden, beheerder).

### I5: beheer and forward-form data (done: 2 tests, 3 cases)

- Covered in `tests/component/ita/test_ita_beheer.py`: kanalen added, renamed, deleted by the beheerder, a duplicate
  naam refused, the KCC user refused; `heeftGroepsmailbox` on afdelingen and groepen. The forward's success message is
  asserted in `test_ita_doorsturen.py` (I1).

### I6: detail data (done: 3 tests, 6 cases)

- Covered in `tests/component/ita/test_ita_detail.py`: the detail's e-mail is the betrokkene's own, else its
  partij's, else none; klantNaam of a BSN partij; a klantcontactnummer of two contactverzoeken gives 409.

## Order across KISS, ITA and ZAC

By high-priority gaps per day, then the medium batches that share their setup:

1. K1, K2, I1, I2 (core KCC flows; K1 first: K2 and I2 build on its helper), then K3 and I3.
2. ZAC Z6 (documents) and Z9 (productaanvraag), then Z10 (zaakafhandelparameters, hoofd- and deelzaak).
3. K4 (cheap), I4, I6, K5, I5, K6, then ZAC Z7, Z8, Z11, Z12.
