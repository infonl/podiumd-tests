"""KISS beheer and nieuws en werkinstructies, through its BFF: what the beheerder and redacteur set up, the KCC sees.

Ported from KISS's own Playwright suite (Kiss.Bff.EndToEndTest), as API calls of the pages it drives.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import NamedTuple

import pytest

from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.bootstrap.keycloak import KeycloakUser
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("kiss", "keycloak")]

E2E = "upstream klantinteractie-servicesysteem/KISS-frontend Kiss.Bff.EndToEndTest"


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
@pytest.mark.scenario("""
    Given the KISS beheerder is logged in to KISS
    When the beheerder adds a kanaal, gespreksresultaat or skill
    And renames it
    Then the overview shows it under its new name
    When the beheerder deletes it
    Then it is gone from the overview
""")
def test_beheerder_adds_changes_and_deletes(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    registry: ResourceRegistry,
    kind: str,
) -> None:
    """The KISS beheerder adds an item, renames it, and deletes it; the overview follows each step."""
    beheer, api = BEHEER[kind], f"{urls['kiss']}/api"
    kiss = kiss_session(ADMIN)
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


def _skill(redacteur: requests.Session, api: str, registry: ResourceRegistry, name: str) -> JsonObject:
    """A new skill of the redacteur, deleted at cleanup."""
    skill = expect_status(redacteur.post(f"{api}/Skills", json={"naam": registry.tagged(name)}), HTTPStatus.CREATED)
    created = skill.json()
    registry.add(f"KISS skill {created['id']}", lambda: redacteur.delete(f"{api}/Skills/{created['id']}"))
    return created


# The count of important berichten is shared: the tests that make one important run one after another.
BERICHTEN = pytest.mark.xdist_group("kiss-berichten")


@BERICHTEN
@pytest.mark.source(
    f"{E2E}/NieuwsEnWerkInstructies/NieuwsEnWerkInstructiesScenarios.cs",
    "Nieuws and werkinstructies: the important message count on the home page and marking a message read.",
)
@pytest.mark.scenario("""
    Given the KISS redacteur and the KCC medewerker are logged in to KISS
    When the redacteur publishes an important nieuwsbericht for a skill
    Then KISS refuses the same bericht from the KCC medewerker
    And the KCC medewerker sees it unread and counted among the important berichten
    When the medewerker marks it read
    Then it is read and the count drops by one
    When the medewerker marks it unread again
    Then it is unread and counted again
""")
def test_published_bericht_reaches_the_kcc_and_is_marked_read(
    kiss_session: Callable[[KeycloakUser], requests.Session], urls: dict[str, str], registry: ResourceRegistry
) -> None:
    """The redacteur publishes an important bericht with a skill; the KCC sees it unread, counted, then reads it.

    Only a redacteur may publish: the KCC is refused.
    """
    api = f"{urls['kiss']}/api"
    redacteur, kcc = kiss_session(ADMIN), kiss_session(KCC)
    skill = _skill(redacteur, api, registry, "skill")
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
    expect_status(kcc.put(f"{api}/berichten/{created['id']}/read", json={"isGelezen": False}), HTTPStatus.OK, 204)
    assert seen()["isGelezen"] is False
    assert featured() == unread


NOW = datetime.now(UTC)


@pytest.fixture(name="bericht")
def fixture_bericht(
    kiss_session: Callable[[KeycloakUser], requests.Session], urls: dict[str, str], registry: ResourceRegistry
) -> Callable[..., JsonObject]:
    """Return a factory: a bericht the redacteur publishes, published an hour ago unless fields say otherwise."""
    api = f"{urls['kiss']}/api"
    redacteur = kiss_session(ADMIN)

    def create(titel: str, **fields: object) -> JsonObject:
        body = {
            "titel": titel,
            "inhoud": "<p>podiumd-tests</p>",
            "isBelangrijk": False,
            "skills": [],
            "publicatieDatum": (NOW - timedelta(hours=1)).isoformat(),
            "type": "Nieuws",
            **fields,
        }
        created = expect_status(redacteur.post(f"{api}/Berichten", json=body), HTTPStatus.CREATED).json()
        registry.add(f"KISS bericht {created['id']}", lambda: redacteur.delete(f"{api}/Berichten/{created['id']}"))
        return created

    return create


def _published(kcc: requests.Session, api: str, **params: str | list[int]) -> list[JsonObject]:
    """The berichten KISS shows the KCC medewerker for the filters (search, type, skillIds)."""
    return entries(expect_status(kcc.get(f"{api}/berichten/published", params=params), HTTPStatus.OK).json())


@BERICHTEN
@pytest.mark.parametrize("soort", ["Nieuws", "Werkinstructie"])
@pytest.mark.source(
    f"{E2E}/NieuwsEnWerkInstructies/NieuwsEnWerkInstructiesScenarios.cs",
    "The beheer list and detail of a nieuwsbericht or werkinstructie, changing titel, publicatiedatum and belangrijk, deleting it.",
)
@pytest.mark.scenario("""
    Given the KISS redacteur publishes a nieuwsbericht or werkinstructie with a skill
    Then the beheer list and its detail show it with its type and skill
    When the redacteur changes its titel and publicatiedatum and makes it belangrijk
    Then the detail shows the changes
    When the redacteur deletes it
    Then the beheer list no longer has it
