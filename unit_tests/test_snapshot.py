"""Unit tests for the release snapshot: per-field hashes and what changed."""

import json

import pytest

from podiumd_tests.snapshot import SNAPSHOT
from podiumd_tests.snapshot import component_version
from podiumd_tests.snapshot import differences
from podiumd_tests.snapshot import fingerprint
from podiumd_tests.snapshot import latest

ZAAK = {"identificatie": "ZAAK-1", "status": {"naam": "Open"}, "rollen": ["b", "a"], "betrokkene": "999990019"}


def snap(zaak):
    return {"taken": "t", "zaaktypen": {}, "zaakafhandelparameters": {}, "zaken": {"ZAAK-1": fingerprint(zaak)}}


def test_fingerprint_keeps_hashes_per_field_never_values():
    found = fingerprint(ZAAK)
    assert sorted(found) == ["betrokkene", "identificatie", "rollen", "status.naam"]
    assert "999990019" not in json.dumps(found)


def test_list_order_is_no_change():
    assert fingerprint({**ZAAK, "rollen": ["a", "b"]}) == fingerprint(ZAAK)


def test_an_added_field_is_no_change_a_changed_or_removed_one_is():
    before = snap(ZAAK)
    assert differences(before, snap({**ZAAK, "nieuw": 1})) == []
    changed = {**ZAAK, "status": {"naam": "Afgerond"}}
    del changed["rollen"]
    assert differences(before, snap(changed)) == ["zaken ZAAK-1: rollen, status.naam"]


def test_a_missing_object_is_gone_and_a_new_one_no_change():
    after = {**snap(ZAAK), "zaken": {"ZAAK-2": fingerprint(ZAAK)}}
    assert differences(snap(ZAAK), after) == ["zaken ZAAK-1: gone"]


def test_many_changed_fields_are_counted():
    wide = {f"f{i}": i for i in range(10)}
    found = differences(snap(wide), snap({k: v + 1 for k, v in wide.items()}))
    assert found == ["zaken ZAAK-1: f0, f1, f2, f3, f4, f5, f6, f7 and 2 more"]


def test_latest_takes_the_newest_snapshot_of_the_environment(tmp_path):
    for name, taken in [
        ("20261001-100000_kees00_snapshot_a", "old"),
        ("20261002-100000_kees00_snapshot_b", "new"),
        ("20261003-100000_minikube_snapshot_c", "other env"),
    ]:
        (tmp_path / "2026-10" / name).mkdir(parents=True)
        (tmp_path / "2026-10" / name / SNAPSHOT).write_text(json.dumps({"taken": taken}), encoding="utf-8")
    assert latest(tmp_path, "kees00") == {"taken": "new"}
    assert latest(tmp_path, "qa") is None


@pytest.mark.parametrize(
    ("image", "label", "version"),
    [("ita.web:3.3.2", "3.3.4", (3, 3, 2)), ("ita.web@sha256:0bef", "3.3.4", (3, 3, 4)), ("ita.web:latest", "", None)],
)
def test_component_version_is_the_image_tag_else_the_helm_label(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    env_factory, profile_factory, fake_runner, image, label, version
):
    ita = {
        "metadata": {"name": "ita-web", "labels": {"app.kubernetes.io/version": label}},
        "spec": {"template": {"spec": {"containers": [{"image": f"ghcr.io/ita/{image}"}]}}},
    }
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [ita]}))
    env = env_factory(profile_factory(urls={"ita": "https://ita.example.test"}))
    assert component_version(env, "ita") == version
