"""Unit tests for the bootstrap framework and the credential store."""

import ast
import base64
import json

from dataclasses import dataclass
from dataclasses import field

import pytest

from podiumd_tests import cli
from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
from podiumd_tests.bootstrap import Context
from podiumd_tests.bootstrap import bootstrap
from podiumd_tests.bootstrap import check
from podiumd_tests.bootstrap import failed
from podiumd_tests.bootstrap import refusal
from podiumd_tests.bootstrap import unbootstrap
from podiumd_tests.bootstrap.keycloak import KeycloakRoles
from podiumd_tests.bootstrap.keycloak import KeycloakUser
from podiumd_tests.bootstrap.keycloak import keycloak_password_key
from podiumd_tests.bootstrap.names import OBJECTEN_STORE_KEY
from podiumd_tests.bootstrap.names import OPENKLANT_OPENINWONER_STORE_KEY
from podiumd_tests.bootstrap.names import OPENKLANT_STORE_KEY
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.bootstrap.oidc_mock import KEYCLOAK_STORE_KEY
from podiumd_tests.bootstrap.oidc_mock import KeycloakOidcMock
from podiumd_tests.bootstrap.oidc_mock import oidc_params
from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.bootstrap.steps import STEPS
from podiumd_tests.bootstrap.steps import ItaMedewerker
from podiumd_tests.bootstrap.steps import OpenInwonerPartijen
from podiumd_tests.bootstrap.steps import OpenKlantActor
from podiumd_tests.bootstrap.steps import SnippetStep
from podiumd_tests.bootstrap.steps import openformulieren_params
from podiumd_tests.bootstrap.steps import openinwoner_openklant_params
from podiumd_tests.bootstrap.steps import productaanvraag_zaaktypen
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.credentials import env_var_name
from podiumd_tests.json_data import section
from podiumd_tests.kube import Kube
from podiumd_tests.kube import KubeError


@dataclass
class FakeStep:
    """A step that records what was done to it."""

    name: str = "fake"
    requires: tuple[str, ...] = ()
    wiring: bool = False
    present: bool = False
    log: list[str] = field(default_factory=list)

    def is_present(self, _ctx):
        return self.present

    def apply(self, _ctx):
        self.log.append("apply")
        self.present = True
        return {f"{self.name}_token": "t0ken-value"}

    def remove(self, _ctx):
        self.log.append("remove")
        self.present = False
        return (f"{self.name}_token",)


def stored(values):
    data = {k: base64.b64encode(v.encode()).decode() for k, v in values.items()}
    return json.dumps({"kind": "Secret", "data": data})


def cluster_env(env_factory, fake_runner, profile_factory, environ=None, **profile):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openzaak"}}]}))
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (0, "")
    fake_runner.answers["apply -f -"] = (0, "secret/podiumd-tests-credentials configured")
    fake_runner.answers["delete secret podiumd-tests-credentials"] = (0, "")
    return env_factory(profile_factory(**profile), environ)


def test_smoke_only_profiles_are_refused(profile_factory):
    assert "smoke-only" in str(refusal(profile_factory(allowed_tiers=["smoke"])))
    assert refusal(profile_factory(allowed_tiers=["smoke", "full"])) is None


