"""Unit tests for environment profiles."""

import pytest

from podiumd_tests.config import ProfileError
from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import list_profiles
from podiumd_tests.config import load_profile


def test_parses_a_valid_profile(profile_factory):
    profile = profile_factory(
        secrets={"token": {"k8s_secret": {"name": "s", "key": "k"}}},
        access={"mode": "host-header", "ingress_service": {"namespace": "traefik", "name": "traefik"}},
        settings={"zgw_client_id": "open-formulieren"},
    )
    assert profile.settings == {"zgw_client_id": "open-formulieren"}
    assert profile.urls["openzaak"] == "https://openzaak.example.test"
    assert profile.secrets["token"].options == {"name": "s", "key": "k"}
    assert profile.secrets["token"].needs_cluster
    assert profile.access.mode == "host-header"
    assert profile.access.ingress_service is not None
    assert profile.access.ingress_service.name == "traefik"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"urls": {"nope": "https://x"}}, "unknown component"),
        ({"urls": {"openzaak": "ftp://x"}}, r"expected an http\(s\) URL"),
        ({"allowed_tiers": []}, "allowed_tiers must be a non-empty list"),
        ({"allowed_tiers": ["everything"]}, "unknown tier"),
        ({"estate": "elsewhere"}, "estate"),
        ({"secrets": {"pw": {"dev_default": "admin"}}}, "dev_default is only allowed for minikube"),
        ({"secrets": {"pw": {"vault": {}}}}, "unknown source"),
        ({"kube": {"context": "ctx"}}, "missing namespace"),
        ({"access": {"mode": "magic"}}, "expected direct or host-header"),
        ({"settings": ["zgw_client_id"]}, "settings"),
        ({"bootstrap": {"wiring": "yes"}}, "expected true or false"),
    ],
)
def test_rejects_invalid_profiles(profile_factory, override, message):
    with pytest.raises(ProfileError, match=message):
        profile_factory(**override)


def test_dev_default_is_allowed_for_minikube(profile_factory):
    profile = profile_factory(estate="minikube", secrets={"pw": {"dev_default": "admin"}})
    assert profile.secrets["pw"].options == {"value": "admin"}


def test_duplicate_profile_names_are_an_error(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "env.yaml").write_text("{}")
    (tmp_path / "b" / "env.yaml").write_text("{}")
    with pytest.raises(ProfileError, match="duplicate profile name"):
        list_profiles(tmp_path)


def test_unknown_profile_lists_the_known_ones(tmp_path):
    (tmp_path / "known.yaml").write_text("{}")
    with pytest.raises(ProfileError, match="known: known"):
        load_profile("other", tmp_path)


@pytest.mark.parametrize("name", sorted(list_profiles(default_envs_dir())))
def test_every_committed_profile_loads(name):
    profile = load_profile(name, default_envs_dir())
    assert profile.urls
    if profile.estate == "externals":
        # ExternalsPodiumD environments stay smoke-only until PLAN.md §12 decides otherwise.
        assert profile.allowed_tiers == ("smoke",)


def test_only_cluster_sources_need_the_cluster(profile_factory):
    profile = profile_factory(
        keyvault="kv", secrets={"a": {"keyvault": {"secret": "x"}}, "b": {"pod_env": {"deployment": "d", "var": "V"}}}
    )
    assert not profile.secrets["a"].needs_cluster
    assert profile.secrets["b"].needs_cluster


@pytest.mark.parametrize(
    ("estate", "override", "expected"),
    [("podiumd-infra", None, True), ("externals", None, False), ("externals", True, True)],
)
def test_wiring_defaults_per_estate(profile_factory, estate, override, expected):
    bootstrap = {} if override is None else {"wiring": override}
    assert profile_factory(estate=estate, bootstrap=bootstrap).wiring is expected
