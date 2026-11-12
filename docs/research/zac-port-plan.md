# ZAC scenario gaps: porting plan

The batches that close the gaps of [`zac-scenario-gaps.md`](zac-scenario-gaps.md): the ZAC team's manual scenarios
for ZAC 5.9.1 (PodiumD 4.10) that no test of this suite asserts. High-priority gaps first, then the medium ones that
share their setup. The user picks the batches to port.

## What the batches build on

- **ZAC REST API.** Every scenario of the gaps list runs through `/rest` (column Via: zac-rest), as the existing ZAC
  tests do (`zac.py`: `create_zaak`, `read_zaak`, `open_task`, `complete_task`, `search`, `productaanvraag_zaak`).
  ZAC's source is checked out next to this repository (`dimpact-zaakafhandelcomponent`); each batch reads the
  endpoints of the deployed version's tag there before writing a test.
- **Zaaktypen.** CMMN: the estate's productaanvraag zaaktype (profile setting `productaanvraag_zaaktype`, fixture
  `zac_parameters`), with the niet-ontvankelijk resultaattype and besluittype that bootstrap adds
  (`openzaak-zac-besluittype`). BPMN: the suite's own `ptest-bootstrap-bpmn` (step `zac-bpmn-process`).
- **Users per role.** Bootstrap has a Keycloak user per ZAC application role (`ZAC_ROLE_USERS`: raadpleger,
  behandelaar, coordinator, recordmanager, beheerder, brp_zoeken), mapped in PABC. The gaps list still names "needs a
  second ZAC user" for some scenarios; these users cover that.
- **Mail.** Mailpit (fixture `mailpit`, `received`) where the environment tests mail.
- **Cleanup.** A zaak is deleted through Open Zaak with its documents (`delete_zaak(with_documents=True)`), as
  `zac_zaak` does; ZAC's own records of it (zaakafhandelparameters are per zaaktype, not per zaak) need nothing.
- **Version gate.** All scenarios are ZAC 5.9.1 behaviour; a test of behaviour newer than 5.4 (PodiumD 4.9) gets a
  ZAC version gate where 4.9 environments still run.

## Summary

| Batch | Area | Gaps closed | Tests | Bootstrap | Days |
| --- | --- | --- | --- | --- | --- |
| Z1 | Zaak lifecycle: intake, afhandelen, heropenen, statuses | 5 high, 3 medium | 5 | none | 2 |
| Z2 | Zaak koppelen (gerelateerd; hoofd- and deelzaak in Z10) | 1 high, 2 medium | 5 (done) | none | 1.5 |
| Z3 | Besluiten in ZAC | 1 high, 3 medium | 7 (done) | besluit rights for the cleanup client | 1.5 |
| Z4 | Opschorten, verlengen and their dates | 3 high (partial), 2 medium | 4 (done) | none | 1.5 |
| Z5 | Mail from a zaak | 2 high, 2 medium | 4 (done) | none | 2 |
| Z6 | Documents: verplaatsen, ontkoppelen, versies, ondertekenen, refusals | 1 high, 6 medium | 8 (done) | none | 2 |
| Z7 | CMMN taken: intake, Goedkeuren, Advies, Document verzenden | 1 high, 4 medium | 7 (done) | step openzaak-iot-email | 2.5 |
| Z8 | Rights per role: closed zaak, documents, admin, verdelen, brp_zoeken | 1 high (partial), 6 medium | 6 (done) | none | 2 |
| Z9 | Productaanvraag: betrokkenen, inbox, contact, documents | 2 high, 5 medium | 6 (done) | step zac-bpmn-productaanvraag | 2 |
| Z10 | Zaakafhandelparameters: persist, new zaaktype version, PABC groups; hoofd- and deelzaak | 4 high, 3 medium | 7 (done) | none (a throwaway zaaktype per run) | 3.5 |
| Z11 | Search, werklijsten, signaleringen | 6 medium | 8 (done) | none | 2 |
| Z12 | Betrokkenen | 6 medium | 4 (done) | none | 1.5 |
| | **Total** | | **61 tests** | | **about 24** |

## Batches

### Z1: zaak lifecycle (done: 5 tests)

