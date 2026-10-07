"""Unit tests for the bootstrap framework and the credential store."""

import ast
import base64
import json

from dataclasses import dataclass
from dataclasses import field

from podiumd_tests import cli
from podiumd_tests.bootstrap import Context
from podiumd_tests.bootstrap import bootstrap
from podiumd_tests.bootstrap import check
from podiumd_tests.bootstrap import failed
from podiumd_tests.bootstrap import refusal
from podiumd_tests.bootstrap import unbootstrap
from podiumd_tests.bootstrap.steps import OPENKLANT_STORE_KEY
from podiumd_tests.bootstrap.steps import STEPS
from podiumd_tests.bootstrap.steps import ZGW_STORE_KEY
from podiumd_tests.bootstrap.steps import KeycloakUser
from podiumd_tests.bootstrap.steps import OpenKlantActor
from podiumd_tests.bootstrap.steps import SnippetStep
from podiumd_tests.bootstrap.steps import keycloak_password_key
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.credentials import env_var_name
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


def test_cli_refuses_bootstrap_on_smoke_only_profiles(tmp_path, capsys):
    (tmp_path / "gemeente.yaml").write_text(
        "estate: externals\nallowed_tiers: [smoke]\nkube: {context: c, namespace: podiumd}\nurls: {}\n",
        encoding="utf-8",
    )
    assert cli.main(["--envs-dir", str(tmp_path), "bootstrap", "--env", "gemeente"]) == cli.EXIT_NOT_ALLOWED
    assert "smoke-only" in capsys.readouterr().err


def snippet_params(code):
    """The params a snippet call was sent with: the string constant passed to _json.loads."""
    calls = [
        n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "loads"
    ]
    return json.loads(ast.literal_eval(calls[0].args[0]))


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


def keycloak_answers(*, user_exists, has_group):
    return {
        "POST /realms/master/protocol/openid-connect/token": (200, {"access_token": "admin-token"}),
        f"GET {REALM}/users": (200, [{"id": "u1"}] if user_exists else []),
        f"DELETE {REALM}/users/u1": (204, None),
        f"POST {REALM}/users": (201, None),
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
    assert len(password) == 40
    calls = [(r.method, r.url.removeprefix(KC).split("?")[0]) for r in sent]
    assert ("DELETE", f"{REALM}/users/u1") in calls  # a stale user is replaced
    assert ("POST", f"{REALM}/users/u1/role-mappings/clients/c1") in calls
    assert ctx.notes == ["not in realm: Coordinator, group beheerders"]


def test_keycloak_user_remove_deletes_only_an_existing_user(env_factory, fake_runner, profile_factory, fake_http):
    ctx = keycloak_ctx(env_factory, fake_runner, profile_factory)
    sent = fake_http(keycloak_answers(user_exists=False, has_group=True))
    assert KeycloakUser("kcc").remove(ctx) == (keycloak_password_key("kcc"),)
    assert all(r.method != "DELETE" for r in sent)


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


def test_snippet_notes_reach_the_outcome(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory, urls={"openarchiefbeheer": "https://oab.example.test"})
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openarchiefbeheer"}}]}))
    fake_runner.answers["exec -i deploy/openarchiefbeheer"] = snippet_answer(
        {"present": False, "notes": ["no group Reviewer"]}
    )
    step = SnippetStep(
        "oab-user", ("openarchiefbeheer",), "django_user", "pw", {"username": "u", "email": "e", "groups": ["Reviewer"]}
    )
    outcome = bootstrap(env, [step])[0]
    assert outcome.action == "created"
    assert outcome.detail == "pw; no group Reviewer"
