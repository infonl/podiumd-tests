"""Volume data for the perf tier (PLAN.md §4 C): many objects per component, kept between runs.

Ported from TA seed-test-data. Everything carries VOLUME_TAG, which is no run tag: sweep leaves
it, unseed-volume deletes it. Seeding tops up to the target count, so a rerun only adds what is
missing. Objects are created through the component APIs, as TA did; counting and deleting go
through Django snippets, which is what makes tens of thousands of objects workable.
"""

from __future__ import annotations

import threading

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING
from typing import cast

import yaml

from podiumd_tests.bootstrap.names import TEST_CATALOGUS_DOMEIN
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.clients.platform import openklant_client
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.registry import ResourceRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment

VOLUME_TAG = "ptest-volume"
VOLUME_ACTOR = f"{VOLUME_TAG}-actor"
# Deleting tens of thousands of objects through the ORM takes minutes.
DELETE_TIMEOUT = 1800
# TA's counts per scale; a profile setting seed_volume_<kind> replaces the perf count.
SCALES = {
    "smoke": {"zaken": 3, "partijen": 5, "internetaken": 5},
    "perf": {"zaken": 50_000, "partijen": 2_000, "internetaken": 100},
}
VOLUME_ZAAKTYPE = {
    "domein": TEST_CATALOGUS_DOMEIN,
    "rsin": TEST_CATALOGUS_RSIN,
    "identificatie": VOLUME_TAG,
    "iot_omschrijving": f"{VOLUME_TAG}-bijlage",
    "besluittype": f"{VOLUME_TAG}-besluit",
}


@dataclass(frozen=True)
class Corpus:
    """Fictional names and zaak scenarios (volume_corpus.yaml); picked by index, so reruns repeat them."""

    personen: list[dict[str, str]]
    organisaties: list[dict[str, str]]
    scenarios: list[str]

    def persoon(self, index: int) -> dict[str, str]:
        """The index-th persoon, wrapping around."""
        return self.personen[index % len(self.personen)]

    def organisatie(self, index: int) -> str:
        """The index-th organisatie's name, wrapping around."""
        return self.organisaties[index % len(self.organisaties)]["naam"]

    def scenario(self, index: int) -> str:
        """The index-th zaak scenario, wrapping around."""
        return self.scenarios[index % len(self.scenarios)]


@cache
def corpus() -> Corpus:
    """The corpus, read once."""
    text = files("podiumd_tests.seed").joinpath("volume_corpus.yaml").read_text(encoding="utf-8")
    data = cast("dict[str, list[object]]", yaml.safe_load(text))
    personen = cast("list[dict[str, str]]", data["personen"])
    organisaties = cast("list[dict[str, str]]", data["organisaties"])
    return Corpus(personen, organisaties, [str(s) for s in data["zaak_scenarios"]])


def target(env: Environment, scale: str, kind: str) -> int:
    """How many objects of the kind the scale asks for on this environment."""
    count = SCALES[scale][kind]
    if scale == "perf":
        count = int(env.profile.settings.get(f"seed_volume_{kind}", count))
    return count


@dataclass(frozen=True)
class Kind:
    """One kind of volume object: the component it needs and how to count, create and delete it."""

    name: str
    component: str
    count: Callable[[Environment], int]
    creator: Callable[[Environment], Callable[[int], None]]
    delete_all: Callable[[Environment], object]


def _per_thread(make: Callable[[], ApiClient]) -> Callable[[], ApiClient]:
    """A client per worker thread: requests sessions are not thread-safe."""
    local = threading.local()

    def client() -> ApiClient:
        if not hasattr(local, "client"):
            local.client = make()
        return cast("ApiClient", local.client)

    return client


def _zaaktype_snippet(env: Environment, action: str) -> dict[str, object]:
    params: dict[str, object] = {"action": action, **VOLUME_ZAAKTYPE}
    deployment = env.deployment_for("openzaak")
    return cast("dict[str, object]", run_snippet(env.kube, deployment, "openzaak_zaaktype", params, DELETE_TIMEOUT))


def _openzaak(env: Environment) -> ApiClient:
    return openzaak_client(env, ZGW_CLIENT_ID, ZGW_STORE_KEY, VOLUME_TAG)


def _volume_zaaktype(openzaak: ApiClient) -> str | None:
    found = openzaak.list(f"{CATALOGI}/zaaktypen", {"identificatie": VOLUME_TAG})
    return str(found[0]["url"]) if found else None


def _count_zaken(env: Environment) -> int:
    openzaak = _openzaak(env)
    zaaktype = _volume_zaaktype(openzaak)
    if zaaktype is None:
        return 0
    return int(str(openzaak.get(f"{ZAKEN}/zaken", {"zaaktype": zaaktype, "pageSize": "1"}).get("count", 0)))


