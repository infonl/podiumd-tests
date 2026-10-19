# Requests for podiumd-infra

## kees00: OMC has Notify template ids

The Open Zaak client works (2026-10-19 17:05). Now OMC answers every notification with 412: "The settings do not
contain a given value, or the value is empty: NOTIFY_TEMPLATEID_EMAIL_ZAAKCREATE". Every `NOTIFY_TEMPLATEID_*` of
the OMC pod on kees00 is empty: the chart has no default for them.

Set them as podiumd-minikube and ExternalsPodiumD icat ontw do; the mock accepts any uuid:

```yaml
omc:
  settings:
    notify:
      templateId:
        decisionMade: "00000000-0000-1000-8000-000000000000"
        email:
          zaakCreate: 716369c8-edba-44ff-a213-a045b4a8d246
          zaakUpdate: ed368ce1-89b5-4826-b34c-3f563fb418a9
          zaakClose: 123e14bd-181e-4a93-a15b-071bee52e383
        sms:
          zaakCreate: b2a51bd0-df3c-492a-9097-9384fa34060a
          zaakUpdate: 76e9ebe7-edae-4fac-ad3c-834586851ef2
          zaakClose: a8d0026a-afab-48e4-b034-c4d85bb3ca60
```

Done when `podiumd-tests run --env kees00 --tier full -- tests/integration/test_omc.py` passes.
