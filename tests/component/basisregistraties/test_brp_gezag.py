"""BRP gezag through the api-proxy: the gezagsrelaties of minderjarigen and of their gezaghebbenden.

The BSNs are from the BRP test set that the personen mock serves; the minderjarigen are born from 2018 on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.basisregistraties import EREBOS
from podiumd_tests.basisregistraties import brp_persoon
from podiumd_tests.json_data import entries

if TYPE_CHECKING:
    import requests

    from podiumd_tests.json_data import JsonObject

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("api-proxy"),
    pytest.mark.source(
        "external BRP-API/Haal-Centraal-BRP-bevragen features/gezag, features/bevragen/persoon/gezag",
        "The BRP API gives the gezag over a minderjarige to the minderjarige and to each gezaghebbende.",
    ),
]

# Helga Huisman and Hans Hamersma have gezamenlijk ouderlijk gezag over Harold, Harm and Harry Hamersma.
HELGA = "999970458"
HANS = "999970446"
HAROLD = "999970471"


def gezag(http: requests.Session, urls: dict[str, str], bsn: str) -> list[JsonObject]:
    """Return the gezag of a person of the BRP test set."""
    return entries(brp_persoon(http, urls["api-proxy"], bsn, ["gezag"])["gezag"])


def wie(value: object) -> object:
    """Return the BSN of a person in a gezagsrelatie, or its type when it has none; other values as they are."""
    if isinstance(value, dict):
        return value.get("burgerservicenummer", value.get("type"))
    if isinstance(value, list):
        return [wie(each) for each in value]
    return value


def relatie(gezag_relatie: JsonObject) -> dict[str, object]:
    """Return a gezagsrelatie with each person replaced by its BSN, or by its type when it has none."""
    return {key: wie(value) for key, value in gezag_relatie.items()}


@pytest.mark.parametrize(
    ("minderjarige", "expected"),
    [
        (HAROLD, {"type": "GezamenlijkOuderlijkGezag", "ouders": [HELGA, HANS]}),
        # Sytse van Steenbergen; his father Sjoerd.
        ("999970793", {"type": "EenhoofdigOuderlijkGezag", "ouder": "999970768"}),
        # Gijs Geus, whose indicatie gezag minderjarige is in onderzoek; his mother Grada Goverwelle.
        ("999970331", {"type": "EenhoofdigOuderlijkGezag", "ouder": "999970148", "inOnderzoek": True}),
        # Peet van Paassen; his mother Petronella with Pia Pauw.
        ("999970161", {"type": "GezamenlijkGezag", "ouder": "999970124", "derde": "999970136"}),
        # Laeticia Luiten; her mother Laurentien van Leeuwen with a derde not in the BRP.
        ("999970719", {"type": "GezamenlijkGezag", "ouder": "999970677", "derde": "OnbekendeDerde"}),
        # Tom van Tintelen; voogd Tina van Tubbergen.
        ("999971037", {"type": "Voogdij", "derden": ["999970987"]}),
        # An Xue.
        (
            "999998389",
            {
                "type": "GezagNietTeBepalen",
                "toelichting": "Gezag kan niet worden bepaald omdat minderjarige in het buitenland is geboren.",
            },
        ),
        # Zacharias Vondeling.
        (
            "999999631",
            {"type": "TijdelijkGeenGezag", "toelichting": "Tijdelijk geen gezag omdat beide ouders onbekend zijn."},
        ),
    ],
    ids=[
        "gezamenlijk-ouderlijk",
        "eenhoofdig-ouderlijk",
        "in-onderzoek",
        "gezamenlijk-met-derde",
        "gezamenlijk-met-onbekende-derde",
        "voogdij",
        "niet-te-bepalen",
        "tijdelijk-geen",
    ],
)
@pytest.mark.scenario("""
    Given a minderjarige in the BRP test set
    When the gezag over the minderjarige is asked through the api-proxy
    Then the BRP gives one gezagsrelatie of the right type for the minderjarige
    And it names the ouders, the derde or the voogd, or explains why no one has gezag
""")
def test_gezag_of_a_minderjarige(
    http: requests.Session, urls: dict[str, str], minderjarige: str, expected: dict[str, object]
) -> None:
    """A minderjarige gets one gezagsrelatie with its type, gezaghebbenden or toelichting."""
    found = [relatie(each) for each in gezag(http, urls, minderjarige)]
    assert found == [{**expected, "minderjarige": minderjarige}]


@pytest.mark.scenario("""
    Given a mother in the BRP test set with gezamenlijk ouderlijk gezag over three young children
    When her gezag is asked through the api-proxy
    Then the BRP gives a gezagsrelatie for each child, naming her and the father
""")
def test_gezag_of_a_parent_over_each_minderjarige(http: requests.Session, urls: dict[str, str]) -> None:
    """A gezaghebbende gets a gezagsrelatie for each minderjarige under the gezag."""
    found = {str(each["minderjarige"]): each for each in map(relatie, gezag(http, urls, HELGA))}
    ouders = {"type": "GezamenlijkOuderlijkGezag", "ouders": [HELGA, HANS]}
    assert found == {kind: {**ouders, "minderjarige": kind} for kind in (HAROLD, "999970483", "999970495")}


@pytest.mark.parametrize(
    ("ouder", "kind"),
    [
        # Lieke Liebeek; the gezag over her son Lux cannot be determined.
        ("999999047", "999999072"),
        # Ria Ruijgrok, under curatele; no one has gezag over her son Rex.
        ("999970197", "999970227"),
    ],
    ids=["niet-te-bepalen", "tijdelijk-geen"],
)
@pytest.mark.scenario("""
    Given a parent in the BRP test set with a minderjarige over whom gezag cannot be determined or no one has gezag
    When the parent's gezag is asked through the api-proxy
    Then the BRP gives the parent no gezagsrelatie for that minderjarige
""")
def test_no_gezag_of_a_parent_without_gezag(
    http: requests.Session, urls: dict[str, str], ouder: str, kind: str
) -> None:
    """A parent gets no gezagsrelatie for a child without a determined gezaghebbende."""
    assert kind not in [relatie(each)["minderjarige"] for each in gezag(http, urls, ouder)]


@pytest.mark.scenario("""
    Given an adult in the BRP test set with ouders and no children
    When the adult's gezag is asked through the api-proxy
    Then the BRP gives no gezagsrelatie
""")
def test_no_gezag_of_an_adult_without_minderjarigen(http: requests.Session, urls: dict[str, str]) -> None:
    """An adult without minderjarigen gets an empty gezag, also none towards the own ouders."""
    assert gezag(http, urls, EREBOS) == []