def test_bootstrap_applies_missing_steps_and_stores_credentials(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    missing, present = FakeStep("a"), FakeStep("b", present=True)
    outcomes = bootstrap(env, [missing, present])
    assert [(o.step, o.action) for o in outcomes] == [("a", "created"), ("b", "present")]
    assert missing.log == ["apply"]
    assert present.log == []
    assert "t0ken-value" in fake_runner.stdins[-1]
    assert "t0ken-value" not in " ".join(" ".join(c) for c in fake_runner.calls)


def test_rotate_reapplies_present_steps(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    step = FakeStep(present=True)
    assert [o.action for o in bootstrap(env, [step], rotate=True)] == ["created"]


def test_steps_without_their_capability_are_skipped(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    step = FakeStep(requires=("zac",))
    outcomes = bootstrap(env, [step])
    assert outcomes[0].action == "skipped"
    assert "zac" in outcomes[0].detail
    assert step.log == []


def test_unbootstrap_removes_in_reverse_order(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    first, second = FakeStep("first", present=True), FakeStep("second")
    outcomes = unbootstrap(env, [first, second])
    assert [(o.step, o.action) for o in outcomes] == [("second", "absent"), ("first", "removed")]


def test_check_changes_nothing(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    step = FakeStep()
    assert [o.action for o in check(env, [step])] == ["missing"]
    assert step.log == []


@dataclass
class OptInStep(FakeStep):
    """A FakeStep behind a profile setting that is off; like FakeStep, it reports present."""

    present: bool = True

    def not_allowed(self, _ctx):
        return "profile setting fake_opt_in is off"


def test_check_and_bootstrap_skip_a_step_the_profile_does_not_allow(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    step = OptInStep()
    for outcome in (check(env, [step])[0], bootstrap(env, [step])[0]):
        assert (outcome.action, outcome.detail) == ("skipped", "profile setting fake_opt_in is off")
    assert step.log == []


def test_unbootstrap_still_removes_a_step_the_profile_no_longer_allows(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    step = OptInStep()
    assert [o.action for o in unbootstrap(env, [step])] == ["removed"]
    assert step.log == ["remove"]


def test_store_merges_and_removes_keys(fake_runner):
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (0, stored({"a": "1", "b": "2"}))
    fake_runner.answers["apply -f -"] = (0, "")
    fake_runner.answers["delete secret"] = (0, "")
    store = CredentialStore(Kube("ctx", "ns", fake_runner))
    assert store.read() == {"a": "1", "b": "2"}
    store.write({"c": "3"})
    assert json.loads(fake_runner.stdins[-1])["stringData"] == {"a": "1", "b": "2", "c": "3"}
    store.remove("a")
    assert json.loads(fake_runner.stdins[-1])["stringData"] == {"b": "2"}


def test_resolver_falls_back_to_bootstrap_credentials(env_factory, fake_runner):
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (0, stored({"zgw_secret": "boot"}))
    creds = env_factory().credentials
    assert creds.configured("zgw_secret")
    assert creds.get("zgw_secret") == "boot"
    assert not creds.configured("other")


def test_resolver_sees_what_bootstrap_stored_after_forget(env_factory, fake_runner):
    key = "get secret podiumd-tests-credentials --ignore-not-found"
    fake_runner.answers[key] = (0, "")
    creds = env_factory().credentials
    assert not creds.configured("admin_password")
    fake_runner.answers[key] = (0, stored({"admin_password": "new"}))
    creds.forget("admin_password")
    assert creds.get("admin_password") == "new"


def test_cli_refuses_bootstrap_on_smoke_only_profiles(tmp_path, capsys):
    (tmp_path / "gemeente.yaml").write_text(
        "estate: externals\nallowed_tiers: [smoke]\nkube: {context: c, namespace: podiumd}\nurls: {}\n",
        encoding="utf-8",
    )
    assert cli.main(["--envs-dir", str(tmp_path), "bootstrap", "--env", "gemeente"]) == cli.EXIT_NOT_ALLOWED
    assert "smoke-only" in capsys.readouterr().err


def snippet_params(code):
    """The params the first snippet was sent with, from the [name, source, params] list passed to _json.loads."""
    calls = [
        n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "loads"
    ]
    return json.loads(ast.literal_eval(calls[0].args[0]))[0][2]


def snippet_answer(value):
    return (0, f"Django chatter\nPTEST_VALUE={json.dumps(value)}\n")


def test_snippet_step_sends_its_secret_over_stdin_only(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    ctx = Context(env, CredentialStore(env.kube))
    step = next(s for s in STEPS if s.name == "openzaak-client")
    fake_runner.answers["exec -i deploy/openzaak"] = snippet_answer({"present": True})
    assert not step.is_present(ctx)  # the secret is not in the credentials Secret yet
    values = step.apply(ctx)
    assert set(values) == {ZGW_STORE_KEY}
    sent = snippet_params(fake_runner.stdins[-1])
    assert sent["action"] == "apply"
    assert sent["secret"] == values[ZGW_STORE_KEY]
    assert sent["catalogus"]["domein"] == "PTEST"
    assert values[ZGW_STORE_KEY] not in " ".join(" ".join(c) for c in fake_runner.calls)
    assert step.remove(ctx) == (ZGW_STORE_KEY,)


def test_steps_run_in_the_components_deployment(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "notificaties"}}]}))
    assert env.deployment_for("opennotificaties") == "notificaties"


KC = "https://kc.example.test"
REALM = "/admin/realms/podiumd"


def keycloak_answers(*, user_exists, has_group) -> dict[str, tuple[int, object]]:
    return {
        "POST /realms/master/protocol/openid-connect/token": (200, {"access_token": "admin-token"}),
        f"GET {REALM}": (200, {"passwordPolicy": "length(50) and digits(3)"}),
        f"GET {REALM}/users": (200, [{"id": "u1"}] if user_exists else []),
        f"DELETE {REALM}/users/u1": (204, None),
        f"POST {REALM}/users": (201, None),
        f"PUT {REALM}/users/u1": (204, None),
        f"PUT {REALM}/users/u1/reset-password": (204, None),
        f"GET {REALM}/roles": (200, [{"id": "r1", "name": "Behandelaar"}, {"id": "r2", "name": "other"}]),
        f"POST {REALM}/users/u1/role-mappings/realm": (204, None),
        f"GET {REALM}/clients": (200, [{"id": "c1"}]),
        f"GET {REALM}/clients/c1/roles": (200, [{"name": "administrator"}]),
        f"POST {REALM}/users/u1/role-mappings/clients/c1": (204, None),
        f"GET {REALM}/groups": (200, [{"id": "g1", "name": "beheerders"}] if has_group else []),
        f"PUT {REALM}/users/u1/groups/g1": (204, None),
    }


def keycloak_ctx(env_factory, fake_runner, profile_factory):
    admin = {env_var_name("keycloak_admin_username"): "admin", env_var_name("keycloak_admin_password"): "pw"}
    env = cluster_env(env_factory, fake_runner, profile_factory, admin, urls={"keycloak": KC})
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "keycloak"}}]}))
    return Context(env, CredentialStore(env.kube))


