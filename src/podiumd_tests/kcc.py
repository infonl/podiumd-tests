"""The klantcontactmedewerker in KISS and ITA: a browser login and the KISS register header."""

from __future__ import annotations

import json

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.browser import challenge_login
from podiumd_tests.json_data import entries
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

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


def ita_detail_text(ita: requests.Session, ita_url: str, taak: JsonObject) -> str:
    """ITA's detail of the contactverzoek, as JSON text: what the KCC user sees on its detail page.

    ITA shows it to members of the groep the taak is assigned to (ITA_GROEP for the KCC test user,
    bootstrap objecten-medewerker-kcc).
    """
    return json.dumps(expect_status(ita.get(f"{ita_url}/api/internetaken/{taak['nummer']}"), HTTPStatus.OK).json())


# ITA 3.3.2's access guard takes Open Klant's deprecated toegewezenAanActor (a bare reference to the
# first assigned actor) over the expanded actor with the same uuid: a groep assigned first is not seen
# as a groep. Fixed in ITA 3.3.4 (Interne-Taak-Afhandeling/ITA#582).
ITA_GROUP_ACCESS = pytest.mark.xfail(
    strict=True,
    raises=UnexpectedStatusError,
    reason="ITA 3.3.2 refuses a groep member a contactverzoek assigned to the groep first (403: its guard reads"
    " the deprecated toegewezenAanActor reference); fixed in ITA 3.3.4 (ITA#582)",
)
