"""Unit tests for Open VTB's Celery workloads, its publish schedule and publishing one bericht."""

import json

from podiumd_tests.seed import openvtb


def deployments(fake_runner, *names):
    items = [{"metadata": {"name": name}} for name in ("openvtb", *names)]
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": items}))
    fake_runner.answers["get statefulsets"] = (0, json.dumps({"items": []}))


def test_missing_celery_names_the_missing_workloads(env_factory, fake_runner):
    deployments(fake_runner, "openvtb-beat")
    assert openvtb.missing_celery(env_factory()) == (
        "no openvtb-worker: Open VTB sends no CloudEvents (podiumd chart without helm-charts #746)"
    )


def test_missing_celery_is_none_with_worker_and_beat(env_factory, fake_runner):
    deployments(fake_runner, "openvtb-worker", "openvtb-beat")
    assert openvtb.missing_celery(env_factory()) is None


def test_publish_schedules_are_the_crontabs_of_the_enabled_tasks(env_factory, fake_runner):
    deployments(fake_runner)
    fake_runner.answers["exec -i deploy/openvtb"] = (0, "chatter\nPTEST_VALUE=0 */1 * * *\nPTEST_VALUE=end\n")
    assert openvtb.publish_schedules(env_factory()) == ["0 */1 * * *"]


def test_publish_bericht_sends_and_marks_only_that_bericht(env_factory, fake_runner):
    deployments(fake_runner)
    fake_runner.answers["exec -i deploy/openvtb"] = (0, "")
    openvtb.publish_bericht(env_factory(), "b-1")
    code = next(stdin for stdin in fake_runner.stdins if stdin and "send_bericht" in stdin)
    assert "uuid='b-1'" in code
    assert "mark_as_published.delay([pk])" in code


def test_notifications_api_root_is_the_printed_api_root(env_factory, fake_runner):
    deployments(fake_runner)
    fake_runner.answers["exec -i deploy/openvtb"] = (0, "chatter\nPTEST_VALUE=https://on.test/api/v1/\n")
    assert openvtb.notifications_api_root(env_factory()) == "https://on.test/api/v1/"
