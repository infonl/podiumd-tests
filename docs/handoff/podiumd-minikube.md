# Requests to podiumd-minikube

## OMC: let podiumd-tests' own zaaktype reach the besluit, taak and bericht scenarios

podiumd-tests now tests OMC's documented scenarios (tests/integration/test_omc_scenarios.py, test_omc_bericht.py).
The "mail sent" cases skip on minikube because OMC's settings exclude them. Request, in `values.yaml` under
`omc.settings`, limited to podiumd-tests' test zaaktype so real zaaktypen keep getting no mail, as on ExternalsPodiumD:

- Besluit genomen:
  - `zgw.variable.objectType.decisionInfoObjectType.uuids: "320da3a6-d87d-5854-88ad-e8c534bc7e8b"`, podiumd-tests'
    informatieobjecttype `ptest-bootstrap-bijlage` (fixed uuid, in place on minikube);
  - `zgw.whitelist.decisionMade.ids: "ptest-bootstrap-klacht"` instead of `niet-bestaande-id`.
- Taak toegewezen:
  - `zgw.whitelist.taskAssigned.ids: "ptest-bootstrap-klacht"`;
  - `notify.templateId.email.taskAssigned`: any uuid (the Notify mock accepts any template);
  - `zgw.variable.objectType.taskObjectType.uuid: "81a4f784-997b-5ab7-a4c5-29c65410ee8b"`, podiumd-tests' taak
    objecttype `ptest-bootstrap-taak` (bootstrap step objecttypen-taak, in place on minikube).
- Bericht ontvangen (Open VTB): `notify.templateId.email.messageBox`: any uuid. It helps only from OMC 2.3.2 on
  (omc-5: OMC 2.3.1 cannot read an Open VTB 0.2.0 bericht).

Agreed by podiumd-minikube (2026-11-13), to deploy in one go now that both uuids exist.
