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

## kees00: Open Klant has the actor that OMC_ACTOR_ID names

After a delivery receipt (`POST /Notify/Confirm`) OMC registers a klantcontact in Open Klant and then links its
actor `OMC_ACTOR_ID` (chart value `omc.settings.omc.actor.id`, default `3a91832c-f2bd-4f22-8d5b-557b44c0ed38`) through
`POST actorklantcontacten`. Without that actor Open Klant answers 400 "Actor object bestaat niet." and OMC answers
the receipt with 500. podiumd-tests' `test_delivery_receipt_becomes_a_klantcontact` skips until the actor exists.

Either create an actor in Open Klant and set `omc.settings.omc.actor.id` to its uuid, or create the actor with that
uuid (Open Klant's API assigns uuids itself, so this needs Open Klant's Django shell or admin), for example a
`geautomatiseerde_actor` named "OMC".