def test_keycloak_user_gets_existing_roles_and_reports_missing_ones(
    env_factory, fake_runner, profile_factory, fake_http
):
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    sent = fake_http(keycloak_answers(user_exists=True, has_group=False))
    user = KeycloakUser(
        "admin",
        realm_roles=("Behandelaar", "Coordinator"),
        client_roles=(("pabc", "administrator"),),
        groups=("beheerders",),
    )
    values = user.apply(ctx)
    password = values[keycloak_password_key("admin")]
    # Meets the realm's passwordPolicy.
    assert (len(password), sum(c.isdigit() for c in password) >= 3) == (50, True)
    calls = [(r.method, r.url.removeprefix(KC).split("?")[0]) for r in sent]
    # An existing user is updated in place: its id is the sub apps made their accounts from.
    assert ("DELETE", f"{REALM}/users/u1") not in calls
    assert ("PUT", f"{REALM}/users/u1/reset-password") in calls
    assert ("POST", f"{REALM}/users/u1/role-mappings/clients/c1") in calls
    assert ctx.notes == ["not in realm: Coordinator, group beheerders"]


def test_keycloak_user_fails_when_the_realm_has_none_of_its_roles(env_factory, fake_runner, profile_factory, fake_http):
    # A realm imported with skipRoles/skipGroups has no roles, client roles or groups: the user gets nothing.
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    answers = keycloak_answers(user_exists=True, has_group=False)
    answers[f"GET {REALM}/roles"] = (200, [])
    answers[f"GET {REALM}/clients/c1/roles"] = (200, [])
    fake_http(answers)
    user = KeycloakUser(
        "admin", realm_roles=("Behandelaar",), client_roles=(("pabc", "administrator"),), groups=("beheerders",)
    )
    with pytest.raises(ValueError, match="skipRoles/skipGroups"):
        user.apply(ctx)


@pytest.mark.parametrize(("mapped", "present"), [([], False), ([{"name": "Behandelaar"}], True)])
def test_keycloak_user_is_present_only_with_the_realms_wanted_roles(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    env_factory, fake_runner, profile_factory, fake_http, mapped, present
):
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    secret = stored({keycloak_password_key("admin"): "pw"})
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (0, secret)
    answers = keycloak_answers(user_exists=True, has_group=True)
    answers[f"GET {REALM}/users/u1/role-mappings/realm"] = (200, mapped)
    answers[f"GET {REALM}/users/u1/groups"] = (200, [{"id": "g1", "name": "beheerders"}])
    fake_http(answers)
    # Coordinator and group "missing" are not in the realm, so they cannot be wanted.
    user = KeycloakUser("admin", realm_roles=("Behandelaar", "Coordinator"), groups=("beheerders", "missing"))
    assert user.is_present(ctx) is present


@pytest.mark.parametrize(("mapped", "present"), [([], False), ([{"name": "administrator"}], True)])
def test_keycloak_user_is_present_only_with_the_realms_wanted_client_roles(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    env_factory, fake_runner, profile_factory, fake_http, mapped, present
):
    # A client role the realm gets later (a redeploy that imports roles) makes the step apply again.
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    secret = stored({keycloak_password_key("admin"): "pw"})
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (0, secret)
    answers = keycloak_answers(user_exists=True, has_group=True)
    answers[f"GET {REALM}/users/u1/role-mappings/realm"] = (200, [])
    answers[f"GET {REALM}/users/u1/groups"] = (200, [])
    answers[f"GET {REALM}/users/u1/role-mappings/clients/c1"] = (200, mapped)
    fake_http(answers)
    user = KeycloakUser("admin", client_roles=(("pabc", "administrator"), ("pabc", "missing")))
    assert user.is_present(ctx) is present


def test_keycloak_user_remove_deletes_only_an_existing_user(env_factory, fake_runner, profile_factory, fake_http):
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    sent = fake_http(keycloak_answers(user_exists=False, has_group=True))
    assert KeycloakUser("kcc").remove(ctx) == (keycloak_password_key("kcc"),)
    assert all(r.method != "DELETE" for r in sent)


