"""The perf tier: Locust users (locustfile.py) and the thresholds their stats must meet (stats.py).

This package must not import locust: it monkey-patches the standard library on import, which only
the Locust process may have.
"""

# Endpoint name -> the component it needs. Reads are TA's k6 api-perf.js; writes create and delete
# their own objects; searches are what users type in ZAC, KISS and the portal.
ENDPOINTS = {
    "oz_zaken": "openzaak",
    "oz_zaaktypen": "openzaak",
    "ok2_partijen": "openklant",
    "brp_persoon": "api-proxy",
    "kc_discovery": "keycloak",
    "oz_zaak_create": "openzaak",
    "ok2_klantcontact_create": "openklant",
    "oz_zaken_by_bsn": "openzaak",
    "ok2_partij_by_bsn": "openklant",
    "obj_vac_create": "objecten",
    "obj_vac_search": "objecten",
    "zac_search": "zac",
    "kiss_search": "kiss",
    "oi_search": "openinwoner",
    # Open Zaak's performance_test (open-zaak/open-zaak): documents at a deep page with ordering, and zaken for a
    # client with rights on one zaaktype (bootstrap step openzaak-client-productaanvraag, which needs ZAC).
    "oz_documenten_ordered": "openzaak",
    "oz_zaken_one_zaaktype": "zac",
}
