"""The Locust runs of the perf tier: their command, endpoints and gateway scenarios.

This module must not import locust: it monkey-patches the standard library on import, which only
the Locust process may have.
"""

from __future__ import annotations

import json
import sys

from dataclasses import replace
from typing import TYPE_CHECKING

from podiumd_tests.bootstrap.steps import ZAC_ROLE_USERS
from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment

if TYPE_CHECKING:
    from argparse import ArgumentParser
    from collections.abc import Mapping
    from pathlib import Path


def locust_command(  # noqa: PLR0913  # the run's settings
    locustfile: Path, users: str, run_time: str, csv_prefix: Path, env: str, *, urls: Mapping[str, str]
) -> list[str]:
    """Return a headless Locust run of the locustfile against the environment at urls, its CSVs at csv_prefix.

    urls: the component URLs as this console reaches them (the `urls` fixture: in-cluster ones port-forwarded).
    """
    command = [sys.executable, "-m", "locust", "-f", str(locustfile), "--headless", "--only-summary"]
    command += ["--users", users, "--spawn-rate", users, "--run-time", run_time, "--exit-code-on-error", "0"]
    command += ["--csv", str(csv_prefix), "--csv-full-history"]
    return [*command, "--podiumd-env", env, "--podiumd-urls", json.dumps(dict(urls), sort_keys=True)]


def add_environment_arguments(parser: ArgumentParser) -> None:
    """Add a locustfile's --podiumd-env and --podiumd-urls, which locust_command sets."""
    parser.add_argument("--podiumd-env", required=True, help="environment profile name")
    parser.add_argument("--podiumd-urls", required=True, help="JSON of the component URLs this console reaches")


def locust_environment(env: str, urls: str) -> Environment:
    """Return the environment of the profile with the component URLs of --podiumd-urls (JSON) in place of its own."""
    profile = load_profile(env, default_envs_dir())
    return Environment(replace(profile, urls={**profile.urls, **json.loads(urls)}))


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
    # Baseflow's DMF PoC document mix (cg-dmf-poc k6/perf.js) and Open Notificaties' notificatie.
    "oz_document_get": "openzaak",
    "oz_document_create": "openzaak",
    "oz_document_patch": "openzaak",
    "oz_oio_list": "openzaak",
    "oz_zio_create": "openzaak",
    "onrc_notificatie": "opennotificaties",
    # Keycloak's password login and client-credentials grant, with ZAC's test users and its zac-admin-client.
    "kc_login": "zac",
    "kc_client_credentials": "zac",
    # ZAC's create-load.py: a zaak started in ZAC, and a document uploaded to it.
    "zac_zaak_create": "zac",
    "zac_document_upload": "zac",
}

# Keycloak's sizing guide: what one vCPU serves per second (keycloak.org high-availability, CPU and memory sizing).
KEYCLOAK_PER_VCPU = {"kc_login": 15, "kc_client_credentials": 120}
# The accounts of kc_login. Not the test admin: every Locust user logs in as the admin when it starts.
LOGIN_USERS = tuple(ZAC_ROLE_USERS.values())

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