@pytest.mark.parametrize(
    ("stored_keys", "attributes"),
    [((), {}), ((keycloak_password_key("kcc"),), {"samaccountname": ["someone-else"]})],
    ids=["no-password-stored", "other-attribute"],
)
def test_keycloak_user_is_absent_without_its_password_or_attributes(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    env_factory, fake_runner, profile_factory, fake_http, stored_keys, attributes
):
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    secret = stored(dict.fromkeys(stored_keys, "pw"))
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (0, secret)
    answers = keycloak_answers(user_exists=True, has_group=True)
    answers[f"GET {REALM}/users"] = (200, [{"id": "u1", "attributes": attributes}])
    fake_http(answers)
    assert KCC.is_present(ctx) is False


def test_keycloak_user_joins_existing_groups_and_reports_missing_client_roles(
    env_factory, fake_runner, profile_factory, fake_http
):
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    answers = keycloak_answers(user_exists=True, has_group=True)
    answers[f"GET {REALM}/clients"] = (200, [])
    sent = fake_http(answers)
    KeycloakUser("admin", client_roles=(("pabc", "administrator"),), groups=("beheerders",)).apply(ctx)
    assert ("PUT", f"{REALM}/users/u1/groups/g1") in [(r.method, r.url.removeprefix(KC)) for r in sent]
    assert ctx.notes == ["not in realm: pabc:administrator"]


def test_keycloak_user_remove_deletes_an_existing_user(env_factory, fake_runner, profile_factory, fake_http):
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    sent = fake_http(keycloak_answers(user_exists=True, has_group=True))
    KeycloakUser("kcc").remove(ctx)
    assert [r.url.removeprefix(KC) for r in sent if r.method == "DELETE"] == [f"{REALM}/users/u1"]


ROLE_USERS = (
    KeycloakUser("admin", realm_roles=("Behandelaar", "Coordinator"), client_roles=(("pabc", "administrator"),)),
    KeycloakUser("kcc", client_roles=(("pabc", "missing"),)),
)


def test_keycloak_roles_creates_the_missing_roles_and_records_them(
    env_factory, fake_runner, profile_factory, fake_http
):
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    answers = keycloak_answers(user_exists=True, has_group=True)
    answers[f"POST {REALM}/roles"] = (201, None)
    answers[f"POST {REALM}/clients/c1/roles"] = (201, None)
    sent = fake_http(answers)
    step = KeycloakRoles(ROLE_USERS)
    assert step.is_present(ctx) is False
    values = step.apply(ctx)
    assert json.loads(values[step.store_key]) == ["Coordinator", "pabc:missing"]
    created = [(r.url.removeprefix(KC), json.loads(r.body)) for r in sent if r.method == "POST" and "/roles" in r.url]
    marker = {"attributes": {"ptest-bootstrap": ["keycloak-roles"]}}
    assert created == [
        (f"{REALM}/roles", {"name": "Coordinator", **marker}),
        (f"{REALM}/clients/c1/roles", {"name": "missing", **marker}),
    ]


def test_keycloak_roles_remove_deletes_only_recorded_roles_it_still_owns(
    env_factory, fake_runner, profile_factory, fake_http
):
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    step = KeycloakRoles(ROLE_USERS)
    # Behandelaar was taken over by a realm import, which dropped the attribute.
    record = json.dumps(["Coordinator", "Behandelaar", "pabc:missing", "gone:role"])
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (
        0,
        stored({step.store_key: record}),
    )
    answers = keycloak_answers(user_exists=True, has_group=True)
    answers[f"GET {REALM}/clients"] = (200, [])
    answers[f"GET {REALM}/roles"] = (
        200,
        [{"name": "Coordinator", "attributes": {"ptest-bootstrap": ["keycloak-roles"]}}, {"name": "Behandelaar"}],
    )
    answers[f"DELETE {REALM}/roles/Coordinator"] = (204, None)
    sent = fake_http(answers)
    assert step.remove(ctx) == (step.store_key,)
    # The clients are gone, so their roles went with them.
    assert [r.url.removeprefix(KC) for r in sent if r.method == "DELETE"] == [f"{REALM}/roles/Coordinator"]


def test_step_names():
    assert [KCC.name, ItaMedewerker(KCC).name, OpenKlantActor("kcc").name] == [
        "keycloak-user-kcc",
        "objecten-medewerker-kcc",
        "openklant-actor-kcc",
    ]


OBJ = "https://obj.example.test"


def objecten_ctx(env_factory, fake_runner, profile_factory, values):
    env = cluster_env(env_factory, fake_runner, profile_factory, urls={"objecten": OBJ})
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (0, stored(values))
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "objecten"}}]}))
    fake_runner.answers["exec -i deploy/objecten"] = snippet_answer({"uuid": "ot1"})
    return Context(env, CredentialStore(env.kube))


