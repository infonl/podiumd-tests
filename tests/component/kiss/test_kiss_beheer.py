"""KISS beheer and nieuws en werkinstructies, through its BFF: what the beheerder and redacteur set up, the KCC sees.

Ported from KISS's own Playwright suite (Kiss.Bff.EndToEndTest), as API calls of the pages it drives.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import NamedTuple

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.oidc import challenge_session
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("kiss", "keycloak")]

E2E = "upstream klantinteractie-servicesysteem/KISS-frontend Kiss.Bff.EndToEndTest"


@pytest.fixture(name="kiss_as")
def fixture_kiss_as(
    podiumd_env: Environment, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> Callable[[KeycloakUser], requests.Session]:
    """A KISS session of a test user, logged in through Keycloak without a browser."""

    def login(user: KeycloakUser) -> requests.Session:
        need_bootstrap(user.name)
        return challenge_session(podiumd_env, urls["kiss"], user.username, podiumd_env.credentials.get(user.store_key))

    return login


class Beheer(NamedTuple):
    """A KISS beheer list: where to add, list, change and delete an item, and its name field."""

    add: str
    overview: str
    change: str
    delete: str
    field: str


BEHEER = {
    "kanaal": Beheer("KanaalToevoegen", "KanalenBeheerOverzicht", "KanaalBewerken", "KanaalVerwijderen", "naam"),
    "gespreksresultaat": Beheer(
        "Gespreksresultaten", "Gespreksresultaten", "Gespreksresultaten", "Gespreksresultaten", "definitie"
    ),
    "skill": Beheer("Skills", "Skills", "Skills", "Skills", "naam"),
}


@pytest.mark.parametrize(
    "kind",
    [
        pytest.param(
            "kanaal",
            marks=pytest.mark.source(f"{E2E}/Beheer/KanaalScenarios.cs", "Adding, editing and deleting a kanaal."),
        ),
        pytest.param(
            "gespreksresultaat",
            marks=pytest.mark.source(
                f"{E2E}/Beheer/GesprekresultatenScenarios.cs", "Adding, editing and deleting a gespreksresultaat."
            ),
        ),
        pytest.param(
            "skill",
            marks=pytest.mark.source(f"{E2E}/Beheer/SkillScenarios.cs", "Adding, editing and deleting a skill."),
        ),
    ],
)
def test_beheerder_adds_changes_and_deletes(
    kiss_as: Callable[[KeycloakUser], requests.Session], urls: dict[str, str], registry: ResourceRegistry, kind: str
) -> None:
    """The KISS beheerder adds an item, renames it, and deletes it; the overview follows each step."""
    beheer, api = BEHEER[kind], urls["kiss"] + "/api"
    kiss = kiss_as(ADMIN)
    name = registry.tagged(kind)

    def listed() -> dict[str, str]:
        found = entries(expect_status(kiss.get(f"{api}/{beheer.overview}"), HTTPStatus.OK).json())
        return {str(i[beheer.field]): str(i["id"]) for i in found}

    expect_status(
        kiss.post(f"{api}/{beheer.add}", json={beheer.field: name}), HTTPStatus.CREATED, HTTPStatus.NO_CONTENT
    )
    item = listed()[name]
    registry.add(f"KISS {kind} {name}", lambda: kiss.delete(f"{api}/{beheer.delete}/{item}"))
    renamed = f"{name}-gewijzigd"
    body = {"id": item, beheer.field: renamed}
    expect_status(kiss.put(f"{api}/{beheer.change}/{item}", json=body), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert listed().get(renamed) == item
    expect_status(kiss.delete(f"{api}/{beheer.delete}/{item}"), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    assert item not in listed().values()


@pytest.mark.source(
    f"{E2E}/NieuwsEnWerkInstructies/NieuwsEnWerkInstructiesScenarios.cs",
    "Nieuws and werkinstructies: the important message count on the home page and marking a message read.",
)
def test_published_bericht_reaches_the_kcc_and_is_marked_read(
    kiss_as: Callable[[KeycloakUser], requests.Session], urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """The redacteur publishes an important bericht with a skill; the KCC sees it unread, counted, then reads it.

    Only a redacteur may publish: the KCC is refused.
    """
    api = urls["kiss"] + "/api"
    redacteur, kcc = kiss_as(ADMIN), kiss_as(KCC)
    skill = expect_status(redacteur.post(f"{api}/Skills", json={"naam": registry.tagged("skill")}), 201).json()
    registry.add(f"KISS skill {skill['id']}", lambda: redacteur.delete(f"{api}/Skills/{skill['id']}"))
    titel = registry.tagged("bericht")
    bericht = {
        "titel": titel,
        "inhoud": "<p>podiumd-tests</p>",
        "isBelangrijk": True,
        "skills": [skill["id"]],
        "publicatieDatum": datetime.now(UTC).isoformat(),
        "type": "Nieuws",
    }
    expect_status(kcc.post(f"{api}/Berichten", json=bericht), HTTPStatus.FORBIDDEN)
    created = expect_status(redacteur.post(f"{api}/Berichten", json=bericht), HTTPStatus.CREATED).json()
    registry.add(f"KISS bericht {created['id']}", lambda: redacteur.delete(f"{api}/Berichten/{created['id']}"))

    def seen() -> JsonObject:
        published = expect_status(kcc.get(f"{api}/berichten/published", params={"search": titel}), HTTPStatus.OK)
        return next(b for b in entries(published.json()) if b["id"] == created["id"])

    def featured() -> int:
        return int(expect_status(kcc.get(f"{api}/berichten/featuredcount"), HTTPStatus.OK).json()["count"])

    assert seen()["isGelezen"] is False
    unread = featured()
    expect_status(kcc.put(f"{api}/berichten/{created['id']}/read", json={"isGelezen": True}), HTTPStatus.OK, 204)
    assert seen()["isGelezen"] is True
    assert featured() == unread - 1
