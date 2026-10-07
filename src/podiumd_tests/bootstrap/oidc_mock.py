"""Wiring W1: DigiD and eHerkenning through Keycloak's mock instead of the real services.

The real DigiD and eHerkenning are unreachable from minikube, QA and some gemeente
environments; tests log in through Keycloak users with bsn, kvk and vestigingsnummer
attributes. Ported from ExternalsPodiumD smoke-tests/scripts/seed-identities.sh. Every
step records what it added and removes exactly that.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.auth.keycloak_admin import realm_of

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.bootstrap import Context
    from podiumd_tests.json_data import JsonObject

# Keycloak client per app (component), the scopes its users log in with, and whether the
# app's profile URL must be a redirect URI of the client.
CLIENTS: dict[str, tuple[str, tuple[str, ...], bool]] = {
    "openinwoner": ("openinwoner", ("bsn", "eherkenning"), True),
    "openformulieren": ("openformulieren", ("bsn",), False),
}
KEYCLOAK_STORE_KEY = "ptest_bootstrap_keycloak_oidc_mock_record"


def _attribute_mapper(name: str, attribute: str, claim: str) -> JsonObject:
    return {
        "name": name,
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "config": {
            "user.attribute": attribute,
            "claim.name": claim,
            "jsonType.label": "String",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "userinfo.token.claim": "true",
        },
    }


# The claims Open Inwoner reads (identity_settings in openinwoner_oidc_mock). A dot in a claim
# name is escaped, or Keycloak nests the claim at the dot.
SCOPES: dict[str, tuple[str, list[JsonObject]]] = {
    "bsn": ("DigiD BSN claim", [_attribute_mapper("bsn-claim", "bsn", "bsn")]),
    "eherkenning": (
        "eHerkenning claims (KvK, vestiging, namequalifier)",
        [
            _attribute_mapper("kvk-claim", "kvk", "urn:etoegang:core:LegalSubjectID"),
            _attribute_mapper(
                "vestigingsnr-claim", "vestigingsnummer", "urn:etoegang:1\\.9:ServiceRestriction:Vestigingsnr"
            ),
            {
                "name": "namequalifier-claim",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-hardcoded-claim-mapper",
                "config": {
                    "claim.name": "namequalifier",
                    "claim.value": "urn:etoegang:1.9:EntityConcernedID:KvKnr",
                    "jsonType.label": "String",
                    "id.token.claim": "true",
                    "access.token.claim": "true",
                    "userinfo.token.claim": "true",
                },
            },
        ],
    ),
}


def _scope_body(name: str, description: str) -> JsonObject:
    return {
        "name": name,
        "description": description,
        "protocol": "openid-connect",
        "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
    }


def _clients(ctx: Context, admin: KeycloakAdmin) -> list[tuple[JsonObject, tuple[str, ...], str | None]]:
    """(client, scopes, redirect URI or None) for each app the environment has; skipped apps get a note."""
    found: list[tuple[JsonObject, tuple[str, ...], str | None]] = []
    for component, (client_id, scopes, redirect) in CLIENTS.items():
        if ctx.env.capabilities.skip_reason(component):
            continue
        client = admin.client(client_id)
        if client is None:
            ctx.notes.append(f"realm {admin.realm} has no client {client_id}")
            continue
        found.append((client, scopes, ctx.env.profile.urls[component] + "/*" if redirect else None))
    return found


def _record(ctx: Context) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(ctx.store.read().get(KEYCLOAK_STORE_KEY, "{}")))


@dataclass(frozen=True)
class KeycloakOidcMock:
    """Keycloak side: the bsn and eherkenning client scopes on the apps' clients, with Open Inwoner's redirect URI."""

    name: str = "keycloak-oidc-mock"
    requires: tuple[str, ...] = ("keycloak",)
    wiring: bool = True

    def is_present(self, ctx: Context, /) -> bool:
        """Both scopes with all their mappers exist, and every app's client has its scopes and redirect URI."""
        admin = for_environment(ctx.env)
        scopes = admin.client_scopes()
        for name, (_, mappers) in SCOPES.items():
            if name not in scopes or {str(m["name"]) for m in mappers} - set(admin.scope_mappers(scopes[name])):
                return False
        for client, wanted, redirect in _clients(ctx, admin):
            if set(wanted) - admin.client_scope_names(str(client["id"])):
                return False
            if redirect and redirect not in cast("list[str]", client.get("redirectUris") or []):
                return False
        return True

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Add what is missing, and extend the stored record with it."""
        admin = for_environment(ctx.env)
        record = _record(ctx)
        scopes = _ensure_scopes(admin, record)
        attached = cast("dict[str, list[str]]", record.setdefault("attached", {}))
        redirects = cast("dict[str, str]", record.setdefault("redirects", {}))
        for client, wanted, redirect in _clients(ctx, admin):
            client_id = str(client["clientId"])
            for name in sorted(set(wanted) - admin.client_scope_names(str(client["id"]))):
                admin.set_optional_scope(str(client["id"]), scopes[name], attached=True)
                attached.setdefault(client_id, []).append(name)
            uris = cast("list[str]", client.get("redirectUris") or [])
            if redirect and redirect not in uris:
                admin.update_client({**client, "redirectUris": [*uris, redirect]})
                redirects[client_id] = redirect
        return {KEYCLOAK_STORE_KEY: json.dumps(record, sort_keys=True)}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Undo exactly what the record lists."""
        record = _record(ctx)
        if record:
            admin = for_environment(ctx.env)
            scopes = admin.client_scopes()
            _undo_clients(admin, record, scopes)
            _undo_scopes(admin, record, scopes)
        return (KEYCLOAK_STORE_KEY,)