- Gaps: intake afronden ontvankelijk (status In behandeling, optional statusmail) and niet ontvankelijk (zaak closed
  with the niet-ontvankelijk resultaat, the mail stored as a definitief PDF); afhandelen with resultaat and
  afhandelmail through the REST action on a CMMN zaak, open taken closed; heropenen by a recordmanager (reden required,
  status Heropend, resultaat and archive dates cleared, afgehandeld again); the statuses In behandeling, Afgerond,
  Heropend; afbreken refused without reden; a zaak that is opgeschort or has a vergrendeld document cannot be
  afgehandeld.
- Files: new `tests/component/zac/test_zac_afhandelen.py`; `zac.py` gets `afronden_intake`, `afhandelen`,
  `heropenen` next to `create_zaak`.
- Reuses: `zac_zaak`, the recordmanager user, `mailpit`, the archive-date checks of Open Zaak's batch 4
  (`test_archivering.py`) for the dates ZAC sets.
- Risks: the statusmail depends on the zaakafhandelparameters of the estate's zaaktype; skip that assertion where its
  statusmail is off rather than changing the estate's configuration.

### Z2: zaak koppelen (done: 5 tests)

- Covered in `tests/component/zac/test_zac_relaties.py`: gerelateerd shows on both zaken (ZAC and Open Zaak) and
  ontkoppelen from the other zaak removes it from both; the koppel search leaves out the zaak itself and marks a linked
  zaak ALREADY_GERELATEERD, a second koppel is refused; a closed zaak can be gerelateerd (from either side) but not
  become a deelzaak (AFGEHANDELD); a zaaktype without deelzaaktypen refuses hoofdzaak and deelzaak.
- Moved to Z10: hoofdzaak and deelzaak koppelen, afhandelen of a hoofdzaak with an open deelzaak, ontkoppelen of a
  closed deelzaak. No estate zaaktype allows deelzaken, and ZAC refuses zaken of a zaaktype it has no configuration
  and PABC rights for (403), so these need Z10's throwaway zaaktype, with itself as deelzaaktype.
- The koppel search matches by uuid: ZAC's index keeps zaken whose DELETE answered 500 (open-zaak-1), and Open Zaak
  gives their identificatie out again.

### Z3: besluiten (done: 7 tests)

- Covered in `tests/component/zac/test_zac_besluiten.py`: a besluit is refused in the intake and stored in Open Zaak
  after it; ingangsdatum required; wijzigen needs a reden and shows in the besluit's historie; intrekken needs a reden
  and sets vervaldatum and vervalreden; a zaak with a besluit is afgehandeld and heropend, and takes another besluit in
  Heropend; a besluit links a document of the zaak; afbreken of a zaak with a besluit is refused (strict xfail zac-10:
  ZAC 5.9.1 checks the resultaat instead).
- Not covered: vervaldatum before ingangsdatum (ZAC and Open Zaak accept it through the API; only ZAC's form checks
  it); a resultaat that requires a besluit (no estate resultaattype has besluitVerplicht).
- Bootstrap: the productaanvraag client deletes besluiten (besluit rights, zaken.geforceerd-bijwerken for a closed
  zaak); the besluittype keeps its URL, links the zaaktype's documenttypes and clears ZAC's ZTC cache.
- The tests run one after another (xdist group): Open Zaak gives besluiten created at the same time the same
  identificatie (open-zaak-8).

### Z4: opschorten and verlengen (done: 4 tests, 2 of them extended)

- Covered: opschorten moves both dates and sets Open Zaak's opschorting (indicatie, reden); hervatten the same day
  moves them back by the unused days and keeps eerdereOpschorting; a second opschorting is refused; verlengen moves
  both dates, Open Zaak records reden and duur, a second verlenging is refused; a new zaak's dates come from the
  zaaktype's servicenorm and doorlooptijd (`test_zac_zaak.py`); Aanvullende informatie with opschorten suspends until
  the task's fatale datum and completing it with hervatten resumes (`test_zac_taken.py`, minikube only: the
  bootstrap step zac-aanvullende-informatie is off on kees00).
- Not covered: a verlenging beyond the zaaktype's verlengingstermijn (ZAC and Open Zaak accept 400 days against P14D
  through the API; only ZAC's form limits it).

### Z5: mail from a zaak (done: 4 tests)