def test_ita_medewerker_recreates_the_users_medewerker_object(env_factory, fake_runner, profile_factory, fake_http):
    ctx = objecten_ctx(env_factory, fake_runner, profile_factory, {OBJECTEN_STORE_KEY: "tok"})
    sent = fake_http(
        {
            "GET /api/v2/objects": (200, [{"url": f"{OBJ}/api/v2/objects/o1"}]),
            "DELETE /api/v2/objects/o1": (204, None),
            "POST /api/v2/objects": (201, {"url": f"{OBJ}/api/v2/objects/o2"}),
        }
    )
    step = ItaMedewerker(KCC)
    assert step.is_present(ctx)
    assert step.apply(ctx) == {}
    assert [r.method for r in sent] == ["GET", "GET", "DELETE", "POST"]
    assert "identificatie__exact__ptest-bootstrap-kcc" in sent[0].url
    body = json.loads(sent[-1].body)
    assert body["type"] == f"{OBJ}/api/v2/objecttypes/ot1"
    assert body["record"]["data"]["groepen"] == [{"groepsnaam": "ptest-bootstrap-groep"}]


def test_steps_without_their_token_stored_find_and_remove_nothing(env_factory, fake_runner, profile_factory, fake_http):
    ctx = objecten_ctx(env_factory, fake_runner, profile_factory, {})
    sent = fake_http()
    assert not ItaMedewerker(KCC).is_present(ctx)
    assert not OpenKlantActor("kcc").is_present(ctx)
    for step in (ItaMedewerker(KCC), OpenKlantActor("kcc"), OpenInwonerPartijen()):
        assert step.remove(ctx) == ()
    assert OpenInwonerPartijen().is_present(ctx)
    assert OpenInwonerPartijen().apply(ctx) == {}
    assert sent == []


def test_a_step_without_store_key_stores_nothing(env_factory, fake_runner, profile_factory):
    ctx = objecten_ctx(env_factory, fake_runner, profile_factory, {})
    fake_runner.answers["exec -i deploy/objecten"] = snippet_answer({})
    assert SnippetStep("x", ("objecten",), "token_auth", None).apply(ctx) == {}
    assert snippet_params(fake_runner.stdins[-1]) == {"action": "apply"}


def test_openformulieren_params_prefer_the_internal_open_zaak_url(env_factory, fake_runner, profile_factory):
    settings = {"openzaak_internal_url": "http://openzaak.podiumd.svc.cluster.local:8000"}
    env = cluster_env(env_factory, fake_runner, profile_factory, settings=settings)
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (0, stored({ZGW_STORE_KEY: "s"}))
    assert openformulieren_params(Context(env, CredentialStore(env.kube))) == {
        "secret": "s",
        "openzaak_url": "http://openzaak.podiumd.svc.cluster.local:8000",
    }


@pytest.mark.parametrize("actoren", [[{"uuid": "a1"}], []])
def test_openinwoner_openklant_params_send_questions_to_the_kcc_actor(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    env_factory, fake_runner, profile_factory, fake_http, actoren
):
    env = cluster_env(env_factory, fake_runner, profile_factory, urls={"openklant": OK})
    values = {OPENKLANT_STORE_KEY: "tok", OPENKLANT_OPENINWONER_STORE_KEY: "oi-tok"}
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (0, stored(values))
    fake_http({f"GET {ACTOREN}": (200, actoren)})
    ctx = Context(env, CredentialStore(env.kube))
    if not actoren:
        with pytest.raises(LookupError, match="run bootstrap step openklant-actor-kcc first"):
            openinwoner_openklant_params(ctx)
        return
    params = openinwoner_openklant_params(ctx)
    assert (params["api_root"], params["token"]) == (f"{OK}/klantinteracties/api/v1/", "oi-tok")
    assert section(params, "config")["mijn_vragen_actor"] == "a1"


def test_wiring_steps_skip_unless_the_profile_allows_wiring(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory, estate="externals", allowed_tiers=["smoke", "full"])
    step = FakeStep(wiring=True)
    outcome = bootstrap(env, [step])[0]
    assert (outcome.action, step.log) == ("skipped", [])
    assert "bootstrap.wiring" in outcome.detail


def test_record_mode_hands_the_stored_record_to_apply_and_remove(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    earlier = {"created": ["partijen"], "filters": {}}
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (
        0,
        stored({"rec": json.dumps(earlier)}),
    )
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "opennotificaties"}}]}))
    step = SnippetStep("kanalen", ("opennotificaties",), "kanalen", "rec", {"kanalen": {}}, record=True, wiring=True)
    ctx = Context(env, CredentialStore(env.kube))
    extended = {"created": ["partijen", "statussen"], "filters": {"zaken": ["zaaktype"]}}
    fake_runner.answers["exec -i deploy/opennotificaties"] = snippet_answer({"present": True, "record": extended})
    values = step.apply(ctx)
    assert snippet_params(fake_runner.stdins[-1])["record"] == earlier
    assert json.loads(values["rec"]) == extended
    step.remove(ctx)
    assert snippet_params(fake_runner.stdins[-1]) == {"kanalen": {}, "action": "remove", "record": earlier}


