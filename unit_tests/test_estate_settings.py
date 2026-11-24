"""Unit tests for applying an estate profile's Keycloak settings to a test environment and restoring them."""

import json
import stat

import pytest

from podiumd_tests import estate_settings
from podiumd_tests.auth.master_otp import OPERATOR
from podiumd_tests.auth.master_otp import SERVICE_ADMIN
from podiumd_tests.responses import UnexpectedStatusError

OPERATOR_CLIENT = {"id": "op", "clientId": OPERATOR, "serviceAccountsEnabled": True, "secret": "op-secret"}


@pytest.fixture
def master(fake_master, monkeypatch):
    """A FakeMaster with the operator client, behind every login of estate_settings; records the logins."""
    found = fake_master()
    found.clients["op"] = dict(OPERATOR_CLIENT)
    found.logins = []

    def login(kind):
        found.logins.append(kind)
        return found

    monkeypatch.setattr(estate_settings, "for_environment", lambda _env, _realm: login("password"))
    monkeypatch.setattr(estate_settings, "service_admin_login", lambda _env, secret: lambda: login(secret))
    return found


def profile(**master_settings):
    return {"estate": "x", "source": "manual", "keycloak_master": master_settings}


def test_apply_records_each_change_and_restore_undoes_them(master, env_factory, tmp_path):
    state = tmp_path / "state.json"
    env = env_factory()
    done = estate_settings.apply(env, profile(operator_client="absent", direct_grant_otp="required"), state)
    assert done == [
        f"master client {SERVICE_ADMIN} created",
        f"master client {OPERATOR} deleted",
        "master direct grant requires OTP of every user",
    ]
    recorded = json.loads(state.read_text(encoding="utf-8"))
    assert stat.S_IMODE(state.stat().st_mode) == 0o600
    assert recorded["operator"] == {"client": OPERATOR_CLIENT, "secret": "op-secret"}
    assert [(change["execution"]["id"], change["requirement"]) for change in recorded["requirements"]] == [
        ("s", "CONDITIONAL"),
        ("c", "REQUIRED"),
    ]
    assert list(master.clients) == [f"uuid-{SERVICE_ADMIN}"]
    assert master.logins[0] == "password"
    assert set(master.logins[1:]) == {f"secret-uuid-{SERVICE_ADMIN}"}

    restored = estate_settings.restore(env, state)
    assert restored[0] == f"master client {OPERATOR} recreated"
    assert restored[-1] == f"master client {SERVICE_ADMIN} deleted"
    assert master.clients == {f"uuid-{OPERATOR}": {**OPERATOR_CLIENT, "id": f"uuid-{OPERATOR}"}}
    assert master.set[2:] == [("direct grant", "c", "REQUIRED"), ("direct grant", "s", "CONDITIONAL")]
    assert not state.exists()


def test_apply_keeps_what_the_profile_does_not_know_or_already_matches(master, env_factory, tmp_path):
    master.clients.pop("op")
    state = tmp_path / "state.json"
    done = estate_settings.apply(env_factory(), profile(operator_client="absent"), state)
    assert done[1:] == [
        f"master client {OPERATOR} was absent already",
        "direct_grant_otp is unknown in the profile: kept",
    ]
    assert master.set == []
    assert estate_settings.restore(env_factory(), state) == [f"master client {SERVICE_ADMIN} deleted"]


def test_restore_after_a_failed_apply_logs_in_as_the_admin(master, env_factory, tmp_path, monkeypatch):
    def refused(_body):
        msg = "POST /clients: 409"
        raise UnexpectedStatusError(msg)

    monkeypatch.setattr(master, "create_client", refused)
    state = tmp_path / "state.json"
    with pytest.raises(UnexpectedStatusError):
        estate_settings.apply(env_factory(), profile(direct_grant_otp="required"), state)
    master.logins.clear()
    assert estate_settings.restore(env_factory(), state) == []
    assert set(master.logins) == {"password"}


@pytest.mark.parametrize(
    ("content", "message"),
    [(None, "No such file"), ("[]", "expected a JSON object"), ('{"env": "other"}', "is of other, not test-env")],
)
def test_restore_refuses_a_missing_unreadable_or_foreign_state_file(env_factory, tmp_path, content, message):
    state = tmp_path / "state.json"
    if content is not None:
        state.write_text(content, encoding="utf-8")
    with pytest.raises(estate_settings.StateError, match=message):
        estate_settings.restore(env_factory(), state)


@pytest.mark.parametrize(
    ("estate", "tiers", "refused"),
    [
        ("externals", ["smoke", "full"], "is in estate externals"),
        ("podiumd-infra", ["smoke"], "smoke-only"),
        ("podiumd-infra", ["smoke", "full"], None),
    ],
)
def test_only_test_environments_that_allow_writes_are_changed(profile_factory, estate, tiers, refused):
    reason = estate_settings.refusal(profile_factory(estate=estate, allowed_tiers=tiers))
    assert reason == refused or refused in reason