- Covered in `tests/component/zac/test_zac_mail.py`: E-mail versturen with an attachment and a reply-to arrives from
  ZAC's afzender with the zaaknummer and omschrijving filled in, and is kept on the zaak as a PDF with the chosen
  vertrouwelijkheidaanduiding; without keeping it, the zaak gets no document; Bevestiging versturen arrives, is kept,
  clears ONTVANGSTBEVESTIGING_NIET_VERSTUURD and is refused a second time; a mail without vertrouwelijkheidaanduiding
  is refused.
- Not covered: the zaakspecifiek e-mail address of the productaanvraag (Z9).

### Z6: documents (done: 8 tests, 12 cases)

- Covered in `tests/component/zac/test_zac_documenten.py`: verplaatsen to another zaak (GEKOPPELD in the target's
  historie); ontkoppelen with a reden (historie, Ontkoppelde documenten with the reden) and koppelen from there to
  another zaak; deleting from Ontkoppelde documenten deletes the document in Open Zaak; a locked document cannot be
  deleted until unlocked; nieuwe versie with a new file and metadata, and with metadata only (versie +1 each);
  ondertekenen on a CMMN zaak (definitief, ONDERTEKEND, a second one refused); an .eml kept byte for byte; aac, mp3,
  exe, msi and an empty file refused.
- Not covered: ontkoppelen needs a reden (ZAC 5.9.1 accepts an empty reden, and without one answers 500 after it has
  removed the link: the document is then on no zaak and not in Ontkoppelde documenten); a real upload at the 500 MB
  limit (`/rest/configuratie/max-file-size-mb`): `test_edge_accepts_zacs_largest_upload` only announces that size at
  the edge, so no proxy in front of ZAC refuses it.

### Z7: CMMN taken (done: 7 tests, 9 cases)

- Covered in `tests/component/zac/test_zac_taken.py` on a throwaway zaaktype with every human task on: an open Advies
  intern holds off afhandelen and leaves Mijn taken once completed; Goedkeuren ondertekent the selected document, a
  second one is refused; Advies extern mails the adviseur (mail and its PDF on the zaak); Document verzenden records
  the verzenddatum; a taak's fatale datum stays within the zaak's; Aanvullende informatie mails and returns the zaak to
  Intake (3 uitkomsten). Bootstrap step `openzaak-iot-email`: ZAC stores sent mail as a document of the type "e-mail".
