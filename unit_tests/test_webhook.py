"""Unit tests for the webhook receiver step and reading what it received."""

import json

from podiumd_tests import webhook
from podiumd_tests.bootstrap import Context
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.json_data import section
from podiumd_tests.webhook import NAME
from podiumd_tests.webhook import Callback
from podiumd_tests.webhook import WebhookReceiver


def ctx_for(env):
    return Context(env, CredentialStore(env.kube))


def test_manifests_carry_the_receiver_code_and_the_managed_by_label():
    docs = webhook.manifests()
    assert [d["kind"] for d in docs] == ["ConfigMap", "Deployment", "Service"]
    assert docs[0]["data"] == {"receiver.py": (webhook.INFRA / "receiver.py").read_text()}
    labels = [section(section(d, "metadata"), "labels") for d in docs]
    assert all(label["app.kubernetes.io/managed-by"] == "podiumd-tests" for label in labels)


def test_callback_reads_only_its_own_path(env_factory, fake_runner):
    lines = [{"path": "/run1/abc", "body": {"actie": "create"}}, {"path": "/run1/other", "body": {}}]
    fake_runner.answers[f"exec deploy/{NAME}"] = (0, "\n".join(json.dumps(line) for line in lines) + "\n")
    callback = Callback(env_factory(), "/run1/abc")
    assert callback.received() == [lines[0]]
    assert (
        callback.wait_for(lambda e: section(e, "body").get("actie") == "create", timeout=0, description="create")
        == lines[0]
    )


def test_callback_url_is_the_in_cluster_service(env_factory):
    callback = Callback.new(env_factory(), "run1")
    assert callback.url.startswith(f"http://{NAME}.podiumd/run1/")
    assert Callback.new(env_factory(), "run1").path != callback.path


def test_receiver_is_present_only_with_current_code_and_a_ready_replica(env_factory, fake_runner):
    code = (webhook.INFRA / "receiver.py").read_text()
    fake_runner.answers[f"get deployment {NAME}"] = (0, json.dumps({"status": {"readyReplicas": 1}}))
    fake_runner.answers[f"get configmap {NAME}"] = (0, json.dumps({"data": {"receiver.py": "old"}}))
    ctx = ctx_for(env_factory())
    assert not WebhookReceiver().is_present(ctx)
    fake_runner.answers[f"get configmap {NAME}"] = (0, json.dumps({"data": {"receiver.py": code}}))
    assert WebhookReceiver().is_present(ctx)


def test_apply_sends_manifests_over_stdin_and_waits_for_the_rollout(env_factory, fake_runner):
    fake_runner.answers["apply -f -"] = (0, "")
    fake_runner.answers["rollout"] = (0, "")
    WebhookReceiver().apply(ctx_for(env_factory()))
    kinds = [json.loads(s)["kind"] for s in fake_runner.stdins if s]
    assert kinds == ["ConfigMap", "Deployment", "Service"]
    assert any("status" in call and f"deployment/{NAME}" in call for call in fake_runner.calls)


def test_remove_deletes_service_first(env_factory, fake_runner):
    fake_runner.answers["delete"] = (0, "")
    assert WebhookReceiver().remove(ctx_for(env_factory())) == ()
    deleted = [call[call.index("delete") + 1] for call in fake_runner.calls]
    assert deleted == ["service", "deployment", "configmap"]


def test_callback_skips_a_line_cut_short(env_factory, fake_runner):
    good = {"path": "/run1/abc", "body": {}}
    fake_runner.answers[f"exec deploy/{NAME}"] = (0, json.dumps(good) + '\n{"path": "/run1/abc", "bo')
    assert Callback(env_factory(), "/run1/abc").received() == [good]
