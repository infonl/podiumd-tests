# Requests to podiumd-minikube

## Allow podiumd-tests to write run-tagged zaaktypen in ZAC's default catalogus (ALG)

ZAC 5.9.1 reads only its default catalogus (`CATALOGUS_DOMEIN`, ALG on minikube) for three behaviours podiumd-tests
cannot test from its own PTEST catalogus:

- the signaleringen job's "zaak verloopt bijna" mail (`ZaakTaskDueDateEmailNotificationService`, zaaktypen of the
  default catalogus whose zaakafhandelparameters set a waarschuwingsvenster);
- the zaakafhandelparameters list (`listZaaktypeConfigurations`): a new zaaktype appears there;
- the inrichtingscheck, which rejects a zaaktype without roltype Behandelaar or Initiator.

Request: allow podiumd-tests, behind a new profile setting `zac_catalogus_writes: true` in `envs/minikube.yaml`, to

- publish zaaktypen whose omschrijving and identificatie carry the run tag (`ptest-<run>-...`) in the ALG catalogus,
  with their own statustypen, roltypen, resultaattypen and informatieobjecttype links;
- save zaakafhandelparameters for those zaaktypen in ZAC;
- delete them at the test's cleanup: zaakafhandelparameters first, then the zaaktypen and their parts (published types
  through the existing Django-shell snippet, extended from PTEST to ALG for run-tagged types only), and in `sweep`
  for leftovers of a failed run.

podiumd-tests never changes or deletes ALG types it did not create, and never touches `zaaktype-voor-e2e-testen`.
Mail of the signaleringen test goes to Mailpit only.

Answer: yes or no in this file (or by message to the podiumd-tests session).
