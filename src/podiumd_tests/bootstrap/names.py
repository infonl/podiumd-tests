"""Names of what bootstrap creates: clients, store keys, test catalogus and types, objecttypes."""

from __future__ import annotations

PREFIX = "ptest-bootstrap"
# The suite's own ZGW client in Open Zaak, and its test catalogus: the client may only touch
# zaken, documenten and besluiten of zaaktypen in that catalogus.
ZGW_CLIENT_ID = "ptest-bootstrap-zgw"
ZGW_STORE_KEY = "ptest_bootstrap_zgw_secret"
ZGW_OPENBAAR_CLIENT_ID = "ptest-bootstrap-zgw-openbaar"
ZGW_OPENBAAR_STORE_KEY = "ptest_bootstrap_zgw_openbaar_secret"
ZGW_NOAUTH_CLIENT_ID = "ptest-bootstrap-zgw-noauth"
ZGW_NOAUTH_STORE_KEY = "ptest_bootstrap_zgw_noauth_secret"
ZGW_GESLOTEN_CLIENT_ID = "ptest-bootstrap-zgw-gesloten"
ZGW_GESLOTEN_STORE_KEY = "ptest_bootstrap_zgw_gesloten_secret"
# Scope prefixes per component on the test catalogus, and the Catalogi API scopes.
ZGW_COMPONENTS: dict[str, tuple[str, ...]] = {
    "zrc": ("zaken.", "audittrails."),
    "drc": ("documenten.", "audittrails."),
    "brc": ("besluiten.", "audittrails."),
}
CATALOGI_SCOPES = ("catalogi.lezen", "catalogi.schrijven")
TEST_CATALOGUS_DOMEIN = "PTEST"
TEST_CATALOGUS_RSIN = "000000000"
# The suite's client in Open Notificaties: publishes and subscribes.
NRC_CLIENT_ID = "ptest-bootstrap-nrc"
NRC_STORE_KEY = "ptest_bootstrap_nrc_secret"
# Test zaaktype and informatieobjecttype in the test catalogus (TA TEST-FORMULIER), and the
# Open Formulieren test form that registers zaken on it (TA poc-klacht-test).
TEST_ZAAKTYPE = "ptest-bootstrap-klacht"
TEST_IOT = "ptest-bootstrap-bijlage"
TEST_BESLUITTYPE = "ptest-bootstrap-besluit"
# The zaaktype ZAC handles with podiumd-tests' BPMN process (bootstrap step zac-bpmn-process).
BPMN_ZAAKTYPE = "ptest-bootstrap-bpmn"
BPMN_IOT = "ptest-bootstrap-bpmn-bijlage"
BPMN_BESLUITTYPE = "ptest-bootstrap-bpmn-besluit"
# ZAC's rights on podiumd-tests' own zaaktypen, apart from the estate's PABC dataset: realm roles of test users,
# PABC's functional roles of those names mapped to ZAC application roles, in PABC's domain of those zaaktypen.
ZAC_DOMAIN = "ptest-bootstrap"
# The test admin's realm role.
ZAC_FUNCTIONAL_ROLE = "ptest-bootstrap-zac"
# ZAC's base roles from fewest to most rights; since ZAC 5.9 each has the rights of the ones before it.
ZAC_BASE_ROLES = ("raadpleger", "behandelaar", "coordinator", "recordmanager", "beheerder")
# brp_zoeken is a plus role: without a base role ZAC 5.9.1 refuses the user.
ZAC_FUNCTIONAL_ROLES = {
    ZAC_FUNCTIONAL_ROLE: ("behandelaar", "coordinator"),
    **{f"{ZAC_FUNCTIONAL_ROLE}-{role}": (role,) for role in ZAC_BASE_ROLES},
    f"{ZAC_FUNCTIONAL_ROLE}-brp-zoeken": ("brp_zoeken",),
}
# ZaakBrug drives ZDS, whose StUF zaaktype code is at most 10 characters; the klacht id (22) is too long.
ZAAKBRUG_ZAAKTYPE = "ZBTESTPT"
ZAAKBRUG_IOT = "ptest-bootstrap-zb-bijlage"
ZAAKBRUG_BESLUITTYPE = "ptest-bootstrap-zb-besluit"
# Two published versions of one zaaktype, the first expired (StUF code at most 10 characters).
ZAAKBRUG_VERSIES_ZAAKTYPE = "ZBVERSIE"
ZAAKBRUG_VERSIES_IOT = "ptest-bootstrap-zbv-bijlage"
ZAAKBRUG_VERSIES_BESLUITTYPE = "ptest-bootstrap-zbv-besluit"
# A zaaktype with a resultaattype per brondatum afleidingswijze, for the archiefactiedatum tests.
ARCHIEF_ZAAKTYPE = "ptest-bootstrap-archief"
ARCHIEF_IOT = "ptest-bootstrap-archief-bijlage"
ARCHIEF_BESLUITTYPE = "ptest-bootstrap-archief-besluit"
TEST_FORM = "ptest-bootstrap-klacht"
# The Ogone merchant of the payment tests in Open Formulieren; the tests play Ogone with its passphrase.
OGONE_MERCHANT = "ptest-bootstrap-ogone"
OGONE_STORE_KEY = "ptest_bootstrap_ogone_secret"
# The Worldline merchant; the mock server plays Worldline's Hosted Checkout API.
WORLDLINE_MERCHANT = "ptest-bootstrap-worldline"
WORLDLINE_STORE_KEY = "ptest_bootstrap_worldline_secret"
# Open Notificaties kanalen the ported tests subscribe on, with the filters of ExternalsPodiumD
# and podiumd-infra.
# The perf tier publishes on its own kanaal, which nothing subscribes to, so no app receives the load.
PERF_KANAAL = "ptest-bootstrap-perf"
KANALEN = {"zaken": ["bronorganisatie", "zaaktype", "vertrouwelijkheidaanduiding"], PERF_KANAAL: []}
# API tokens (TokenAuth identifier = store key).
# The productaanvraag chain (Objecten → Open Notificaties → ZAC → Open Zaak) runs on the
# environment's own wiring: profile settings productaanvraag_type and productaanvraag_zaaktype.
PRODUCTAANVRAAG_OBJECTTYPE = "Productaanvraag-Dimpact"
ZGW_PRODUCTAANVRAAG_CLIENT_ID = "ptest-bootstrap-zgw-productaanvraag"
ZGW_PRODUCTAANVRAAG_STORE_KEY = "ptest_bootstrap_zgw_productaanvraag_secret"
OBJECTEN_STORE_KEY = "ptest_bootstrap_objecten_token"
OBJECTTYPEN_STORE_KEY = "ptest_bootstrap_objecttypen_token"
# ITA forwards internetaken to Afdeling and Groep objects, finds a user's groepen in their Medewerker
# object and logs each action in an Activiteitenlog object; the suite creates and cleans up all four.
ITA_OBJECTTYPES = ("Afdeling", "Groep", "Medewerker", "Activiteitenlog")
# Objecttypes KISS indexes for its search (its elastic-sync jobs vac and kennisbank).
KISS_OBJECTTYPES = ("VAC", "Kennisartikel")
OPENKLANT_STORE_KEY = "ptest_bootstrap_openklant_token"
OPENVTB_STORE_KEY = "ptest_bootstrap_openvtb_token"
# Open Inwoner's token in Open Klant (wiring W6).
OPENKLANT_OI_STORE_KEY = "ptest_bootstrap_openklant_openinwoner_token"
