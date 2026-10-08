"""Keycloak admin REST API: the calls bootstrap needs for test users (PLAN.md §4 A1)."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak import PasswordLogin
from podiumd_tests.auth.keycloak import admin_realm_url
from podiumd_tests.auth.keycloak import password_grant
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject


def user_email(username: str) -> str:
    """The e-mail address create_user gives a user; Open Klant actors are matched on it."""
    return f"{username}@example.invalid"


def realm_of(env: Environment) -> str:
    """The realm the applications log in to (settings.keycloak_realm, default podiumd)."""
    return env.profile.settings.get("keycloak_realm", "podiumd")


def for_environment(env: Environment, realm: str | None = None) -> KeycloakAdmin:
    """Admin client for a realm (default: the environment's), through keycloak-admin when the profile has it."""
    url = env.profile.urls.get("keycloak-admin") or env.profile.urls["keycloak"]
    admin = (env.credentials.get("keycloak_admin_username"), env.credentials.get("keycloak_admin_password"))
    return KeycloakAdmin(env.session(cookies=False), url, realm or realm_of(env), admin)


class KeycloakAdmin:  # pylint: disable=too-many-public-methods  # one method per Admin REST call
    """Admin calls on one realm, with a token of an admin user in the master realm."""

    def __init__(self, http: requests.Session, url: str, realm: str, admin: tuple[str, str]) -> None:
        self.http = http
        self.realm = realm
        self.base = admin_realm_url(url, realm)
        token = password_grant(http, url, "master", PasswordLogin("admin-cli", *admin))
        self.headers = {"Authorization": f"Bearer {token}"}

    def _get(self, path: str, params: dict[str, str] | None = None) -> object:
        return expect_status(self.http.get(self.base + path, params=params, headers=self.headers), HTTPStatus.OK).json()

    def _send(self, method: str, path: str, body: object, *expected: int) -> None:
        response = self.http.request(method, self.base + path, json=body, headers=self.headers)
        expect_status(response, *(expected or (HTTPStatus.NO_CONTENT,)))

    def representation(self) -> JsonObject:
        """The realm's own settings, e.g. smtpServer."""
        return cast("JsonObject", self._get(""))

    def user(self, username: str) -> JsonObject | None:
        """The user with exactly this username, or None."""
        users = cast("list[JsonObject]", self._get("/users", {"username": username, "exact": "true"}))
        return users[0] if users else None

    def user_id(self, username: str) -> str | None:
        """Id of the user with exactly this username, or None."""
        user = self.user(username)
        return str(user["id"]) if user else None

    def users(self, search: str) -> list[JsonObject]:
        """The users whose username, e-mail or name contains the text."""
        count = self.count_users(search)
        return cast(
            "list[JsonObject]",
            self._get("/users", {"search": search, "max": str(count), "briefRepresentation": "true"}),
        )

    def count_users(self, search: str) -> int:
        """How many users' username, e-mail or name contains the text."""
        return cast("int", self._get("/users/count", {"search": search}))

    def create_user(
        self, username: str, password: str, attributes: dict[str, list[str]], name: tuple[str, str] | None = None
    ) -> str:
        """Create an enabled user without required actions, by default named PodiumD <username>; its id."""
        first, last = name or ("PodiumD", username)
        body = {
            "username": username,
            "enabled": True,
            "email": user_email(username),
            "emailVerified": True,
            "firstName": first,
            "lastName": last,
            "attributes": attributes,
            "requiredActions": [],
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        self._send("POST", "/users", body, HTTPStatus.CREATED)
        user_id = self.user_id(username)
        if user_id is None:
            msg = f"user {username} not found after creating it"
            raise LookupError(msg)
        return user_id

    def delete_user(self, user_id: str) -> None:
        """Delete a user."""
        self._send("DELETE", f"/users/{user_id}", None)

    def realm_roles(self, names: tuple[str, ...]) -> list[JsonObject]:
        """The realm roles with these names that exist."""
        roles = cast("list[JsonObject]", self._get("/roles"))
        return [r for r in roles if r.get("name") in names]

    def add_realm_roles(self, user_id: str, roles: list[JsonObject]) -> None:
        """Map realm roles to a user."""
        if roles:
            self._send("POST", f"/users/{user_id}/role-mappings/realm", roles)

    def client(self, client_id: str) -> JsonObject | None:
        """The client with this clientId, or None."""
        clients = cast("list[JsonObject]", self._get("/clients", {"clientId": client_id}))
        return clients[0] if clients else None

    def client_role(self, client_id: str, role: str) -> tuple[str, JsonObject] | None:
        """(client uuid, role) when the client and its role exist."""
        client = self.client(client_id)
        if client is None:
            return None
        uuid = str(client["id"])
        roles = cast("list[JsonObject]", self._get(f"/clients/{uuid}/roles"))
        found = next((r for r in roles if r.get("name") == role), None)
        return (uuid, found) if found else None

    def add_client_role(self, user_id: str, client_uuid: str, role: JsonObject) -> None:
        """Map one client role to a user."""
        self._send("POST", f"/users/{user_id}/role-mappings/clients/{client_uuid}", [role])

    def group_id(self, name: str) -> str | None:
        """Id of the top-level group with this name, or None."""
        groups = cast("list[JsonObject]", self._get("/groups", {"search": name, "exact": "true"}))
        return next((str(g["id"]) for g in groups if g.get("name") == name), None)

    def join_group(self, user_id: str, group_id: str) -> None:
        """Add a user to a group."""
        self._send("PUT", f"/users/{user_id}/groups/{group_id}", None)

    def update_client(self, client: JsonObject) -> None:
        """Replace a client's representation (from client())."""
        self._send("PUT", f"/clients/{client['id']}", client)

    def client_secret(self, client_uuid: str) -> str:
        """A confidential client's secret."""
        return str(cast("JsonObject", self._get(f"/clients/{client_uuid}/client-secret"))["value"])

    def client_scopes(self) -> dict[str, str]:
        """Client scope name -> id."""
        return {str(s["name"]): str(s["id"]) for s in cast("list[JsonObject]", self._get("/client-scopes"))}

    def create_client_scope(self, scope: JsonObject) -> str:
        """Create a client scope; its id."""
        self._send("POST", "/client-scopes", scope, HTTPStatus.CREATED)
        return self.client_scopes()[str(scope["name"])]

    def delete_client_scope(self, scope_id: str) -> None:
        """Delete a client scope, with its mappers and client attachments."""
        self._send("DELETE", f"/client-scopes/{scope_id}", None)

    def scope_mappers(self, scope_id: str) -> dict[str, str]:
        """Protocol mapper name -> id of a client scope."""
        mappers = cast("list[JsonObject]", self._get(f"/client-scopes/{scope_id}/protocol-mappers/models"))
        return {str(m["name"]): str(m["id"]) for m in mappers}

    def add_scope_mapper(self, scope_id: str, mapper: JsonObject) -> None:
        """Add a protocol mapper to a client scope."""
        self._send("POST", f"/client-scopes/{scope_id}/protocol-mappers/models", mapper, HTTPStatus.CREATED)

    def delete_scope_mapper(self, scope_id: str, mapper_id: str) -> None:
        """Delete one protocol mapper of a client scope."""
        self._send("DELETE", f"/client-scopes/{scope_id}/protocol-mappers/models/{mapper_id}", None)

    def client_scope_names(self, client_uuid: str) -> set[str]:
        """Names of the default and optional client scopes of a client."""
        found: set[str] = set()
        for kind in ("default-client-scopes", "optional-client-scopes"):
            found |= {str(s["name"]) for s in cast("list[JsonObject]", self._get(f"/clients/{client_uuid}/{kind}"))}
        return found

    def set_optional_scope(self, client_uuid: str, scope_id: str, *, attached: bool) -> None:
        """Attach a client scope to a client as optional, or detach it."""
        self._send("PUT" if attached else "DELETE", f"/clients/{client_uuid}/optional-client-scopes/{scope_id}", None)
