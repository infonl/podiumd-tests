"""Snapshot of zaaktypen, ZAC's zaakafhandelparameters and the oldest zaken, to compare after a release.

Draaiboek ZAC-004, FB-013 and FB-014. It keeps a hash per field, never a value: zaken hold personal
data. A field a release adds is no change; a field it changes or removes is.
"""

from __future__ import annotations

import hashlib
import json

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.results import now_iso
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.workloads import pod_containers
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import zaakafhandelparameters
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from pathlib import Path

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

SNAPSHOT = "snapshot.json"
# The oldest zaken: mostly closed, so nobody changes them between the snapshot and the release.
SAMPLE = 100
# Zaaktypen the suite creates itself.
TEST_PREFIX = "ptest-"
COMPARED = ("zaaktypen", "zaakafhandelparameters", "zaken")
# Open Zaak sets it when anyone only opens the zaak.
OPENED = "laatstGeopend"
# Changed fields named per object.
SHOWN = 8

type Fingerprint = dict[str, str]


def _hash(value: object) -> str:
    if isinstance(value, list):
        value = sorted(json.dumps(item, sort_keys=True) for item in cast("list[object]", value))
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]


def fingerprint(value: object, prefix: str = "") -> Fingerprint:
    """A hash per field, nested objects flattened to dotted names ("status.naam")."""
    if not isinstance(value, dict) or not value:
        return {prefix.rstrip("."): _hash(cast("object", value))}
    found: Fingerprint = {}
    for key, item in cast("JsonObject", value).items():
        found |= fingerprint(item, f"{prefix}{key}.")
    return found


def images(env: Environment) -> dict[str, list[str]]:
    """The container images of Open Zaak's and ZAC's deployments: a release changes them."""
    names = {env.deployment_for(c) for c in ("openzaak", "zac") if c in env.profile.urls}
    return {
        metadata_name(w): sorted(str(c.get("image")) for c in pod_containers(w, with_init=False))
        for w in env.items("deployments")
        if metadata_name(w) in names
    }


def take(env: Environment) -> JsonObject:
    """The snapshot of the environment now."""
    openzaak = openzaak_client(env, ZGW_CLIENT_ID, ZGW_STORE_KEY, "snapshot")
    zaaktypen = [
        z for z in openzaak.list(f"{CATALOGI}/zaaktypen") if not str(z.get("identificatie")).startswith(TEST_PREFIX)
    ]
    zaken = entries(openzaak.get(f"{ZAKEN}/zaken", {"ordering": "startdatum"}).get("results"))[:SAMPLE]
    found: dict[str, dict[str, Fingerprint]] = {
        "zaaktypen": {f"{z.get('identificatie')} {z.get('versiedatum')}": fingerprint(z) for z in zaaktypen},
        "zaakafhandelparameters": {},
        "zaken": {
            str(z.get("identificatie")): fingerprint({k: v for k, v in z.items() if k != OPENED}, "openzaak.")
            for z in zaken
        },
    }
    zac_url = env.profile.urls.get("zac")
    if zac_url:
        zac = zac_session(env, ADMIN.username, env.credentials.get(ADMIN.store_key))
        for parameters in zaakafhandelparameters(zac, zac_url):
            zaaktype = section(parameters, "zaaktype")
            key = f"{zaaktype.get('identificatie')} {zaaktype.get('uuid')}"
            found["zaakafhandelparameters"][key] = fingerprint(parameters)
        for zaak in zaken:
            try:
                view = fingerprint(read_zaak(zac, zac_url, str(zaak.get("uuid"))), "zac.")
            except UnexpectedStatusError:
                view = {"zac": "unreadable"}
            found["zaken"][str(zaak.get("identificatie"))] |= view
    return {"taken": now_iso(), "images": images(env), **found}


def differences(before: JsonObject, after: JsonObject) -> list[str]:
    """What changed or disappeared since the snapshot before, per object; empty when nothing did."""
    found: list[str] = []
    for name in COMPARED:
        old, now = section(before, name), section(after, name)
        for key in old:
            if key not in now:
                found.append(f"{name} {key}: gone")
                continue
            changed = sorted(f for f, h in section(old, key).items() if section(now, key).get(f) != h)
            if changed:
                more = f" and {len(changed) - SHOWN} more" if len(changed) > SHOWN else ""
                found.append(f"{name} {key}: {', '.join(changed[:SHOWN])}{more}")
    return found


def latest(results: Path, env: str) -> JsonObject | None:
    """The newest snapshot of the environment under the results directory, or None."""
    for run in sorted(results.glob(f"*/*_{env}_snapshot_*"), reverse=True):
        if (run / SNAPSHOT).is_file():
            return json.loads((run / SNAPSHOT).read_text(encoding="utf-8"))
    return None
