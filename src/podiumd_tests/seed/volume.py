"""Volume data for the perf tier (PLAN.md §4 C): many objects per component, kept between runs.

Ported from TA seed-test-data. Everything carries VOLUME_TAG, which is no run tag: sweep leaves
it, unseed-volume deletes it. Seeding tops up to the target count, so a rerun only adds what is
missing. Objects are created through the component APIs, as TA did; counting and deleting go
through Django snippets, which is what makes tens of thousands of objects workable.
"""

from __future__ import annotations

import threading

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING
from typing import cast

import requests
import yaml

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_DOMEIN
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.clients.platform import openklant_client
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.credentials import SecretError
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.kcc import KENNIS_URL
from podiumd_tests.kcc import kennisartikel_data
from podiumd_tests.kcc import kiss_sync_cronjob
from podiumd_tests.kcc import vac_data
from podiumd_tests.pabc import add_zaaktype_entity_type
from podiumd_tests.pabc import admin_session
from podiumd_tests.pabc import delete_entity_type
from podiumd_tests.pabc import zaaktype_entity_type
from podiumd_tests.process import ProcessError
from podiumd_tests.seed.openklant import make_actor
from podiumd_tests.seed.openklant import make_internetaak
from podiumd_tests.seed.openklant import make_klantcontact
from podiumd_tests.seed.openklant import make_partij
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.workloads import run_cronjob
from podiumd_tests.workloads import scaled
from podiumd_tests.zac import count_zaken_found
from podiumd_tests.zac import reindex_zaken
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment

