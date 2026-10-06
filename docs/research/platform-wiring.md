# Platform wiring that the source suites depend on

Analysed 2026-10-06, read-only, from podiumd-testautomation (TA, 180 specs),
ExternalsPodiumD smoke tests (EX), podiumd-minikube and podiumd-infra tests
(MK/PI), and the podiumd chart 4.9.3. "Wiring" is PodiumD configuration that
TA's `test-seeding/scripts/seed-omgeving.sh` applies to an environment and
never removes. It is not test data and not a test credential.

## Wiring items

| W | What | In a normal PodiumD deployment? |
|---|---|---|
| W1 | OI DigiD/eHerkenning OIDC config against the Keycloak realm, pre-provisioned OI users | No. The realm has no `bsn`/`eherkenning` scopes; real environments use real DigiD/eHerkenning |
| W2 | Keycloak realm roles, client roles, user profile, redirect URIs | Mostly yes (`keycloak-podiumd-realm-config.yaml`); the seed adds test users, the bsn/eherkenning scopes and extra hosts |
| W3 | ON kanalen (zaken, statussen, documenten, partijen, internetaken), NotificationsConfig in OZ/OK | Partly, per environment through `configuration.data`; statussen, partijen, internetaken and OK config are not in the chart |
| W4 | OI ZGW services and API group | Yes where OI shows zaken (environment owner, setup_configuration) |
| W5 | OI CMS pages (welkom, mijn-zaken, mijn-profiel, berichten, contactformulier) | Partly; gemeenten build their own CMS, the slugs and texts are seed-specific |
| W6 | OI → OK2 service, OpenKlant2Config | No (manual or environment owner) |
| W7 | OK2 medewerker actor for the KCC test user | Test-user data |
| W8 | OI contact flow, ContactFormSubjects, KlantenSysteemConfig | No |
| W9 | OF forms `poc-klacht-test`, `vestiging-test` | No |
| W10 | OF ZGW registration backend, OZ autorisaties for open-formulieren (`max_va=openbaar`) | Partly; per-form backends and test-tailored autorisaties are seed-only |
| W11 | OAB ZGW services, OAB role users | Partly |
| W12 | Objecten/Objecttypen for the ITA chain | Mostly yes (`create-required-objecttypen` job) |
| W13 | OZ catalogus `TEST`, zaaktype `TEST-FORMULIER` | No; the chart has `zaaktype-voor-e2e-testen` (test data, see §4 B of PLAN.md) |
| W14 | OK2 TokenAuth `seeder` | Test credential |

TA also overwrites the OZ JWT secrets of the real clients `open-formulieren`,
`open-inwoner`, `zac` and `zgw-test` with fixed values. On a real environment
that breaks Open Formulieren, Open Inwoner and ZAC unless the values match.

## Which TA specs need wiring

| Folder | A: no wiring | B: test data or test credentials only | C: needs wiring |
|---|---|---|---|
| smoke (15) | 5 | 5 (01, 66, 72, 92, 113) | 5 (00 W4/W5/W9/W10, 04 W5, 05/82/99 W1) |
| interaction (27) | 0 | 7 (02, 03, 09, 10, 20, 35, 145) | 20 (portal W1/W4/W5/W6/W8, ITA W7/W12, OF W9/W10, OAB W11) |
| regression (134) | 27 | 50 (OZ API, OK2 token, OMC, Keycloak users) | 57 (W3 ×13, W10 ×3, ITA W7/W12 ×4, OF ×10, portal ×21, OAB ×6) |

The biggest single dependency is W1: about 40 portal specs log in through the
Keycloak "DigiD/eHerkenning mock". MK and PI tests use none of W1–W14.

Specs that need a seed script `seed-omgeving.sh` does not run: 143-oab
(destructive OAB zaken), 158 (OF eHerkenning vestiging), 183/185 (OF DigiD,
payment demo), 184 (ITA object instances).
