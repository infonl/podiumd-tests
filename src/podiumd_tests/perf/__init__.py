"""The perf tier: Locust users (locustfile.py) and the thresholds their stats must meet (stats.py).

This package must not import locust: it monkey-patches the standard library on import, which only
the Locust process may have.
"""

# Endpoint name -> the component it needs; ported from TA's k6 api-perf.js.
ENDPOINTS = {
    "oz_zaken": "openzaak",
    "oz_zaaktypen": "openzaak",
    "ok2_partijen": "openklant",
    "brp_persoon": "api-proxy",
    "kc_discovery": "keycloak",
}