def test_a_failing_step_does_not_stop_the_others(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)

    class Broken(FakeStep):
        def remove(self, _ctx):
            raise KubeError(["kubectl", "exec"], "DisallowedHost: example.com")

    later = FakeStep("later", present=True)
    outcomes = unbootstrap(env, [later, Broken("broken", present=True)])
    assert [(o.step, o.action) for o in outcomes] == [("broken", "failed"), ("later", "removed")]
    assert "DisallowedHost" in outcomes[0].detail
    assert failed(outcomes)


OK = "https://ok.example.test"
ACTOREN = "/klantinteracties/api/v1/actoren"


def test_openklant_actor_recreates_the_users_actor(env_factory, fake_runner, profile_factory, fake_http):
    env = cluster_env(env_factory, fake_runner, profile_factory, urls={"openklant": OK})
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (
        0,
        stored({OPENKLANT_STORE_KEY: "tok"}),
    )
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openklant"}}]}))
    sent = fake_http(
        {
            f"GET {ACTOREN}": (200, {"results": [{"uuid": "a1"}]}),
            f"DELETE {ACTOREN}/a1": (204, None),
            f"POST {ACTOREN}": (201, {"uuid": "a2"}),
        }
    )
    step = OpenKlantActor("kcc")
    assert step.apply(Context(env, CredentialStore(env.kube))) == {}
    assert [(r.method, r.url.removeprefix(OK).split("?")[0]) for r in sent] == [
        ("GET", ACTOREN),
        ("DELETE", f"{ACTOREN}/a1"),
        ("POST", ACTOREN),
    ]
    assert sent[0].url.endswith("actoridentificatorObjectId=ptest-bootstrap-kcc%40example.invalid")
    assert sent[-1].headers["Authorization"] == "Token tok"


def test_openinwoner_partijen_remove_deletes_the_partijen_of_the_test_identities(
    env_factory, fake_runner, profile_factory, fake_http
):
    env = cluster_env(env_factory, fake_runner, profile_factory, urls={"openklant": OK})
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (
        0,
        stored({OPENKLANT_STORE_KEY: "tok"}),
    )
    api = "/klantinteracties/api/v1"
    identificator = {
        "url": f"{OK}{api}/partij-identificatoren/i1",
        "identificeerdePartij": {"url": f"{OK}{api}/partijen/p1"},
    }
    kvk = {"url": f"{OK}{api}/partij-identificatoren/i1", "subIdentificatorVan": None}
    vestiging = {"url": f"{OK}{api}/partij-identificatoren/i2", "subIdentificatorVan": {"url": kvk["url"]}}
    sent = fake_http(
        {
            f"GET {api}/partij-identificatoren": (200, {"results": [identificator], "next": None}),
            f"GET {api}/digitaleadressen": (200, {"results": [], "next": None}),
            f"GET {api}/partijen/p1": (
                200,
                {"partijIdentificatoren": [{"url": kvk["url"]}, {"url": vestiging["url"]}]},
            ),
            f"GET {api}/partij-identificatoren/i1": (200, kvk),
            f"GET {api}/partij-identificatoren/i2": (200, vestiging),
            f"DELETE {api}/partij-identificatoren/i1": (204, None),
            f"DELETE {api}/partij-identificatoren/i2": (204, None),
            f"DELETE {api}/partijen/p1": (204, None),
        }
    )
    assert OpenInwonerPartijen().remove(Context(env, CredentialStore(env.kube))) == ()
    searched = [r.url.split("ObjectId=")[1] for r in sent if "partijIdentificatorObjectId" in r.url]
    assert searched == ["000037178601", "999990019", "999993653", "68750110"]
    # The vestiging's sub-identificator goes before the kvk_nummer it refers to.
    assert [r.url.removeprefix(OK + api) for r in sent if r.method == "DELETE"] == [
        "/partij-identificatoren/i2",
        "/partij-identificatoren/i1",
        "/partijen/p1",
    ] * 4


def test_snippet_notes_reach_the_outcome(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory, urls={"objecten": "https://objecten.example.test"})
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "objecten"}}]}))
    fake_runner.answers["exec -i deploy/objecten"] = snippet_answer({"present": False, "notes": ["no objecttype X"]})
    step = SnippetStep("objecten-token", ("objecten",), "token_auth", "tok", {"modules": ("m",), "object_types": ["X"]})
    outcome = bootstrap(env, [step])[0]
    assert outcome.action == "created"
    assert outcome.detail == "tok; no objecttype X"