def _zaak_creator(env: Environment) -> Callable[[int], None]:
    """Zaken of the volume zaaktype (created first), with a scenario as omschrijving and a long toelichting."""
    if not _zaaktype_snippet(env, "status").get("present"):
        _zaaktype_snippet(env, "apply")
    openzaak = _per_thread(lambda: _openzaak(env))
    registry = ResourceRegistry(VOLUME_TAG, keep=True)
    zaaktype = str(_volume_zaaktype(openzaak()))

    def create(index: int) -> None:
        scenario = corpus().scenario(index)
        # TA's toelichting is about 900 characters.
        toelichting = f"{VOLUME_TAG} {index}: {scenario}. " + "Toelichting van de aanvrager. " * 28
        make_zaak(openzaak(), registry, zaaktype, omschrijving=scenario[:80], toelichting=toelichting)

    return create


def _openklant_volume(env: Environment, action: str, kind: str) -> int:
    params: dict[str, object] = {"action": action, "kind": kind, "tag": VOLUME_TAG}
    found = run_snippet(env.kube, env.deployment_for("openklant"), "openklant_volume", params, DELETE_TIMEOUT)
    return int(str(cast("dict[str, object]", found)["count"]))


def _partij_creator(env: Environment) -> Callable[[int], None]:
    """Partijen in TA's mix of 7 personen to 3 organisaties, tagged in interneNotitie."""
    openklant = _per_thread(lambda: openklant_client(env))
    registry = ResourceRegistry(VOLUME_TAG, keep=True)

    def create(index: int) -> None:
        if index % 10 < 7:
            persoon = corpus().persoon(index)
            naam = {"contactnaam": {"voornaam": persoon["voornaam"], "achternaam": persoon["achternaam"]}}
            make_partij(openklant(), registry, partijIdentificatie=naam, interneNotitie=VOLUME_TAG)
        else:
            naam = {"naam": corpus().organisatie(index)}
            make_partij(
                openklant(), registry, soortPartij="organisatie", partijIdentificatie=naam, interneNotitie=VOLUME_TAG
            )

    return create


def _internetaak_creator(env: Environment) -> Callable[[int], None]:
    """Internetaken (TA's ita module), each raised by its klantcontact and assigned to one volume actor."""
    openklant = _per_thread(lambda: openklant_client(env))
    registry = ResourceRegistry(VOLUME_TAG, keep=True)
    actoren = openklant().list("actoren", {"naam": VOLUME_ACTOR})
    actor = actoren[0] if actoren else make_actor(openklant(), registry, name=VOLUME_ACTOR)

    def create(index: int) -> None:
        onderwerp = f"{VOLUME_TAG} {corpus().scenario(index)}"[:200]
        make_internetaak(openklant(), registry, make_klantcontact(openklant(), registry, onderwerp=onderwerp), [actor])

    return create


KINDS: tuple[Kind, ...] = (
    Kind("zaken", "openzaak", _count_zaken, _zaak_creator, lambda env: _zaaktype_snippet(env, "remove")),
    Kind(
        "partijen",
        "openklant",
        lambda env: _openklant_volume(env, "count", "partijen"),
        _partij_creator,
        lambda env: _openklant_volume(env, "delete", "partijen"),
    ),
    Kind(
        "internetaken",
        "openklant",
        lambda env: _openklant_volume(env, "count", "internetaken"),
        _internetaak_creator,
        lambda env: _openklant_volume(env, "delete", "internetaken"),
    ),
)


@dataclass(frozen=True)
class Seeded:
    """What seeding or unseeding did for one kind."""

    kind: str
    before: int
    after: int
    detail: str = ""


def seed(env: Environment, scale: str, *, parallel: int) -> list[Seeded]:
    """Top every kind the environment has up to its target count."""
    seeded: list[Seeded] = []
    for kind in KINDS:
        reason = env.capabilities.skip_reason(kind.component)
        if reason:
            seeded.append(Seeded(kind.name, 0, 0, f"skipped: {reason}"))
            continue
        before = kind.count(env)
        missing = range(before, target(env, scale, kind.name))
        if missing:
            create = kind.creator(env)
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                list(pool.map(create, missing))
        seeded.append(Seeded(kind.name, before, kind.count(env)))
    return seeded


def unseed(env: Environment) -> list[Seeded]:
    """Delete the volume objects of every kind the environment has."""
    unseeded: list[Seeded] = []
    for kind in reversed(KINDS):
        reason = env.capabilities.skip_reason(kind.component)
        if reason:
            unseeded.append(Seeded(kind.name, 0, 0, f"skipped: {reason}"))
            continue
        before = kind.count(env)
        kind.delete_all(env)
        unseeded.append(Seeded(kind.name, before, kind.count(env)))
    return unseeded


def format_seeded(seeded: list[Seeded]) -> str:
    """One line per kind: its count before and after, or why it was skipped."""
    return "\n".join(
        f"{s.kind:<14} {s.detail}" if s.detail else f"{s.kind:<14} {s.before} -> {s.after}" for s in seeded
    )
