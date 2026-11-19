"""Open VTB test data; every factory registers its deleter."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.kube import DJANGO_VALUE_MARKER
from podiumd_tests.kube import django_values
from podiumd_tests.seed.openzaak import after_period
from podiumd_tests.seed.openzaak import today

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


# Required details per taak endpoint; the IBAN passes the mod-97 check.
TAAK_DETAILS: dict[str, JsonObject] = {
    "urltaken": {"uitvraagLink": "http://example.invalid/"},
    "betaaltaken": {
        "bedrag": "12.50",
        "transactieomschrijving": "ptest leges",
        "doelrekening": {"naam": "ptest", "iban": "NL91ABNA0417164300"},
    },
    "formuliertaken": {
        "formulierDefinitie": {"components": [{"label": "Bewijsstuk", "key": "bewijsstuk", "type": "textfield"}]}
    },
}

# The fields of an externe taak the Open VTB Taken aansluitprofiel (raadpleegTaak) maps to the Interactie API.
PROFILE_FIELDS = (
    "uuid",
    "titel",
    "toelichting",
    "status",
    "einddatumHandelingsTermijn",
    "isGerelateerdAan",
    "handelingsPerspectief",
    "url",
    "taakSoort",
)
# The berichtenbox type of make_bericht's berichttypen: OMC drops a bericht whose type is empty, even when its
# whitelist is "*" (Open VTB allows 8 characters).
BERICHTENBOX_TYPE = "ptest"


def zaak_urn(zaak: JsonObject) -> str:
    """Return the URN of a zaak by its zaaknummer, unique per bronorganisatie; Open Zaak has no zaak URN."""
    return f"urn:nld:rsin:{zaak['bronorganisatie']}:zaak:zaaknummer:{zaak['identificatie']}"


def taak_body(registry: ResourceRegistry, endpoint: str, **fields: object) -> dict[str, object]:
    """Return a taak for an endpoint (urltaken, ...) with its required fields, titel run-tagged; None drops a field."""
    body: dict[str, object] = {
        "titel": registry.tagged(endpoint),
        "einddatumHandelingsTermijn": after_period(today(), "P14D"),
        "details": TAAK_DETAILS[endpoint],
        **fields,
    }
    return {field: value for field, value in body.items() if value is not None}


def without(body: dict[str, object], field: str) -> dict[str, object]:
    """Return a taak body without a field, at the top or in its details."""
    if field in body:
        return {key: value for key, value in body.items() if key != field}
    details = cast("JsonObject", body["details"])
    return {**body, "details": {key: value for key, value in details.items() if key != field}}


def make_taak(taken: ApiClient, registry: ResourceRegistry, endpoint: str, **fields: object) -> JsonObject:
    """Create a taak as taak_body describes it."""
    taak = taken.post(endpoint, taak_body(registry, endpoint, **fields))
    url = str(taak["url"])
    registry.add(f"openvtb taak {url}", lambda: taken.delete(url))
    return taak


def make_bericht(  # the berichttype's flag is not a field of the bericht
    env: Environment,
    berichten: ApiClient,
    registry: ResourceRegistry,
    ontvanger: str,
    *,
    berichtenbox: bool = False,
    **fields: object,
) -> JsonObject:
    """Create a bericht to ontvanger (a URN) of a new berichttype, onderwerp run-tagged; fields override defaults.

    berichtenbox: the berichttype is for MijnOverheid's Berichtenbox.
    """
    berichttype = berichten.post(
        "berichttypen",
        {
            "verantwoordelijkeOrganisatie": "urn:ptest:org",
            "mijnOverheidBerichtenbox": berichtenbox,
            "mijnOverheidBerichtenboxType": BERICHTENBOX_TYPE,
            "bijlageTypen": [],
        },
    )
    berichttype_url = str(berichttype["url"])
    registry.add(f"openvtb berichttype {berichttype_url}", lambda: berichten.delete(berichttype_url))
    body = {
        "onderwerp": registry.tagged("bericht"),
        "berichtTekst": "ptest",
        "ontvanger": ontvanger,
        "berichtType": berichttype_url,
        **fields,
    }
    bericht = berichten.post("berichten", body)
    bericht_uuid = str(bericht["uuid"])
    registry.add(f"openvtb bericht {bericht_uuid}", lambda: _delete_bericht(env, bericht_uuid))
    return bericht


# Open VTB's Celery worker, which sends its CloudEvents to Open Notificaties, and its beat, which publishes due
# berichten (podiumd chart from helm-charts #746).
OPENVTB_WORKER = "openvtb-worker"
OPENVTB_BEAT = "openvtb-beat"
# The type prefix of Open VTB's bericht CloudEvents and the beat task that publishes due berichten.
BERICHT_EVENTS = "nl.overheid.berichten."
PUBLISH_TASK = "openvtb.components.berichten.tasks.send_berichten_events"


def missing_celery(env: Environment) -> str | None:
    """Return the failure message when Open VTB runs without its worker or beat, else None."""
    missing = [name for name in (OPENVTB_WORKER, OPENVTB_BEAT) if name not in env.workload_names]
    if not missing:
        return None
    return f"no {' and '.join(missing)}: Open VTB sends no CloudEvents (podiumd chart without helm-charts #746)"


def notifications_api_root(env: Environment) -> str:
    """Return the API root of the Open Notificaties service Open VTB publishes its events to; empty when none."""
    code = (
        "from notifications_api_common.models import NotificationsConfig\n"
        "service = NotificationsConfig.get_solo().notifications_api_service\n"
        f"print({DJANGO_VALUE_MARKER!r} + (service.api_root if service else ''))"
    )
    return django_values(env.kube.exec_django_shell(env.deployment_for("openvtb"), code))[0]


def publish_schedules(env: Environment) -> list[str]:
    """Return the crontabs of Open VTB's enabled periodic tasks that publish due berichten."""
    code = (
        "from django_celery_beat.models import PeriodicTask\n"
        f"for task in PeriodicTask.objects.filter(task={PUBLISH_TASK!r}, enabled=True):\n"
        f"    print({DJANGO_VALUE_MARKER!r} + str(task.crontab))\n"
        f"print({DJANGO_VALUE_MARKER!r} + 'end')"
    )
    values = django_values(env.kube.exec_django_shell(env.deployment_for("openvtb"), code))
    return values[:-1]


def publish_bericht(env: Environment, bericht: str) -> None:
    """Publish a bericht (uuid) now: its CloudEvent bericht-gepubliceerd as Open VTB's beat task sends it.

    Only this bericht, unlike the task send_berichten_events, which publishes every due bericht of the environment.
    """
    code = (
        "from openvtb.components.berichten.models import Bericht\n"
        "from openvtb.components.berichten.tasks import mark_as_published, send_bericht\n"
        f"pk = Bericht.objects.get(uuid={bericht!r}).pk\n"
        "send_bericht.delay(pk)\n"
        "mark_as_published.delay([pk])"
    )
    env.kube.exec_django_shell(env.deployment_for("openvtb"), code)


def _delete_bericht(env: Environment, bericht: str) -> None:
    """Delete a bericht (uuid), which frees its berichttype, in Open VTB's Django shell: the API answers 405."""
    code = f"from openvtb.components.berichten.models import Bericht\nBericht.objects.filter(uuid={bericht!r}).delete()"
    env.kube.exec_django_shell(env.deployment_for("openvtb"), code)
