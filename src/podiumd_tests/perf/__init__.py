"""The perf tier: Locust users (locustfile.py) and the thresholds their stats must meet (stats.py).

This package must not import locust: it monkey-patches the standard library on import, which only
the Locust process may have.
"""

from __future__ import annotations

import sys

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def locust_command(locustfile: Path, users: str, run_time: str, csv_prefix: Path, env: str) -> list[str]:
    """A headless Locust run of the locustfile against the environment, its CSVs at csv_prefix."""
    command = [sys.executable, "-m", "locust", "-f", str(locustfile), "--headless", "--only-summary"]
    command += ["--users", users, "--spawn-rate", users, "--run-time", run_time, "--exit-code-on-error", "0"]
    return [*command, "--csv", str(csv_prefix), "--podiumd-env", env]


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

# Anonymous requests through the public gateway, one Locust run each (tests/perf/test_gateway_perf.py), to compare
# gateway settings such as upstream keep-alive. Name -> (component, path, expected status); kiss_page also loads
# the scripts and stylesheets of the page.
GATEWAY_SCENARIOS = {
    "kiss_healthz": ("kiss", "/healthz", 200),
    "kiss_healthcheck": ("kiss", "/api/healthcheck", 200),
    "kiss_page": ("kiss", "/", 200),
    # KISS answers an anonymous API call with a challenge, without calling a backend.
    "kiss_challenge": ("kiss", "/api/search/sources", 302),
    # Control: a route that keeps upstream keep-alive.
    "openzaak_root": ("openzaak", "/zaken/api/v1/", 200),
}