def test_productaanvraag_client_gets_rights_only_with_the_profile_setting(env_factory, profile_factory):
    without = Context(env_factory(profile_factory()), CredentialStore(Kube("ctx", "podiumd")))
    assert productaanvraag_zaaktypen(without) == {}
    with_setting = Context(
        env_factory(profile_factory(settings={"productaanvraag_zaaktype": "zt-1"})),
        CredentialStore(Kube("ctx", "podiumd")),
    )
    zaaktypen = section(productaanvraag_zaaktypen(with_setting), "zaaktypen")
    assert zaaktypen["identificaties"] == ["zt-1"]
    assert zaaktypen["scopes"] == ["zaken.lezen", "zaken.verwijderen"]
    assert zaaktypen["base_url"] == "https://openzaak.example.test"


OI = "https://oi.example.test"


def oidc_mock_answers(eherkenning_mappers):
    return {
        "POST /realms/master/protocol/openid-connect/token": (200, {"access_token": "admin-token"}),
        f"GET {REALM}/client-scopes": (200, [{"id": "s-bsn", "name": "bsn"}, {"id": "s-eh", "name": "eherkenning"}]),
        f"GET {REALM}/client-scopes/s-bsn/protocol-mappers/models": (200, [{"id": "m0", "name": "bsn-claim"}]),
        f"GET {REALM}/client-scopes/s-eh/protocol-mappers/models": (200, eherkenning_mappers),
        f"POST {REALM}/client-scopes/s-eh/protocol-mappers/models": (201, None),
        f"DELETE {REALM}/client-scopes/s-eh/protocol-mappers/models/m2": (204, None),
        f"GET {REALM}/clients": (200, [{"id": "c1", "clientId": "openinwoner", "redirectUris": ["https://x/*"]}]),
        f"GET {REALM}/clients/c1/default-client-scopes": (200, []),
        f"GET {REALM}/clients/c1/optional-client-scopes": (200, []),
        f"PUT {REALM}/clients/c1/optional-client-scopes/s-bsn": (204, None),
        f"PUT {REALM}/clients/c1/optional-client-scopes/s-eh": (204, None),
        f"DELETE {REALM}/clients/c1/optional-client-scopes/s-bsn": (204, None),
        f"DELETE {REALM}/clients/c1/optional-client-scopes/s-eh": (204, None),
        f"PUT {REALM}/clients/c1": (204, None),
    }


def oidc_mock_ctx(env_factory, fake_runner, profile_factory):
    admin = {env_var_name("keycloak_admin_username"): "admin", env_var_name("keycloak_admin_password"): "pw"}
    env = cluster_env(env_factory, fake_runner, profile_factory, admin, urls={"keycloak": KC, "openinwoner": OI})
    deployments = [{"metadata": {"name": "keycloak"}}, {"metadata": {"name": "openinwoner"}}]
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": deployments}))
    return Context(env, CredentialStore(env.kube))


def test_oidc_mock_records_only_what_it_adds(env_factory, fake_runner, profile_factory, fake_http):
    ctx = oidc_mock_ctx(env_factory, fake_runner, profile_factory)
    sent = fake_http(oidc_mock_answers([{"id": "m1", "name": "kvk-claim"}]))
    record = json.loads(KeycloakOidcMock().apply(ctx)[KEYCLOAK_STORE_KEY])
    assert record == {
        "scopes": [],
        "mappers": {"eherkenning": ["vestigingsnr-claim", "namequalifier-claim"]},
        "attached": {"openinwoner": ["bsn", "eherkenning"]},
        "redirects": {"openinwoner": f"{OI}/*"},
    }
    assert sum(r.method == "POST" and "protocol-mappers" in r.url for r in sent) == 2


def test_oidc_mock_remove_undoes_the_record(env_factory, fake_runner, profile_factory, fake_http):
    ctx = oidc_mock_ctx(env_factory, fake_runner, profile_factory)
    record = {
        "mappers": {"eherkenning": ["vestigingsnr-claim"]},
        "attached": {"openinwoner": ["bsn"]},
        "redirects": {"openinwoner": "https://x/*"},
    }
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (
        0,
        stored({KEYCLOAK_STORE_KEY: json.dumps(record)}),
    )
    sent = fake_http(oidc_mock_answers([{"id": "m2", "name": "vestigingsnr-claim"}]))
    assert KeycloakOidcMock().remove(ctx) == (KEYCLOAK_STORE_KEY,)
    deletes = sorted(r.url.removeprefix(KC + REALM) for r in sent if r.method == "DELETE")
    assert deletes == ["/client-scopes/s-eh/protocol-mappers/models/m2", "/clients/c1/optional-client-scopes/s-bsn"]
    assert any(r.method == "PUT" and r.url.endswith("/clients/c1") for r in sent)