def _ensure_scopes(admin: KeycloakAdmin, record: dict[str, object]) -> dict[str, str]:
    """Create missing scopes and mappers, recording them; every scope name -> id."""
    created = cast("list[str]", record.setdefault("scopes", []))
    added = cast("dict[str, list[str]]", record.setdefault("mappers", {}))
    scopes = admin.client_scopes()
    for name, (description, mappers) in SCOPES.items():
        if name not in scopes:
            scopes[name] = admin.create_client_scope(_scope_body(name, description))
            created.append(name)
        existing = admin.scope_mappers(scopes[name])
        for mapper in mappers:
            if mapper["name"] not in existing:
                admin.add_scope_mapper(scopes[name], mapper)
                if name not in created:
                    added.setdefault(name, []).append(str(mapper["name"]))
    return scopes


def _undo_clients(admin: KeycloakAdmin, record: dict[str, object], scopes: dict[str, str]) -> None:
    redirects = cast("dict[str, str]", record.get("redirects") or {})
    attached = cast("dict[str, list[str]]", record.get("attached") or {})
    for client_id in sorted(set(attached) | set(redirects)):
        client = admin.client(client_id)
        if client is None:
            continue
        for name in attached.get(client_id, []):
            if name in scopes:
                admin.set_optional_scope(str(client["id"]), scopes[name], attached=False)
        if client_id in redirects:
            uris = cast("list[str]", client.get("redirectUris") or [])
            admin.update_client({**client, "redirectUris": [u for u in uris if u != redirects[client_id]]})


def _undo_scopes(admin: KeycloakAdmin, record: dict[str, object], scopes: dict[str, str]) -> None:
    for name, mapper_names in cast("dict[str, list[str]]", record.get("mappers") or {}).items():
        if name in scopes:
            existing = admin.scope_mappers(scopes[name])
            for mapper in mapper_names:
                if mapper in existing:
                    admin.delete_scope_mapper(scopes[name], existing[mapper])
    for name in cast("list[str]", record.get("scopes") or []):
        if name in scopes:
            admin.delete_client_scope(scopes[name])


def oidc_params(component: str) -> Callable[[Context], dict[str, object]]:
    """Context params for the oidc_mock snippet in one app: Keycloak's endpoints and its client's secret."""

    def params(ctx: Context) -> dict[str, object]:
        admin = for_environment(ctx.env)
        client_id = CLIENTS[component][0]
        client = admin.client(client_id)
        if client is None:
            msg = f"realm {admin.realm} has no client {client_id}"
            raise LookupError(msg)
        return {
            "endpoint": f"{ctx.env.profile.urls['keycloak']}/realms/{realm_of(ctx.env)}/protocol/openid-connect",
            "client_id": client_id,
            "secret": admin.client_secret(str(client["id"])),
        }

    return params
