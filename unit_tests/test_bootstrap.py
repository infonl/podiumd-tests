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
from podiumd_tests.bootstrap import refusal
from podiumd_tests.bootstrap import unbootstrap
from podiumd_tests.bootstrap.steps import STEPS
from podiumd_tests.bootstrap.steps import ZGW_STORE_KEY
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.kube import Kube


@dataclass
class FakeStep:
    """A step that records what was done to it."""

    name: str = "fake"
    requires: tuple[str, ...] = ()
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


def cluster_env(env_factory, fake_runner, profile_factory, **profile):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openzaak"}}]}))
    fake_runner.answers["get secret podiumd-tests-credentials --ignore-not-found"] = (0, "")
    fake_runner.answers["apply -f -"] = (0, "secret/podiumd-tests-credentials configured")
    fake_runner.answers["delete secret podiumd-tests-credentials"] = (0, "")
    return env_factory(profile_factory(**profile))


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
    step = STEPS[0]
    fake_runner.answers["exec -i deploy/openzaak"] = snippet_answer({"present": True})
    assert not step.is_present(ctx)  # the secret is not in the credentials Secret yet
    values = step.apply(ctx)
    assert set(values) == {ZGW_STORE_KEY}
    sent = snippet_params(fake_runner.stdins[-1])
    assert sent["action"] == "apply"
    assert sent["secret"] == values[ZGW_STORE_KEY]
    assert sent["domein"] == "PTEST"
    assert values[ZGW_STORE_KEY] not in " ".join(" ".join(c) for c in fake_runner.calls)
    assert step.remove(ctx) == (ZGW_STORE_KEY,)


def test_steps_run_in_the_components_deployment(env_factory, fake_runner, profile_factory):
    env = cluster_env(env_factory, fake_runner, profile_factory)
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "notificaties"}}]}))
    assert env.deployment_for("opennotificaties") == "notificaties"
