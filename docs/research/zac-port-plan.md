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
| Z5 | Mail from a zaak | 2 high, 2 medium | 4 | none | 2 |
| Z6 | Documents: verplaatsen, ontkoppelen, versies, ondertekenen, refusals | 1 high, 6 medium | 6 | none | 2 |
| Z7 | CMMN taken: intake, Goedkeuren, Advies, Document verzenden | 1 high, 4 medium | 4 | human task parameters for more plan items | 2.5 |
| Z8 | Rights per role: closed zaak, documents, admin, verdelen, brp_zoeken | 1 high (partial), 6 medium | 6 | none | 2 |
| Z9 | Productaanvraag: betrokkenen, inbox, contact, documents | 2 high, 5 medium | 5 | productaanvraag with betrokkenen and geometry | 2 |
| Z10 | Zaakafhandelparameters: persist, new zaaktype version, PABC groups; hoofd- and deelzaak | 4 high, 3 medium | 6 | a throwaway zaaktype configured in ZAC | 3.5 |
| Z11 | Search, werklijsten, signaleringen | 6 medium | 5 | none | 2 |
| Z12 | Betrokkenen | 6 medium | 4 | none | 1.5 |
| | **Total** | | **61 tests** | | **about 24** |

## Batches

### Z1: zaak lifecycle (2 days, 5 tests)

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

### Z5: mail from a zaak (2 days, 4 tests)

- Gaps: Bevestiging versturen from a zaak (mail arrives, stored as a document, indicatie
  ONTVANGSTBEVESTIGING_NIET_VERSTUURD cleared); E-mail versturen with and without an attachment (mail arrives, PDF of
  the mail on the zaak); mails built from the zaakafhandelparameters' templates with their afzender and reply-to; the
  stored mail PDF's vertrouwelijkheidaanduiding.
- Files: new `tests/component/zac/test_zac_mail.py`; `zac.py` gets `send_mail`.
- Reuses: `mailpit` and its `received` lookup, `zac_zaak`.
- Risks: needs mail: requires `mailpit`; the zaakspecifiek e-mail address of the productaanvraag (betrokkenen gap) is
  Z9.

### Z6: documents (2 days, 6 tests)

- Gaps: verplaatsen to another zaak and koppelen from Ontkoppelde documenten (move in historie); ontkoppelen needs a
  reden; a locked document cannot be deleted until unlocked; nieuwe versie with metadata (versie +1); ondertekenen on
  a CMMN zaak (definitief, indicatie ONDERTEKEND); allowed and refused extensions (eml kept intact; aac, mp3, exe, msi
  and empty files refused); a document deleted from Ontkoppelde documenten is gone from Open Zaak.
- Files: new `tests/component/zac/test_zac_documenten.py`; upload helpers of the existing document tests move to
  `zac.py` if a second module needs them.
- Reuses: the upload of `test_document_can_be_deleted`, `zac_zaak`.
- Risks: the 500 MB limit is left out: one upload of that size per run costs more than it checks; the refusal above the
  limit can use the configured limit if ZAC exposes it.

### Z7: CMMN taken (2.5 days, 4 tests)

- Gaps: intake afronden ontvankelijk, then start and complete Goedkeuren, Advies intern, Advies extern (with e-mail,
  prefilled initiator) and Document verzenden: mandatory fields, toelichting stored, mail sent, completed taken leave
  the lists; aanvullende informatie with each outcome and its mail and PDF; Goedkeuren signs the selected document;
  taak fatale datum capped at the zaak's.
- Files: `tests/component/zac/test_zac_taken.py`.
- Bootstrap: `ZacParameters` activates only AANVULLENDE_INFORMATIE today; add the other human task plan items as
  further `ZacPart`s (opt-in profile settings, as `zac_aanvullende_informatie`), since they change the estate's
  zaakafhandelparameters.
- Risks: environments that do not allow the opt-in skip these tests.

### Z8: rights per role (2 days, 6 tests)

- Gaps: on an afgehandelde zaak a behandelaar and coordinator cannot edit details, dates, betrokkenen or send mail, a
  recordmanager and beheerder can (not dates) and can heropenen; document rights per role and lock state; ZAC's
  `/rest/admin` refused for every role but beheerder; only a coordinator may verdelen and vrijgeven; without
  brp_zoeken no person search and initiator changes only to a bedrijf; the group list of a zaak offers only groups
  with rights on the zaaktype in PABC.
- Files: `tests/component/zac/test_zac_rechten.py`.
- Reuses: `ZAC_ROLE_USERS`, `zac_session` per user, the refusal pattern of `test_zac_refuses_a_call_below_its_least_role`.
- Risks: PABC's mapping is podiumd-tests' own domain (`ZAC_DOMAIN`); never change the estate's PABC dataset.

### Z9: productaanvraag (2 days, 5 tests)

