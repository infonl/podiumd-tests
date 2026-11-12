"""Unit tests for the inway consumers' bootstrap step."""

import json

from podiumd_tests.bootstrap import inway as inway_step
from podiumd_tests.bootstrap.runner import Context
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.inway import fingerprint
from podiumd_tests.inway import make_identity
from podiumd_tests.inway import split
from podiumd_tests.process import run_process

SETTINGS = {"inway_client_ca": "owner/.pki/client-ca", "inway_consumers_command": "owner/bin/openbao-consumers"}


def _context(env_factory, profile_factory, fake_runner, settings):
    fake_runner.answers["get secret podiumd-tests-credentials"] = (0, json.dumps({"kind": "Secret"}))
    env = env_factory(profile_factory(settings=settings))
    return Context(env, CredentialStore(env.kube))


def test_without_the_setting_the_owner_keeps_everything(env_factory, profile_factory, fake_runner):
    ctx = _context(env_factory, profile_factory, fake_runner, {})
    step = inway_step.InwayConsumers()
    assert step.is_present(ctx)
    assert step.apply(ctx) == {}
    assert step.remove(ctx) == ()
    assert "environment owner's" in ctx.notes[0]


def test_apply_deploys_fg_echo_and_registers_partner_a_and_b(
    env_factory, profile_factory, fake_runner, monkeypatch, tmp_path
):
    identity = make_identity(run_process, None, tmp_path, "partner-x")
    monkeypatch.setattr(inway_step, "make_identity", lambda *_: identity)
    fake_runner.answers["apply -f -"] = (0, "")
    fake_runner.answers["rollout status deployment/fg-echo"] = (0, "")
    fake_runner.answers["openbao-consumers"] = (0, "")
    ctx = _context(env_factory, profile_factory, fake_runner, SETTINGS)
    stored = inway_step.InwayConsumers().apply(ctx)
    assert set(stored) == {"inway_partner_a", "inway_partner_b", "inway_partner_c"}
    registered = next(call for call in fake_runner.calls if call[0].endswith("openbao-consumers"))
    sha1 = fingerprint(split(identity)[0])
    assert registered[1:] == [f"partner-a={sha1}", f"partner-b={sha1}"]


def test_remove_unregisters_only_partner_a_and_b(env_factory, profile_factory, fake_runner):
    fake_runner.answers["openbao-consumers"] = (0, "")
    fake_runner.answers["delete"] = (0, "")
    ctx = _context(env_factory, profile_factory, fake_runner, SETTINGS)
    removed = inway_step.InwayConsumers().remove(ctx)
    assert removed == ("inway_partner_a", "inway_partner_b", "inway_partner_c")
    registered = next(call for call in fake_runner.calls if call[0].endswith("openbao-consumers"))
    assert registered[1:] == ["--remove", "partner-a", "partner-b"]