""")
def test_bericht_is_changed_and_deleted_in_beheer(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    registry: ResourceRegistry,
    bericht: Callable[..., JsonObject],
    soort: str,
) -> None:
    """/api/Berichten: list, detail, PUT titel, publicatieDatum and isBelangrijk, DELETE."""
    api = f"{urls['kiss']}/api"
    redacteur = kiss_session(ADMIN)
    skill = _skill(redacteur, api, registry, f"skill-{soort}")
    created = bericht(registry.tagged(f"beheer-{soort}"), type=soort, skills=[skill["id"]])
    one = f"{api}/Berichten/{created['id']}"
    listed = {b["id"]: b for b in entries(expect_status(redacteur.get(f"{api}/Berichten"), HTTPStatus.OK).json())}
    assert listed[created["id"]]["type"] == soort
    detail = expect_status(redacteur.get(one), HTTPStatus.OK).json()
    assert detail["skills"] == [skill["id"]]
    datum = (NOW - timedelta(days=1)).replace(microsecond=0)
    changes = {"titel": f"{created['titel']}-gewijzigd", "publicatieDatum": datum.isoformat(), "isBelangrijk": True}
    expect_status(redacteur.put(one, json={**detail, **changes}), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    changed = expect_status(redacteur.get(one), HTTPStatus.OK).json()
    assert (changed["titel"], changed["isBelangrijk"]) == (changes["titel"], True)
    assert datetime.fromisoformat(str(changed["publicatieDatum"])) == datum
    expect_status(redacteur.delete(one), HTTPStatus.OK, HTTPStatus.NO_CONTENT)
    remaining = entries(expect_status(redacteur.get(f"{api}/Berichten"), HTTPStatus.OK).json())
    assert created["id"] not in [b["id"] for b in remaining]


WINDOWS = {
    "future-publicatiedatum-hidden": ({"publicatieDatum": (NOW + timedelta(days=1)).isoformat()}, False),
    "past-einddatum-hidden": ({"publicatieEinddatum": (NOW - timedelta(minutes=5)).isoformat()}, False),
    "future-einddatum-shown": ({"publicatieEinddatum": (NOW + timedelta(days=1)).isoformat()}, True),
}


@pytest.mark.parametrize("window", list(WINDOWS))
@pytest.mark.source(
    f"{E2E}/NieuwsEnWerkInstructies/NieuwsEnWerkInstructiesScenarios.cs",
    "A bericht shows only between its publicatiedatum and publicatie-einddatum.",
)
@pytest.mark.scenario("""
    Given the KISS redacteur has a bericht with a publicatiedatum in the future, an einddatum past, or one to come
    When the KCC medewerker searches it
    Then KISS shows it only while it is published
""")
def test_bericht_shows_within_its_publication_window(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    registry: ResourceRegistry,
    bericht: Callable[..., JsonObject],
    window: str,
) -> None:
    """/berichten/published leaves out a bericht before its publicatieDatum and after its publicatieEinddatum."""
    fields, shown = WINDOWS[window]
    titel = registry.tagged(f"venster-{window}")
    bericht(titel, **fields)
    found = _published(kiss_session(KCC), f"{urls['kiss']}/api", search=titel)
    assert bool(found) is shown


@pytest.mark.source(
    f"{E2E}/NieuwsEnWerkInstructies/NieuwsEnWerkInstructiesScenarios.cs",
    "Filters on one, several or no skills, and on type with a search; the skills show as labels.",
)
@pytest.mark.scenario("""
    Given a nieuwsbericht of one skill, a werkinstructie of another, and a nieuwsbericht without skill
    When the KCC medewerker filters on one skill, on both, on none, or on type werkinstructie
    Then KISS shows the berichten of that skill, of either skill, all three, or only the werkinstructie
    And each bericht shows its skill
""")
def test_berichten_are_filtered_on_skill_and_type(
    kiss_session: Callable[[KeycloakUser], requests.Session],
    urls: dict[str, str],
    registry: ResourceRegistry,
    bericht: Callable[..., JsonObject],
) -> None:
    """/berichten/published with skillIds (one, several, none) and type, each within the run's search term."""
    api = f"{urls['kiss']}/api"
    redacteur = kiss_session(ADMIN)
    skills = [_skill(redacteur, api, registry, f"filter-{name}") for name in ("a", "b")]
    term = registry.tagged("filter")
    nieuws = bericht(f"{term}-nieuws", skills=[skills[0]["id"]])
    instructie = bericht(f"{term}-instructie", type="Werkinstructie", skills=[skills[1]["id"]])
    zonder = bericht(f"{term}-zonder")
    kcc = kiss_session(KCC)

    def ids(**params: str | list[int]) -> set[object]:
        return {b["id"] for b in _published(kcc, api, search=term, **params)}

    a, b = int(str(skills[0]["id"])), int(str(skills[1]["id"]))
    assert ids(skillIds=[a]) == {nieuws["id"]}
    assert ids(skillIds=[a, b]) == {nieuws["id"], instructie["id"]}
    assert ids() == {nieuws["id"], instructie["id"], zonder["id"]}
    assert ids(type="Werkinstructie") == {instructie["id"]}
    labels = {x["id"]: [s.get("naam") for s in entries(x.get("skills"))] for x in _published(kcc, api, search=term)}
    assert labels[nieuws["id"]] == [skills[0]["naam"]]
