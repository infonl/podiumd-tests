# Requests for podiumd-infra

## kees00: Open Zaak knows OMC's API client

OMC reads the zaak and its status from Open Zaak with a ZGW token issued as `omc`
(`omc.settings.zgw.auth.jwt.issuer`, secret `omc.settings.zgw.auth.jwt.secret`). On kees00 Open Zaak answers
403 "Client identifier bestaat niet" (2026-10-19), so OMC answers every notification with 412 and sends nothing.

Add to Open Zaak's configuration, as podiumd-minikube and ExternalsPodiumD do:

```yaml
openzaak:
  configuration:
    data: # setup_configuration
      vng_api_common_credentials:
        items:
          - identifier: omc
            secret: <omc.settings.zgw.auth.jwt.secret>
      vng_api_common_applicaties:
        items:
          - uuid: 746c65d7-b88e-4043-a1c0-15451004fbfa
            client_ids: [omc]
            heeft_alle_autorisaties: true
            label: OMC
```

OMC also reads Open Klant, Objecten and Objecttypen with tokens of identifier `omc`
(`omc.settings.zgw.auth.key.*`); check that those token auths exist too.

Done when `podiumd-tests run --env kees00 --tier full -- tests/integration/test_omc.py` passes.
