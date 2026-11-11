"""A throwaway zaaktype that ZAC handles: published in the test catalogus as its own deelzaaktype, known to PABC.

ZAC keeps the zaakafhandelparameters of a deleted zaaktype: it has no call to delete them. They name a run-tagged
omschrijving that no other zaaktype has, and have no productaanvraagtype.
"""

from __future__ import annotations

import secrets

from datetime import date
from datetime import timedelta
from typing import TYPE_CHECKING

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.bootstrap.bpmn import uuid_of
from podiumd_tests.bootstrap.names import ZAC_DOMAIN
from podiumd_tests.bootstrap.names import ZAC_FUNCTIONAL_ROLE
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.pabc import add_zaaktype_entity_type
from podiumd_tests.pabc import admin_session
from podiumd_tests.pabc import delete_entity_type
from podiumd_tests.pabc import ensure_domain
from podiumd_tests.pabc import zaaktype_entity_type
from podiumd_tests.seed.catalogi import ZaaktypeTypes
from podiumd_tests.seed.catalogi import make_publishable_zaaktype
from podiumd_tests.seed.catalogi import publish
from podiumd_tests.seed.openzaak import today
from podiumd_tests.zac import clear_ztc_cache
from podiumd_tests.zac import configure_zaaktype
from podiumd_tests.zac import user_groups
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# The statustypen of ZAC's CMMN model and the roltypen ZAC requires.
ZAC_TYPES = ZaaktypeTypes(
    ("Intake", "In behandeling", "Afgerond"), (("Initiator", "initiator"), ("Behandelaar", "behandelaar"))
)


def zac_as_admin(env: Environment) -> requests.Session:
    """Return a session on ZAC's REST API as the test admin, ZAC's beheerder."""
    return zac_session(env, ADMIN.username, env.credentials.get(ADMIN.store_key))


def pabc_as_admin(env: Environment) -> tuple[requests.Session, str]:
    """Return PABC's management API as the test admin, and PABC's URL."""
    return admin_session(env, ADMIN.username, env.credentials.get(ADMIN.store_key)), env.profile.urls["pabc"]


def publish_zac_zaaktype(
    env: Environment, openzaak: ApiClient, registry: ResourceRegistry, template: JsonObject, **fields: object
) -> JsonObject:
    """Publish a throwaway zaaktype with run-tagged omschrijving that ZAC can handle and that is its own deelzaaktype.

    A new version takes the identificatie and omschrijving of the one before in fields.
    """
    body: dict[str, object] = {"omschrijving": registry.tagged(f"zac-{secrets.token_hex(3)}"), **fields}
    concept = make_publishable_zaaktype(env, openzaak, registry, template, ZAC_TYPES, **body)
    openzaak.patch(str(concept["url"]), {"deelzaaktypen": [concept["url"]]})
    return publish(openzaak, concept)


def publish_new_version(
    env: Environment, openzaak: ApiClient, registry: ResourceRegistry, template: JsonObject, zaaktype: JsonObject
) -> JsonObject:
    """End the published zaaktype yesterday and publish its next version, valid from today; the new version.

    Open Zaak notifies no publish: the new version is updated after it, so ZAC copies the zaakafhandelparameters.
    """
    yesterday = date.fromisoformat(today()) - timedelta(days=1)
    openzaak.patch(str(zaaktype["url"]), {"eindeGeldigheid": yesterday.isoformat()})
    same = {key: zaaktype[key] for key in ("identificatie", "omschrijving", "servicenorm")}
    version = publish_zac_zaaktype(env, openzaak, registry, template, **same, beginGeldigheid=today())
    return openzaak.patch(str(version["url"]), {"eindeGeldigheid": None})


def grant_zaaktype(env: Environment, registry: ResourceRegistry, omschrijving: str) -> None:
    """Add the zaaktype to PABC domain ZAC_DOMAIN, whose roles the test users have; cleanup deletes its entity type.

    ZAC reads a user's rights at login: a session from before has none on the zaaktype.
    """
    pabc, pabc_url = pabc_as_admin(env)
    entity_type = add_zaaktype_entity_type(pabc, pabc_url, omschrijving)
    registry.add(f"PABC entity type {omschrijving}", lambda: forget_zaaktype(env, omschrijving))
    ensure_domain(pabc, pabc_url, ZAC_DOMAIN, [entity_type])


def forget_zaaktype(env: Environment, omschrijving: str) -> None:
    """Delete the zaaktype's PABC entity type, where it exists, with a new login: cleanup can run hours later."""
    pabc, pabc_url = pabc_as_admin(env)
    entity_type = zaaktype_entity_type(pabc, pabc_url, omschrijving)
    if entity_type is not None:
        delete_entity_type(pabc, pabc_url, entity_type)


def make_role_group(env: Environment, registry: ResourceRegistry, role: str) -> str:
    """Create a run-tagged Keycloak group with podiumd-tests' functional role for one ZAC role; its name.

    PABC authorises a group by its realm roles; the role is mapped in domain ZAC_DOMAIN only.
    """
    name = registry.tagged(f"zac-{role}")
    group = for_environment(env).create_group(name, (f"{ZAC_FUNCTIONAL_ROLE}-{role}",))
    # A fresh admin token: the master realm's tokens expire within minutes.
    registry.add(f"Keycloak group {name}", lambda: for_environment(env).delete_group(group))
    return name


def make_zac_zaaktype(
    env: Environment, openzaak: ApiClient, registry: ResourceRegistry, template: JsonObject, **fields: object
) -> JsonObject:
    """Publish a throwaway zaaktype, grant it and configure it in the admin's first group; its zaakafhandelparameters.

    Cleanup deletes it and then clears ZAC's ZTC cache.
    """
    zac_url = env.profile.urls["zac"]
    registry.add("ZAC's ZTC cache", lambda: clear_ztc_cache(zac_as_admin(env), zac_url))
    zaaktype = publish_zac_zaaktype(env, openzaak, registry, template, **fields)
    grant_zaaktype(env, registry, str(zaaktype["omschrijving"]))
    admin = zac_as_admin(env)
    return configure_zaaktype(admin, zac_url, uuid_of(zaaktype["url"]), user_groups(admin, zac_url)[0])
