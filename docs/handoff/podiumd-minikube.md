# Requests to podiumd-minikube

## OMC: let podiumd-tests' own zaaktype reach the besluit, taak and bericht scenarios

podiumd-tests now tests OMC's documented scenarios (tests/integration/test_omc_scenarios.py, test_omc_bericht.py).
The "mail sent" cases skip on minikube because OMC's settings exclude them. Request, in `values.yaml` under
`omc.settings`, limited to podiumd-tests' test zaaktype so real zaaktypen keep getting no mail, as on ExternalsPodiumD:

- Besluit genomen:
  - `zgw.variable.objectType.decisionInfoObjectType.uuids`: the uuid of podiumd-tests' informatieobjecttype
    `ptest-bootstrap-bijlage` (sets `ZGW_VARIABLE_OBJECTTYPE_DECISIONINFOOBJECTTYPE_UUIDS`; today
    `7a4927ec-888c-422d-9bca-b248f454f48f`, it changes when bootstrap recreates the test zaaktype);
  - `zgw.whitelist.decisionMade.ids: "ptest-bootstrap-klacht"` instead of `niet-bestaande-id`.
- Taak toegewezen:
  - `zgw.whitelist.taskAssigned.ids: "ptest-bootstrap-klacht"`;
  - `notify.templateId.email.taskAssigned`: any uuid (the Notify mock accepts any template);
  - `zgw.variable.objectType.taskObjectType.uuid`: the uuid of a taak objecttype. podiumd-tests will add a bootstrap
    step that creates that objecttype with a fixed uuid; tell us which uuid you set, or take ours once the step exists.
- Bericht ontvangen (Open VTB): `notify.templateId.email.messageBox`: any uuid. It helps only from OMC 2.3.2 on
  (omc-5: OMC 2.3.1 cannot read an Open VTB 0.2.0 bericht).
- Message handling: if it is meant to be off, as values.yaml says, give `whitelist.message.allowed` as the string
  `"false"`: the chart's `default` turns a boolean `false` into `"true"` (omc-7; the deployed ConfigMap holds `true`).

Answer: yes or no per item in this file (or by message to the podiumd-tests session).