VOLUME_TAG = "ptest-volume"
VOLUME_ACTOR = f"{VOLUME_TAG}-actor"
VOLUME_GROUP = "medewerkers"
OBJECTEN_BATCH = 200
# Deleting tens of thousands of objects through the ORM takes minutes.
DELETE_TIMEOUT = 1800
# TA's counts per scale; a profile setting seed_volume_<kind> replaces the perf count.
SCALES = {
    "smoke": {"users": 5, "zaken": 3, "partijen": 5, "objecten": 10, "internetaken": 5, "vac": 5, "kennisartikelen": 5},
    "perf": {
        "users": 100,
        "zaken": 50_000,
        "partijen": 2_000,
        "objecten": 1_000,
        "internetaken": 100,
        "vac": 500,
        "kennisartikelen": 500,
    },
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
    create: Callable[[Environment, range, int], None]  # the indexes to create, and the concurrency
    delete_all: Callable[[Environment], object]
    # The kind whose target count this kind follows, e.g. the zaken ZAC indexes.
    target_kind: str = ""
    # Why the environment does not allow this kind, or None.
    refused: Callable[[Environment], str | None] = lambda _env: None


@dataclass(frozen=True)
class KissSource:
    """KISS search content in Objecten: its objecttype, the data key and prefix that mark volume data, its sync job."""

    objecttype: str
    key: str
    prefix: str
    data: Callable[[str, str], dict[str, object]]
    sync: str


def _one_by_one(creator: Callable[[Environment], Callable[[int], None]]) -> Callable[[Environment, range, int], None]:
    """Create through an API, one object per call, `parallel` calls at a time."""

    def create(env: Environment, missing: range, parallel: int) -> None:
        one = creator(env)
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            list(pool.map(one, missing))

    return create


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


def _count_users(env: Environment) -> int:
    return for_environment(env).count_users(VOLUME_TAG)


def _user_creator(env: Environment) -> Callable[[int], None]:
    """Keycloak users with scifi names in TA's group medewerkers (when the realm has it); nobody logs in as them."""
    group = for_environment(env).group_id(VOLUME_GROUP)

    def create(index: int) -> None:
        persoon = corpus().persoon(index)
        username = f"{VOLUME_TAG}-{persoon['voornaam']}.{persoon['achternaam']}.{index}".lower().replace(" ", "")
        # A fresh admin token per user: the master realm's tokens expire within minutes.
        admin = for_environment(env)
        user = admin.create_user(username, admin.new_password(), {}, (persoon["voornaam"], persoon["achternaam"]))
        if group:
            admin.join_group(user, group)

    return create


def _delete_users(env: Environment) -> None:
    admin = for_environment(env)
    for user in admin.users(VOLUME_TAG):
        admin.delete_user(str(user["id"]))


def _objecttype(env: Environment, action: str) -> str | None:
    params: dict[str, object] = {"action": action, "name": VOLUME_TAG}
    found = run_snippet(env.kube, env.deployment_for("objecttypen"), "objecttypen_volume", params)
    uuid = cast("dict[str, object]", found)["uuid"]
    return str(uuid) if uuid else None


def _objecten_volume(env: Environment, action: str, **params: object) -> int:
    params = {"action": action, "name": VOLUME_TAG, "tag": VOLUME_TAG, **params}
    found = run_snippet(env.kube, env.deployment_for("objecten"), "objecten_volume", params, DELETE_TIMEOUT)
    return int(str(cast("dict[str, object]", found)["count"]))


def _count_objecten(env: Environment) -> int:
    return _objecten_volume(env, "count", uuid=_objecttype(env, "status"))


def _create_objecten(env: Environment, missing: range, _parallel: int) -> None:
    """Objects of the volume objecttype, OBJECTEN_BATCH per snippet call.

    Through Django: the Objecten API would need the suite's token to have rights on this objecttype.
    """
    uuid = _objecttype(env, "apply")
    body = "Tekst van podiumd-tests. " * 20
    for start in range(missing.start, missing.stop, OBJECTEN_BATCH):
        stop = min(start + OBJECTEN_BATCH, missing.stop)
        _objecten_volume(env, "create", uuid=uuid, start=start, stop=stop, body=body)


def _delete_objecten(env: Environment) -> None:
    _objecten_volume(env, "delete", uuid=_objecttype(env, "status"))
    _objecttype(env, "remove")


def _kiss_content(
    env: Environment, source: KissSource, action: str, items: list[dict[str, object]] | None = None
) -> int:
    params: dict[str, object] = {
        "action": action,
        "name": source.objecttype,
        "key": source.key,
        "prefix": source.prefix,
        "items": items or [],
    }
    found = run_snippet(env.kube, env.deployment_for("objecten"), "objecten_tagged", params, DELETE_TIMEOUT)
    return int(str(cast("dict[str, object]", found)["count"]))


def _sync_kiss(env: Environment, source: KissSource) -> None:
    run_cronjob(env.kube, kiss_sync_cronjob(env, source.sync), f"{VOLUME_TAG}-{source.sync}-sync")


def _kiss_kind(name: str, source: KissSource) -> Kind:
    """Objects KISS's search finds once its sync job ran: their title is VOLUME_TAG, an index and a scenario."""

    def create(env: Environment, missing: range, _parallel: int) -> None:
        tekst = "Toelichting van podiumd-tests. " * 20
        for start in range(missing.start, missing.stop, OBJECTEN_BATCH):
            indexes = range(start, min(start + OBJECTEN_BATCH, missing.stop))
            items = [source.data(f"{VOLUME_TAG} {i} {corpus().scenario(i)}", tekst) for i in indexes]
            _kiss_content(env, source, "create", items)
        _sync_kiss(env, source)

    def delete_all(env: Environment) -> None:
        _kiss_content(env, source, "delete")
        _sync_kiss(env, source)

    return Kind(name, "kiss", lambda env: _kiss_content(env, source, "count"), create, delete_all)


def _volume_zac_allowed(env: Environment) -> str | None:
    if env.profile.settings.get("pabc_volume_zaaktype", "").lower() != "true":  # settings are strings
        return "not allowed: profile setting pabc_volume_zaaktype is off"
    return None


def _pabc(env: Environment) -> tuple[requests.Session, str]:
    return admin_session(env, ADMIN.username, env.credentials.get(ADMIN.store_key)), env.profile.urls["pabc"]


def _count_zaken_in_zac(env: Environment) -> int:
    zac = zac_session(env, ADMIN.username, env.credentials.get(ADMIN.store_key))
    return count_zaken_found(zac, env.profile.urls["zac"], VOLUME_TAG)


def _index_zaken_in_zac(env: Environment, _missing: range, _parallel: int) -> None:
    """Make the volume zaaktype known to PABC, so the admin may see its zaken, and reindex ZAC's zaken."""
    pabc, pabc_url = _pabc(env)
    if zaaktype_entity_type(pabc, pabc_url, VOLUME_TAG) is None:
        add_zaaktype_entity_type(pabc, pabc_url, VOLUME_TAG)
    reindex_zaken(env)


def _forget_zaken_in_zac(env: Environment) -> None:
    pabc, pabc_url = _pabc(env)
    entity_type = zaaktype_entity_type(pabc, pabc_url, VOLUME_TAG)
    if entity_type is not None:
        delete_entity_type(pabc, pabc_url, entity_type)


def _delete_zaken(env: Environment) -> None:
    _zaaktype_snippet(env, "remove")
    # The snippet deletes without notifications: ZAC's index keeps the zaken until a reindex.
    if "zac" in env.profile.urls and _volume_zac_allowed(env) is None:
        reindex_zaken(env)


KINDS: tuple[Kind, ...] = (
    Kind("users", "keycloak", _count_users, _one_by_one(_user_creator), _delete_users),
    Kind("zaken", "openzaak", _count_zaken, _one_by_one(_zaak_creator), _delete_zaken),
    Kind(
        "zaken_in_zac",
        "zac",
        _count_zaken_in_zac,
        _index_zaken_in_zac,
        _forget_zaken_in_zac,
        target_kind="zaken",
        refused=_volume_zac_allowed,
    ),
    Kind(
        "partijen",
        "openklant",
        lambda env: _openklant_volume(env, "count", "partijen"),
        _one_by_one(_partij_creator),
        lambda env: _openklant_volume(env, "delete", "partijen"),
    ),
    Kind(
        "internetaken",
        "openklant",
        lambda env: _openklant_volume(env, "count", "internetaken"),
        _one_by_one(_internetaak_creator),
        lambda env: _openklant_volume(env, "delete", "internetaken"),
    ),
    Kind("objecten", "objecten", _count_objecten, _create_objecten, _delete_objecten),
    _kiss_kind("vac", KissSource("VAC", "vraag", VOLUME_TAG, vac_data, "vac")),
    _kiss_kind(
        "kennisartikelen", KissSource("Kennisartikel", "url", KENNIS_URL + VOLUME_TAG, kennisartikel_data, "kennisbank")
    ),
)


@dataclass(frozen=True)
class Seeded:
    """What seeding or unseeding did for one kind."""

    kind: str
    before: int
    after: int
    detail: str = ""


@contextmanager
def faster(env: Environment, replicas: int) -> Generator[None]:
    """TA's --scale-cluster: Open Zaak, Open Klant and their workers at `replicas` in the block (0: unchanged).

    TA's --no-notify is not ported: Open Zaak refuses every write while it has no Notificaties service.
    """
    with ExitStack() as stack:
        for component in ("openzaak", "openklant"):
            if replicas and not env.capabilities.skip_reason(component):
                main = env.deployment_for(component)
                for deployment in (main, f"{main}-worker"):
                    if deployment in env.deployment_names:
                        stack.enter_context(scaled(env.kube, deployment, replicas))
        yield


def _skipped(env: Environment, kind: Kind) -> str | None:
    """Why the kind is skipped on the environment: its component is missing or the profile refuses it."""
    return env.capabilities.skip_reason(kind.component) or kind.refused(env)


def seed(env: Environment, scale: str, *, parallel: int) -> list[Seeded]:
    """Top every kind the environment has up to its target count."""
    seeded: list[Seeded] = []
    for kind in KINDS:
        reason = _skipped(env, kind)
        if reason:
            seeded.append(Seeded(kind.name, 0, 0, f"skipped: {reason}"))
            continue
        before = kind.count(env)
        missing = range(before, target(env, scale, kind.target_kind or kind.name))
        if missing:
            kind.create(env, missing, parallel)
        seeded.append(Seeded(kind.name, before, kind.count(env)))
    return seeded


def unseed(env: Environment) -> list[Seeded]:
    """Delete the volume objects of every kind the environment has."""
    unseeded: list[Seeded] = []
    for kind in reversed(KINDS):
        reason = _skipped(env, kind)
        if reason:
            unseeded.append(Seeded(kind.name, 0, 0, f"skipped: {reason}"))
            continue
        before = kind.count(env)
        kind.delete_all(env)
        unseeded.append(Seeded(kind.name, before, kind.count(env)))
    return unseeded


def counts(env: Environment) -> dict[str, int | None]:
    """The volume objects per kind the environment has now; None where they cannot be counted."""
    found: dict[str, int | None] = {}
    for kind in KINDS:
        try:
            found[kind.name] = None if _skipped(env, kind) else kind.count(env)
        except (ProcessError, SecretError, AssertionError, LookupError, requests.RequestException):
            # No kubectl, no Keycloak admin secret, an API refusing: this run's volume is unknown.
            found[kind.name] = None
    return found


def format_seeded(seeded: list[Seeded]) -> str:
    """One line per kind: its count before and after, or why it was skipped."""
    width = max([14, *(len(s.kind) + 1 for s in seeded)])
    return "\n".join(
        f"{s.kind:<{width}} {s.detail}" if s.detail else f"{s.kind:<{width}} {s.before} -> {s.after}" for s in seeded
    )