- Gaps: betrokkenen (BSN, KvK, KvK with vestigingsnummer) become initiator and betrokkene rollen with the right
  roltype, several of them, a mismatching vestiging gives an error; a productaanvraag of a type ZAC does not handle
  lands in Inbox productaanvragen and becomes a zaak from there; aanvraagspecifieke contactgegevens stored on the zaak;
  the form's geometry and documents (once, kanaal E-formulier); groep and behandelaar from the zaakafhandelparameters;
  no duplicate zaken.
- Files: `tests/integration/test_productaanvraag.py`.
- Bootstrap: none new; the productaanvraag objects get betrokkenen and geometry in `make_productaanvraag`.
- Reuses: `productaanvraag_zaak`, the BRP and KvK test sets, `objecten`.
- Risks: the inbox case leaves a productaanvraag that ZAC does not turn into a zaak by itself: delete it in cleanup.

### Z10: zaakafhandelparameters (2.5 days, 4 tests)

- Gaps: saved fields persist (gegevens, waarschuwingsvensters 0 to 31, zaakbeeindig gegevens, mailgegevens,
  statusmail); a new zaaktype version keeps all of them after ZAC's synchronisation, and a changed default groep
  applies only to new zaken (the behaviour of known issue podiumd-chart-37); only PABC-authorised groups are offered
  and an unauthorised default groep is cleared; the inrichtingscheck rejects a zaaktype without roltype Behandelaar or
  Initiator. From Z2: hoofdzaak and deelzaak koppelen shows on both zaken; the hoofdzaak cannot be afgehandeld while a
  deelzaak is open, can after the deelzaak is closed or ontkoppeld; ontkoppelen of a closed deelzaak; a deelzaak
  cannot become deel- or hoofdzaak again (IS_DEELZAAK, ALREADY_DEELZAAK, HAS_DEELZAKEN).
- Files: new `tests/component/zac/test_zac_zaaktype_versies.py`, `test_zac_zaakafhandelparameters.py`; the hoofd- and
  deelzaak tests in `test_zac_relaties.py`. The throwaway zaaktype lists itself as deelzaaktype.
- Bootstrap: none; the tests make a throwaway zaaktype (`seed/catalogi.py`: `make_publishable_zaaktype`, `publish`)
  and configure it in ZAC through the admin API as step `zac-bpmn-process` does for its zaaktype; cleanup removes the
  zaaktype with snippet `openzaak_catalogi_types` and its PABC entity type.
- Risks: never write the zaakafhandelparameters of an estate's zaaktype; ZAC has no call to delete a zaaktype's
  configuration (as zac-9 notes for the BPMN one): check what a deleted throwaway zaaktype leaves in ZAC before the
  batch, and keep the count of throwaways per run at one.

### Z11: search, werklijsten and signaleringen (2 days, 5 tests)

- Gaps: signalering settings take effect, dashboard and mail signals for zaak and taak toegewezen and document
  toegevoegd; a completed taak leaves the takenlijst; text search finds zaken (also the Open Formulieren kenmerk) and
  Solr special characters give no error; verdelen to a group without behandelaar removes the behandelaar; werkvoorraad
  indicaties DEELZAAK, HOOFDZAAK, VERLENGD, OPGESCHORT, HEROPEND.
- Files: `tests/component/zac/test_zac_toekennen.py`, new `test_zac_zoeken.py`.
- Reuses: `search`, `wait_in_werkvoorraad`, the role users (a signalering goes to another user than the one who acts),
  Z1, Z2 and Z4 for the zaken with indicaties.
- Risks: signaleringen for expiry need ZAC's signaleringen CronJob: leave those out; Solr indexing delays need
  `wait_until`.

### Z12: betrokkenen (1.5 days, 4 tests)

- Gaps: the same person with the same rol cannot be added twice; betrokkene and initiator ontkoppelen (reden
  required); initiator changed from persoon to bedrijf and back keeps one initiator; a bedrijf rol stored in Open Zaak
  as niet-natuurlijk persoon with only KvK and vestigingsnummer; the e-mail address ZAC takes from Open Klant (single,
  voorkeur, else first).
- Files: `tests/component/zac/test_zac_klanten.py`.
- Reuses: `send_with_person`, `person_key`, the BRP and KvK test sets, `make_digitaal_adres`.

## Not planned

- UI-only behaviour (layout, dialogs, labels such as "(inactief)"), AD login, Graylog logging.
- More than 120 zaaktypen in the werklijsten, the 500 MB upload, bulk verdelen of 100 zaken: they need volume
  seeding beyond what a shared environment should carry; revisit with the perf tier's volume data.
- PDF/A conformance of generated PDFs: needs a validator (veraPDF) in the suite's image.
- Keycloak group changes (rename, inactive, delete), referentietabellen and mail template CRUD, zaakspecifiek
  autorisatie: they change shared configuration; possible with podiumd-tests' own groups and names once the user
  wants them.
- Low-priority gaps not named above; they follow the batch of their area when one is ported.
