"""Unit tests for the mock server step and reading what it received."""

import importlib.util
import json

from podiumd_tests import mock_server
from podiumd_tests.bootstrap import Context
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.json_data import section
from podiumd_tests.mock_server import NAME
from podiumd_tests.mock_server import Callback
from podiumd_tests.mock_server import MockServer


def ctx_for(env):
    return Context(env, CredentialStore(env.kube))


def test_manifests_carry_the_mock_server_code_and_the_managed_by_label():
    docs = mock_server.manifests()
    assert [d["kind"] for d in docs] == ["ConfigMap", "Deployment", "Service"]
    assert docs[0]["data"] == {"server.py": (mock_server.INFRA / "server.py").read_text()}
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


def test_mock_server_is_present_only_with_current_code_and_a_ready_replica(env_factory, fake_runner):
    code = (mock_server.INFRA / "server.py").read_text()
    fake_runner.answers[f"get deployment {NAME}"] = (0, json.dumps({"status": {"readyReplicas": 1}}))
    fake_runner.answers[f"get configmap {NAME}"] = (0, json.dumps({"data": {"server.py": "old"}}))
    ctx = ctx_for(env_factory())
    assert not MockServer().is_present(ctx)
    fake_runner.answers[f"get configmap {NAME}"] = (0, json.dumps({"data": {"server.py": code}}))
    assert MockServer().is_present(ctx)


def test_apply_sends_manifests_over_stdin_and_waits_for_the_rollout(env_factory, fake_runner):
    fake_runner.answers["apply -f -"] = (0, "")
    fake_runner.answers["rollout"] = (0, "")
    MockServer().apply(ctx_for(env_factory()))
    kinds = [json.loads(s)["kind"] for s in fake_runner.stdins if s]
    assert kinds == ["ConfigMap", "Deployment", "Service"]
    assert any("status" in call and f"deployment/{NAME}" in call for call in fake_runner.calls)


def test_remove_deletes_service_first(env_factory, fake_runner):
    fake_runner.answers["delete"] = (0, "")
    assert MockServer().remove(ctx_for(env_factory())) == ()
    deleted = [call[call.index("delete") + 1] for call in fake_runner.calls]
    assert deleted == ["service", "deployment", "configmap"]


def test_callback_skips_a_line_cut_short(env_factory, fake_runner):
    good = {"path": "/run1/abc", "body": {}}
    fake_runner.answers[f"exec deploy/{NAME}"] = (0, json.dumps(good) + '\n{"path": "/run1/abc", "bo')
    assert Callback(env_factory(), "/run1/abc").received() == [good]


def mock_server_handler(path):
    """A mock server Handler for a path, without a socket: enough for its status logic."""
    spec = importlib.util.spec_from_file_location("server", mock_server.INFRA / "server.py")
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handler = module.Handler.__new__(module.Handler)
    handler.path = path
    return handler


def test_fail_first_path_fails_the_first_notification_only():
    handler = mock_server_handler("/ptest-x/fail-first/abc")
    check = {"authorization": "Bearer t", "body": {"kanaal": "test"}}
    notification = {"authorization": "Bearer t", "body": {"kanaal": "zaken"}}
    assert [handler._status(e) for e in (check, notification, notification)] == [204, 500, 204]  # pylint: disable=protected-access


def test_mock_server_refuses_without_authorization_and_answers_notify():
    assert mock_server_handler("/ptest-x/abc")._status({"authorization": None, "body": None}) == 403  # pylint: disable=protected-access
    notify = mock_server_handler("/ptest-x/notify/v2/notifications/email")
    assert notify._status({"authorization": "ApiKey-v1 k", "body": {}}) == 201  # pylint: disable=protected-access


def test_notify_notification_is_recorded_with_an_id_and_answers_a_get():
    handler = mock_server_handler("/notify/v2/notifications/sms")
    sent = []
    handler._json = lambda status, body: sent.append((status, body))  # pylint: disable=protected-access
    handler._notify_created("0" * 8 + "-0000-0000-0000-" + "0" * 12, {"template_id": "t", "phone_number": "0612345678"})  # pylint: disable=protected-access
    status, body = sent[0]
    assert status == 201
    assert body["content"]["subject"] == "ptest sms t"
    handler.path = f"/v2/notifications/{body['id']}"
    handler.do_GET()
    assert sent[1][0] == 200
    assert sent[1][1]["phone_number"] == "0612345678"
    assert sent[1][1]["status"] == "delivered"


def test_fail_first_callback_path(env_factory):
    assert "/fail-first/" in Callback.new(env_factory(), "ptest-x", fail_first=True).path
