"""The perf tier's Keycloak calls: a test user's password login and a client's client-credentials grant.

Only the Locust process imports this module: its account pool waits with gevent.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from gevent.queue import Queue

from podiumd_tests.auth.keycloak import client_credentials_grant
from podiumd_tests.auth.keycloak import login_page_action
from podiumd_tests.auth.keycloak import submit_login
from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.auth.keycloak_admin import realm_of
from podiumd_tests.oidc import LOGIN_PATHS
from podiumd_tests.perf.runs import LOGIN_USERS
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.perf.zgw_calls import Call
    from podiumd_tests.perf.zgw_calls import Prepared
    from podiumd_tests.seed.registry import ResourceRegistry

# Its tokens are what ZAC itself asks for: ZAC reads users and groups through Keycloak's admin API with it.
SERVICE_CLIENT = "zac-admin-client"
type _Login = tuple[requests.Session, str, tuple[str, str]]
# Keycloak refuses a login of a user while another login of that user is in progress (keycloak#33527), and
# one_login_at_a_time's file lock would block the whole Locust process: an account logs in once at a time.
type Accounts = Queue[tuple[str, str]]


def login_accounts(env: Environment) -> Accounts:
    """Return the (username, password) of LOGIN_USERS, for the Locust users of one process to share."""
    accounts: Accounts = Queue()
    for user in LOGIN_USERS:
        accounts.put((user.username, env.credentials.get(user.store_key)))
    return accounts


def keycloak_calls(env: Environment, accounts: Accounts) -> dict[str, Call | Prepared]:
    """Return a password login at ZAC's Keycloak login form, as one of the accounts, and SERVICE_CLIENT's token."""
    urls, realm = env.profile.urls, realm_of(env)
    admin = for_environment(env)
    client = admin.client(SERVICE_CLIENT)
    secret = admin.client_secret(str(client["id"])) if client else None
    http = env.session(cookies=False)

    def login_form(registry: ResourceRegistry) -> _Login:
        account = accounts.get()
        registry.add(f"login account {account[0]}", lambda: accounts.put(account))
        session = env.session()
        return session, login_page_action(session, urls["zac"] + LOGIN_PATHS["zac"]), account

    def login(prepared: object) -> None:
        session, action, (username, password) = cast("_Login", prepared)
        expect_status(submit_login(session, action, username, password, allow_redirects=False), HTTPStatus.FOUND)

    def token(_registry: ResourceRegistry) -> str:
        if secret is None:
            msg = f"realm {realm} has no client {SERVICE_CLIENT}"
            raise LookupError(msg)
        return client_credentials_grant(http, urls["keycloak"], realm, (SERVICE_CLIENT, secret))

    return {"kc_login": (login_form, login), "kc_client_credentials": token}