EHERKENNING_MAPPERS = [
    {"id": f"m{i}", "name": n} for i, n in enumerate(("kvk-claim", "vestigingsnr-claim", "namequalifier-claim"))
]
CLIENT_SCOPES = [{"name": "bsn"}, {"name": "eherkenning"}]


@pytest.mark.parametrize(
    ("changes", "present"),
    [
        ({}, True),
        ({f"GET {REALM}/client-scopes/s-eh/protocol-mappers/models": (200, EHERKENNING_MAPPERS[:1])}, False),
        ({f"GET {REALM}/clients/c1/optional-client-scopes": (200, CLIENT_SCOPES[:1])}, False),
        ({f"GET {REALM}/clients": (200, [{"id": "c1", "clientId": "openinwoner", "redirectUris": []}])}, False),
    ],
    ids=["complete", "mapper-missing", "scope-not-attached", "redirect-missing"],
)
def test_oidc_mock_is_present(env_factory, fake_runner, profile_factory, fake_http, changes, present):
    ctx = oidc_mock_ctx(env_factory, fake_runner, profile_factory)
    answers = oidc_mock_answers(EHERKENNING_MAPPERS)
    answers[f"GET {REALM}/clients"] = (200, [{"id": "c1", "clientId": "openinwoner", "redirectUris": [f"{OI}/*"]}])
    answers[f"GET {REALM}/clients/c1/optional-client-scopes"] = (200, CLIENT_SCOPES)
    fake_http(answers | changes)
    assert KeycloakOidcMock().is_present(ctx) is present


def test_oidc_mock_creates_missing_scopes_and_notes_a_missing_client(
    env_factory, fake_runner, profile_factory, fake_http, monkeypatch
):
    ctx = oidc_mock_ctx(env_factory, fake_runner, profile_factory)
    answers = oidc_mock_answers(EHERKENNING_MAPPERS)
    answers[f"GET {REALM}/client-scopes"] = (200, [{"id": "s-bsn", "name": "bsn"}])
    answers[f"GET {REALM}/clients"] = (200, [])
    fake_http(answers)
    created = []
    monkeypatch.setattr(KeycloakAdmin, "create_client_scope", lambda _self, scope: created.append(scope) or "s-eh")
    record = json.loads(KeycloakOidcMock().apply(ctx)[KEYCLOAK_STORE_KEY])
    assert [c["name"] for c in created] == ["eherkenning"]
    assert (record["scopes"], record["mappers"]) == (["eherkenning"], {})
    assert ctx.notes == ["realm podiumd has no client openinwoner"]


def test_oidc_mock_remove_deletes_created_scopes_and_skips_a_deleted_client(
    env_factory, fake_runner, profile_factory, fake_http
):
    ctx = oidc_mock_ctx(env_factory, fake_runner, profile_factory)
    record = {"scopes": ["bsn"], "attached": {"openinwoner": ["bsn"]}}
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (
        0,
        stored({KEYCLOAK_STORE_KEY: json.dumps(record)}),
    )
    answers = oidc_mock_answers(EHERKENNING_MAPPERS)
    answers[f"GET {REALM}/clients"] = (200, [])
    answers[f"DELETE {REALM}/client-scopes/s-bsn"] = (204, None)
    sent = fake_http(answers)
    KeycloakOidcMock().remove(ctx)
    assert [r.url.removeprefix(KC + REALM) for r in sent if r.method == "DELETE"] == ["/client-scopes/s-bsn"]


@pytest.mark.parametrize("clients", [[{"id": "c1"}], []])
def test_oidc_params_carry_the_client_secret(env_factory, fake_runner, profile_factory, fake_http, clients):
    ctx = oidc_mock_ctx(env_factory, fake_runner, profile_factory)
    answers = oidc_mock_answers(EHERKENNING_MAPPERS)
    answers[f"GET {REALM}/clients"] = (200, clients)
    answers[f"GET {REALM}/clients/c1/client-secret"] = (200, {"value": "s3cret"})
    fake_http(answers)
    if not clients:
        with pytest.raises(LookupError, match="realm podiumd has no client openinwoner"):
            oidc_params("openinwoner")(ctx)
        return
    assert oidc_params("openinwoner")(ctx) == {
        "endpoint": f"{KC}/realms/podiumd/protocol/openid-connect",
        "client_id": "openinwoner",
        "secret": "s3cret",
    }


def test_an_opt_in_step_does_nothing_unless_the_profile_allows_it(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    ctx = Context(env, CredentialStore(env.kube))
    step = next(s for s in STEPS if s.name == "openformulieren-payment-wait")
    assert step.is_present(ctx)
    assert step.apply(ctx) == {}
    assert ctx.notes == ["not allowed: profile setting of_wait_for_payment is off"]
    assert not any("exec" in c for c in fake_runner.calls)
