# Requests for podiumd-infra

## kees00: OMC sends Notify requests to podiumd-tests' Notify mock

podiumd-tests' OMC tests (`tests/integration/test_omc.py`) check that OMC mails or texts the initiator of a zaak and
that a delivery receipt becomes a klantcontact in Open Klant. They run only where OMC's Notify base URL is the
mock server that `podiumd-tests bootstrap` deploys (step `infra-mock-server`); elsewhere they skip. On kees00 OMC
posts to `https://api.notifynl.nl`, so the tests skip there.

Set in kees00's podiumd values, as podiumd-minikube does (`values.yaml`, section omc):

```yaml
omc:
  settings:
    notify:
      api:
        baseUrl: http://ptest-bootstrap-mock-server.<namespace>/notify
        key: <any key in NotifyNL's format name-serviceId-secret>
```

- The mock accepts any key; OMC's Notify client refuses one that is not in the format above.
- OMC keeps only the host of the base URL; the `/notify` path is not used.
- The template ids stay as they are (the chart defaults, the same as ExternalsPodiumD icat ontw).
- The mock server exists after `podiumd-tests bootstrap --env kees00`; before that OMC's Notify calls fail.

Done when `podiumd-tests run --env kees00 --tier full -- tests/integration/test_omc.py` runs the tests instead of
skipping them.
