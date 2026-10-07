"""The klantcontactmedewerker in KISS and ITA: a browser login and the KISS register header."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.browser import challenge_login
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

# KISS proxies Open Klant's klantinteracties API under this path.
KISS_KLANTCONTACTEN = "/api/klantinteracties/api/v1/klantcontacten"


def kcc_login(page: Page, env: Environment, component: str) -> requests.Session:
    """The KCC test user's session in KISS ("kiss") or ITA ("ita")."""
    return challenge_login(page, env, env.profile.urls[component], KCC.username, env.credentials.get(KCC.store_key))


def kiss_register(kiss: requests.Session, kiss_url: str) -> dict[str, str]:
    """The header that sends a KISS proxy call to its default register (KISS has one per systeem)."""
    systemen = entries(expect_status(kiss.get(kiss_url + "/api/environment/registers"), 200).json()["systemen"])
    default = next(s for s in systemen if s.get("isDefault"))
    return {"systemIdentifier": str(default["identifier"])}
