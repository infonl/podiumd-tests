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

    from podiumd_tests.json_data import JsonObject


def user_email(username: str) -> str:
    """The e-mail address create_user gives a user; Open Klant actors are matched on it."""
    return f"{username}@example.invalid"


class KeycloakAdmin:
    """Admin calls on one realm, with a token of an admin user in the master realm."""

    def __init__(self, http: requests.Session, url: str, realm: str, admin: tuple[str, str]) -> None:
        self.http = http
        self.base = admin_realm_url(url, realm)
        token = password_grant(http, url, "master", PasswordLogin("admin-cli", *admin))
        self.headers = {"Authorization": f"Bearer {token}"}

    def _get(self, path: str, params: dict[str, str] | None = None) -> object:
        return expect_status(self.http.get(self.base + path, params=params, headers=self.headers), HTTPStatus.OK).json()

    def _send(self, method: str, path: str, body: object, *expected: int) -> None:
        response = self.http.request(method, self.base + path, json=body, headers=self.headers)
        expect_status(response, *(expected or (HTTPStatus.NO_CONTENT,)))

    def user_id(self, username: str) -> str | None:
        """Id of the user with exactly this username, or None."""
        users = cast("list[JsonObject]", self._get("/users", {"username": username, "exact": "true"}))
        return str(users[0]["id"]) if users else None

    def create_user(self, username: str, password: str, attributes: dict[str, list[str]]) -> str:
        """Create an enabled user without required actions; its id."""
        body = {
            "username": username,
            "enabled": True,
            "email": user_email(username),
            "emailVerified": True,
            "firstName": "PodiumD",
            "lastName": username,
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

    def client_role(self, client_id: str, role: str) -> tuple[str, JsonObject] | None:
        """(client uuid, role) when the client and its role exist."""
        clients = cast("list[JsonObject]", self._get("/clients", {"clientId": client_id}))
        if not clients:
            return None
        uuid = str(clients[0]["id"])
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
