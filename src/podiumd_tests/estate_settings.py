"""An estate profile's Keycloak settings on a test environment, and their restore from a state file.

The state file holds what restore needs, client secrets included; it is written before the first change and before
each next one, so a restore after a failed apply also undoes a change that was under way.
"""

from __future__ import annotations

import json

from typing import TYPE_CHECKING
from typing import cast

import requests

from podiumd_tests.auth.keycloak import TokenError
from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.auth.master_otp import OPERATOR
from podiumd_tests.auth.master_otp import REQUIRED
from podiumd_tests.auth.master_otp import SERVICE_ADMIN
from podiumd_tests.auth.master_otp import create_service_admin
from podiumd_tests.auth.master_otp import has_recreated_operator
from podiumd_tests.auth.master_otp import otp_changes
from podiumd_tests.auth.master_otp import service_admin_login
from podiumd_tests.bootstrap.runner import refusal as bootstrap_refusal
from podiumd_tests.credentials import SecretError
from podiumd_tests.estate_profile import ABSENT
from podiumd_tests.estate_profile import UNKNOWN
from podiumd_tests.estate_profile import master_value
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import UnexpectedStatusError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.config import Profile
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

type State = dict[str, object]

# Estates of our own test environments: the only ones apply and restore change.
TEST_ESTATES = ("podiumd-infra", "minikube")
# Errors of a Keycloak admin call: the login, a refused call, the network, the admin credentials.
KEYCLOAK_ERRORS = (TokenError, UnexpectedStatusError, requests.RequestException, SecretError, LookupError)


class StateError(Exception):
    """The state file is missing or unreadable."""


def refusal(profile: Profile) -> str | None:
    """Why apply and restore may not change this environment, or None."""
    if profile.estate not in TEST_ESTATES:
        return f"{profile.name} is in estate {profile.estate}: only {', '.join(TEST_ESTATES)} test environments"
    return bootstrap_refusal(profile)


def _save(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def apply(env: Environment, profile: JsonObject, path: Path) -> list[str]:
    """Give master the profile's absent operator client and required OTP, recording each change in path first.

    SERVICE_ADMIN comes first, so restore can log in once master requires OTP. Other values keep the environment's.
    """
    state: State = {"env": env.profile.name, "service_admin": None, "operator": None, "requirements": []}
    _save(path, state)
    secret = create_service_admin(for_environment(env, "master"), lambda _uuid: None)
    state["service_admin"] = {"secret": secret}
    _save(path, state)
    admin = service_admin_login(env, secret)
    done = [f"master client {SERVICE_ADMIN} created"]
    operator = master_value(profile, "operator_client")
    if operator == ABSENT:
        done.append(_remove_operator(admin(), path, state))
    otp = master_value(profile, "direct_grant_otp")
    if otp == REQUIRED:
        done.append(_require_otp(admin(), path, state))
    done += [f"{field} is unknown in the profile: kept" for field, value in _fields(operator, otp) if value == UNKNOWN]
    return done


def _fields(operator: str, otp: str) -> tuple[tuple[str, str], ...]:
    return ("operator_client", operator), ("direct_grant_otp", otp)


def _remove_operator(master: KeycloakAdmin, path: Path, state: State) -> str:
    client = master.client(OPERATOR)
    if client is None:
        return f"master client {OPERATOR} was absent already"
    state["operator"] = {"client": client, "secret": master.client_secret(str(client["id"]))}
    _save(path, state)
    master.delete_client(str(client["id"]))
    return f"master client {OPERATOR} deleted"


def _require_otp(master: KeycloakAdmin, path: Path, state: State) -> str:
    flow, changes = otp_changes(master)
    recorded = cast("list[object]", state["requirements"])
    for execution, requirement in changes:
        recorded.append({"flow": flow, "execution": execution, "requirement": execution["requirement"]})
        _save(path, state)
        master.set_requirement(flow, execution, requirement)
    return f"master {flow} requires OTP of every user"


def restore(env: Environment, path: Path) -> list[str]:
    """Undo what apply recorded in path, each step with a fresh login, then delete path."""
    state = _load(path)
    if state.get("env") != env.profile.name:
        msg = f"state file {path} is of {state.get('env')}, not {env.profile.name}"
        raise StateError(msg)
    secret = section(state, "service_admin").get("secret")
    admin: Callable[[], KeycloakAdmin] = (
        service_admin_login(env, str(secret)) if secret else lambda: for_environment(env, "master")
    )
    done: list[str] = []
    operator = section(state, "operator")
    if operator:
        recreated = has_recreated_operator(admin(), section(operator, "client"), str(operator["secret"]))
        done.append(f"master client {OPERATOR} {'recreated' if recreated else 'kept: it exists again'}")
    for change in reversed(entries(state.get("requirements"))):
        execution = section(change, "execution")
        admin().set_requirement(str(change["flow"]), execution, str(change["requirement"]))
        done.append(f"master {change['flow']}: {execution.get('displayName')} back to {change['requirement']}")
    helper = admin().client(SERVICE_ADMIN)
    if helper is not None:
        admin().delete_client(str(helper["id"]))
        done.append(f"master client {SERVICE_ADMIN} deleted")
    path.unlink()
    return done


def _load(path: Path) -> State:
    try:
        state: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"state file {path}: {exc}"
        raise StateError(msg) from exc
    if not isinstance(state, dict):
        msg = f"state file {path}: expected a JSON object"
        raise StateError(msg)
    return cast("State", state)