- Finding zac-12: the Advies referentietabel is not stored on the first save of human task parameters (strict xfail).
- Not covered: mandatory form fields and the prefilled initiator (ZAC's UI only); Advies extern's vastleggen variant.

### Z8: rights per role (done: 6 tests, 13 cases)

- Covered in `tests/component/zac/test_zac_rechten.py`, as the base roles on the BPMN test zaaktype, with the rights
  of ZAC 5.9.1's policies: the rechten of an afgehandelde zaak per role; a behandelaar and coordinator cannot edit it,
  a recordmanager can (not the uiterlijke einddatum afdoening), a behandelaar cannot heropenen; document rights per
  role when locked by another user, ondertekend and on an afgehandelde zaak; beheer refused to every role but
  beheerder; only a coordinator verdeelt and vrijgeeft; without brp_zoeken no person search but a bedrijf as
  initiator; the werklijst CSV export refused to the recordmanager (`test_zac_rollen.py`).
- A recordmanager reopens a closed BPMN zaak (the BPMN test zaaktype got statustype Heropend in bootstrap).
- Not covered: the group list per zaaktype from PABC (needs the PABC API key or podiumd-tests' own Keycloak groups); mail from a
  closed zaak (only the right `versturenEmail`).
- ZAC's search matches a zaak by uuid: its index keeps deleted zaken (open-zaak-1) whose identificatie Open Zaak hands
  out again.
- Zaakspecifieke autorisatie in `tests/component/zac/test_zac_zaakspecifiek.py`, on a throwaway zaaktype with
  eigenschap ZAAK_GEAUTORISEERD and roltype "Zaakspecifiek geautoriseerde medewerker", in a new group of two new
  behandelaars: the behandelaar marks the zaak; colleague, recordmanager, raadpleger and beheerder cannot open the
  zaak or its document, the colleague does not find it; the marking cannot be lifted; refused for a zaaktype without
  it, without behandelaar and for a colleague; a marked zaak cannot be released; after a handover the former
  behandelaar keeps access.

### Z9: productaanvraag (done: 6 tests)

- Covered in `tests/integration/test_productaanvraag.py`, on the BPMN test zaaktype with productaanvraagtype
  (bootstrap step `zac-bpmn-productaanvraag`): betrokkenen become rollen (first initiator only, BSN and KvK
  belanghebbenden, no behandelaar); the zaak takes omschrijving, toelichting, location, kanaal, groep, behandelaar,
  PDF, bijlage and the zaakobject; aanvraagspecifieke contactgegevens on the estate's zaaktype; the Inbox
  productaanvragen starts a zaak with the documents; concurrent notifications start one zaak.
- Finding podiumd-chart-42: the Productaanvraag-Dimpact objecttype refuses a company betrokkene at vestiging level
  (strict xfail `test_company_betrokkene_at_vestiging_level_becomes_a_rol`).
- Not covered: a vestiging that does not belong to the KvK-nummer (ZAC checks the format only); an attachment with a
  foreign informatieobjecttype; duplicates through Open Notificaties itself.

### Z10: zaakafhandelparameters, hoofd- and deelzaak (done: 7 tests, 11 cases)

- Covered in `tests/component/zac/test_zac_zaakafhandelparameters.py` on a throwaway zaaktype (test catalogus, PABC
  domain ptest-bootstrap, ZAC's generic CMMN model; cleaned up except ZAC's parameter rows, which ZAC cannot delete):
  saved values read back; a new zaaktype version keeps them and a changed default groep applies to new zaken only;
  only groups with a role on the zaaktype are offered. In `test_zac_relaties.py`: hoofd- and deelzaak on both zaken
  (both directions); a hoofdzaak with an open deelzaak cannot be afgehandeld; a closed deelzaak is ontkoppeld only
  once the hoofdzaak is closed too; IS_DEELZAAK, ALREADY_DEELZAAK and HAS_DEELZAKEN refused.
- ZAC's rule differs from the scenario "ontkoppelen also for a closed deelzaak": ZAC 5.9.1 allows it only when both
  zaken are open or both closed; the test asserts ZAC's rule.
- Not covered: the inrichtingscheck (lists only the default catalogus); the waarschuwingsvenster limit and clearing an
  unauthorised default groep (ZAC's UI only).

### Z11: search, werklijsten and signaleringen (done: 8 tests, 10 cases)

- Covered in `test_zac_zoeken.py` (text search by kenmerk, Solr special characters, werkvoorraad indicaties OPSCHORTING,
  VERLENGD, HEROPEND, HOOFDZAAK and DEELZAAK), `test_zac_signaleringen.py` (a zaak on my name and a new document on
  the dashboard until opened, a setting off gives none, a taak on my name), `test_zac_toekennen.py` (verdeeld to a
  group alone loses its behandelaar), `test_zac_bpmn.py` (a completed taak leaves the takenlijst).
- Not covered: signalering mails (the test users have no e-mail in Keycloak); expiry signals (ZAC's signaleringen
  CronJob).

### Z12: betrokkenen (done: 4 tests)

- Covered in `test_zac_klanten.py`: the same person with the same rol is added once (409); a betrokkene is ontkoppeld
  with a reden in the historie; the initiator changes from persoon to bedrijf and back (a toelichting required, one
  initiator in Open Zaak); a person's e-mail is the voorkeur address, else the first.
- Finding zac-13: ontkoppelen of a betrokkene or the initiator works without a reden (strict xfail).

## Not planned

- UI-only behaviour (layout, dialogs, labels such as "(inactief)"), AD login, Graylog logging.
- More than 120 zaaktypen in the werklijsten: 120 zaaktypen with ZAC configuration and PABC rights on a shared
  environment.
- PDF/A conformance of generated PDFs: needs a validator (veraPDF) in the suite's image.
- Holders of ZAC's application role zaakspecifiek_geautoriseerd: PodiumD's PABC dataset (chart 4.10.1, 4.11.0) has
  no such role.
- Low-priority gaps not named above; they follow the batch of their area when one is ported.
