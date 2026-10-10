"""Names of what bootstrap creates: clients, store keys, test catalogus and types, objecttypes."""

from __future__ import annotations

PREFIX = "ptest-bootstrap"
# The suite's own ZGW client in Open Zaak, and its test catalogus: the client may only touch
# zaken, documenten and besluiten of zaaktypen in that catalogus (PLAN.md §11a).
ZGW_CLIENT_ID = "ptest-bootstrap-zgw"
ZGW_STORE_KEY = "ptest_bootstrap_zgw_secret"
ZGW_OPENBAAR_CLIENT_ID = "ptest-bootstrap-zgw-openbaar"
ZGW_OPENBAAR_STORE_KEY = "ptest_bootstrap_zgw_openbaar_secret"
ZGW_NOAUTH_CLIENT_ID = "ptest-bootstrap-zgw-noauth"
ZGW_NOAUTH_STORE_KEY = "ptest_bootstrap_zgw_noauth_secret"
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
TEST_FORM = "ptest-bootstrap-klacht"
# Open Notificaties kanalen the ported tests subscribe on, with the filters of ExternalsPodiumD
# and podiumd-infra.
KANALEN = {"zaken": ["bronorganisatie", "zaaktype", "vertrouwelijkheidaanduiding"]}
# API tokens (TokenAuth identifier = store key).
# The productaanvraag chain (Objecten → Open Notificaties → ZAC → Open Zaak) runs on the
# environment's own wiring: profile settings productaanvraag_type and productaanvraag_zaaktype.
PRODUCTAANVRAAG_OBJECTTYPE = "Productaanvraag-Dimpact"
ZGW_PRODUCTAANVRAAG_CLIENT_ID = "ptest-bootstrap-zgw-productaanvraag"
ZGW_PRODUCTAANVRAAG_STORE_KEY = "ptest_bootstrap_zgw_productaanvraag_secret"
OBJECTEN_STORE_KEY = "ptest_bootstrap_objecten_token"
# ITA forwards internetaken to Afdeling and Groep objects, finds a user's groepen in their Medewerker
# object and logs each action in an Activiteitenlog object; the suite creates and cleans up all four.
ITA_OBJECTTYPES = ("Afdeling", "Groep", "Medewerker", "Activiteitenlog")
# Objecttypes KISS indexes for its search (its elastic-sync jobs vac and kennisbank).
KISS_OBJECTTYPES = ("VAC", "Kennisartikel")
OPENKLANT_STORE_KEY = "ptest_bootstrap_openklant_token"
# Open Inwoner's token in Open Klant (wiring W6).
OPENKLANT_OPENINWONER_STORE_KEY = "ptest_bootstrap_openklant_openinwoner_token"
