"""Grafana's login through Keycloak (generic OAuth, client monitoring) and its link to the Grafana user."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.auth.keycloak_admin import user_email
from podiumd_tests.browser import browser_session
from podiumd_tests.browser import keycloak_login
from podiumd_tests.grafana import grafana_auth
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("grafana", "keycloak", "keycloak-admin")]

# Grafana's client in the realm; its client roles become claim monitoring_roles (role_attribute_path).
CLIENT = "monitoring"


def grafana_login(page: Page, env: Environment, username: str, password: str) -> JsonObject:
    """Log in to Grafana through Keycloak; Grafana's own view of the logged-in user, with its org role."""
    grafana = env.profile.urls["grafana"]
    page.context.clear_cookies()
    page.goto(grafana + "/login/generic_oauth")
    keycloak_login(page, username, password)
    page.wait_for_url(lambda url: url_host(url) == url_host(grafana) and "/login" not in url)
    http = browser_session(page, env)
    user = expect_status(http.get(grafana + "/api/user"), HTTPStatus.OK).json()
    orgs = expect_status(http.get(grafana + "/api/user/orgs"), HTTPStatus.OK).json()
    return {**user, "role": next((o["role"] for o in orgs if o.get("orgId") == user.get("orgId")), None)}


def make_user(admin: KeycloakAdmin, username: str, password: str, role: str) -> str:
    """A Keycloak user with one client role of Grafana's client; its id."""
    user_id = admin.create_user(username, password, {})
    found = admin.client_role(CLIENT, role)
    if found is None:
        pytest.fail(f"Keycloak client {CLIENT} has no role {role}")
    client_uuid, client_role = found
    admin.add_client_role(user_id, client_uuid, client_role)
    return user_id


@pytest.mark.source(
    "podiumd-tests",
    "monitoring-logging 1.0.19 (#697, IN-3352): a recreated Keycloak account links to its existing Grafana user by e-mail.",
)
@pytest.mark.scenario("""
    Given a Keycloak user with Grafana's editor role who has logged in to Grafana once
    When the user is deleted and created again in Keycloak with the same e-mail address and the admin role
    And logs in to Grafana again
    Then Grafana links the login to the same Grafana user
    And the user's Grafana role is Admin, from the new token
""")
def test_recreated_keycloak_user_logs_in_to_the_same_grafana_user(
    page: Page, podiumd_env: Environment, registry: ResourceRegistry
) -> None:
    """After its Keycloak account is recreated, a login reaches the same Grafana user, with the role of the new token."""
    grafana = podiumd_env.profile.urls["grafana"]
    settings = expect_status(podiumd_env.session().get(grafana + "/api/frontend/settings"), HTTPStatus.OK).json()
    if "generic_oauth" not in (settings.get("oauth") or {}):
        pytest.skip("Grafana's Keycloak login is off here (auth.generic_oauth.enabled)")
    admin = for_environment(podiumd_env)
    username, password = registry.tagged("grafana"), admin.new_password()
    auth = grafana_auth(podiumd_env.credentials)
    if auth is None:
        pytest.skip(
            "Grafana's admin login is needed to remove the test's Grafana user: secrets grafana_username/password"
        )

    def remove_grafana_user() -> None:
        lookup = podiumd_env.session().get(
            f"{grafana}/api/users/lookup", params={"loginOrEmail": user_email(username)}, auth=auth
        )
        if lookup.status_code == HTTPStatus.OK:
            podiumd_env.session().delete(f"{grafana}/api/admin/users/{lookup.json()['id']}", auth=auth)

    registry.add(f"grafana user {username}", remove_grafana_user)
    first_id = make_user(admin, username, password, "editor")
    registry.add(f"keycloak user {username}", lambda: [admin.delete_user(u) for u in [admin.user_id(username)] if u])
    first = grafana_login(page, podiumd_env, username, password)
    assert first["role"] == "Editor", first

    admin.delete_user(first_id)
    second_id = make_user(admin, username, password, "admin")
    assert second_id != first_id
    second = grafana_login(page, podiumd_env, username, password)
    assert (second["id"], second["email"]) == (first["id"], first["email"]), (first, second)
    assert second["role"] == "Admin", second
