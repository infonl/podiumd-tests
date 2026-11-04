# Open requests for podiumd-infra

## Open Archiefbeheer's Open Klant and Objecten registers on kees00 (2026-11-04)

kees00 (`values/kees00/podiumd.yaml`) has no `openarchiefbeheer` token in Objecten or Open Klant, and Open
Archiefbeheer has no `objecten-api` or Open Klant service. ExternalsPodiumD (dim1, dim3, mayk, icat) and
podiumd-minikube (54c281c, `values.yaml:1549`) configure all of them. Without the Objecten permission, OAB's
destruction of a zaak with a productaanvraag fails with 403 (IN-2784).

Add, as ExternalsPodiumD:

- Objecten tokenauth item `openarchiefbeheer` with the chart's fixed productaanvraag uuid, as the `zaak` and
  `formulier` items already use it:

  ```yaml
  permissions:
    - object_type: 11a5f7fd-013e-4e29-9cd1-738249fc3479
      mode: read_and_write
  ```

- Open Klant tokenauth item `openarchiefbeheer`.
- In Open Archiefbeheer's configuration: services `objecten-api` and `openklant-klantinteracties` (`api_key`,
  `Token <token>`) and `external_registers` on.

Do not use `REP_ZAC_PRODUCTAANVRAAG_UUID_REP` or the 4.10.1 script
`migrate-objecten-openarchiefbeheer-permissions-4.10.1.py`: both are for SSC values, where each municipality has
its own uuid. helm-charts #696 (script support for a literal uuid) is closed for that reason.

Verify: `podiumd-tests run --env kees00 -k test_destruction_deletes_the_productaanvraag_of_the_zaak`.
