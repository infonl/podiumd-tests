"""Unit tests for the pytest plugin, run in a nested pytest session (pytester)."""

import pytest

from podiumd_tests import pytest_plugin
from podiumd_tests.bootstrap import Outcome
from podiumd_tests.pytest_plugin import requiring

pytest_plugins = ["pytester"]

INNER_CONFTEST = """
import subprocess

import pytest

from podiumd_tests.config import parse_profile
from podiumd_tests.environment import Environment
from podiumd_tests.pytest_plugin import ENVIRONMENT_KEY

pytest_plugins = ["podiumd_tests.pytest_plugin"]


def no_cluster(args, _timeout, _stdin=None):
    return subprocess.CompletedProcess(list(args), 1, "", "no cluster")


def pytest_configure(config):
    profile = parse_profile(
        {
            "estate": "podiumd-infra",
            "allowed_tiers": ["smoke"],
            "kube": {"context": "ctx", "namespace": "podiumd"},
            "urls": {"openzaak": "https://openzaak.example.test"},
        },
        name="inner",
    )
    config.stash[ENVIRONMENT_KEY] = Environment(profile, no_cluster, environ={})


def pytest_itemcollected(item):
    if not item.get_closest_marker("source"):
        item.add_marker(pytest.mark.source("podiumd-tests", "inner test of a unit test"))
"""

INNER_TESTS = """
import pytest


@pytest.fixture(scope="module")
def zac_client():
    raise AssertionError("module fixture ran for a skipped test")


@pytest.mark.requires("zac")
def test_needs_zac(zac_client):
    pass


@pytest.mark.requires("openzaak")
def test_needs_openzaak():
    pass


@pytest.mark.requires("cluster")
def test_needs_cluster():
    pass
"""


def test_requires_skips_before_module_fixtures_run(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(INNER_TESTS)
    # pytest-playwright does not support a nested in-process session; the markers live in pyproject.toml.
    result = pytester.runpytest_inprocess("-rs", "-p", "no:playwright", "-W", "ignore::pytest.PytestUnknownMarkWarning")
    result.assert_outcomes(passed=1, skipped=2)
    result.stdout.fnmatch_lines(["*requires: zac (no URL in profile)*", "*requires: cluster (kube API of context ctx*"])
    result.stdout.no_fnmatch_line("*module fixture ran*")


def test_requiring_builds_a_param_that_requires_its_component():
    param = requiring("kiss", "kiss", "/healthz", test_id="kiss/healthz")
    assert param.values == ("kiss", "/healthz")
    assert param.id == "kiss/healthz"
    assert [(m.name, m.args) for m in param.marks] == [("requires", ("kiss",))]


def test_destructive_tests_share_one_xdist_group(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(
        """
import pytest


@pytest.mark.destructive
def test_destructive(request):
    assert request.node.get_closest_marker("xdist_group").args == ("destructive",)


def test_other(request):
    assert request.node.get_closest_marker("xdist_group") is None
"""
    )
    result = pytester.runpytest_inprocess("-p", "no:playwright", "-W", "ignore::pytest.PytestUnknownMarkWarning")
    result.assert_outcomes(passed=2)


# Inner sessions run in this process, so the plugin's module attributes can be patched from outside.
INNER_ARGS = ("-p", "no:playwright", "-W", "ignore::pytest.PytestUnknownMarkWarning")

REPLICAS_TEST = """
import pytest


def test_multi_pod(several_replicas, request):
    assert request.node.get_closest_marker("destructive") is None
"""


def test_several_replicas_is_destructive_where_the_profile_switches_pods(pytester):
    pytester.makeconftest(INNER_CONFTEST.replace('"urls"', '"settings": {"replicas_command": "replicas"}, "urls"'))
    pytester.makepyfile(REPLICAS_TEST)
    pytester.runpytest_inprocess(*INNER_ARGS, "-m", "not destructive").assert_outcomes(deselected=1)


def test_several_replicas_is_a_no_op_without_replicas_command(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(REPLICAS_TEST)
    pytester.runpytest_inprocess(*INNER_ARGS, "-m", "not destructive").assert_outcomes(passed=1)


APPS = ("openzaak", "openklant", "objecten", "objecttypen", "opennotificaties", "mailpit", "zac")
WRITABLE_CONFTEST = (
    INNER_CONFTEST.replace('"allowed_tiers": ["smoke"]', '"allowed_tiers": ["smoke", "full"]')
    .replace(
        '"urls": {"openzaak": "https://openzaak.example.test"}',
        '"urls": {'
        + ", ".join(f'"{a}": "https://{a}.example.test"' for a in APPS)
        + '}, "settings": {"productaanvraag_zaaktype": "ZT-PA"}',
    )
    .replace("environ={}", 'environ={"PODIUMD_TESTS_SECRET_" + k: "s3cr3t" for k in SECRETS}')
    + """
SECRETS = [
    "PTEST_BOOTSTRAP_ZGW_SECRET",
    "PTEST_BOOTSTRAP_ZGW_OPENBAAR_SECRET",
    "PTEST_BOOTSTRAP_ZGW_NOAUTH_SECRET",
    "PTEST_BOOTSTRAP_ZGW_PRODUCTAANVRAAG_SECRET",
    "PTEST_BOOTSTRAP_NRC_SECRET",
    "PTEST_BOOTSTRAP_OBJECTEN_TOKEN",
    "PTEST_BOOTSTRAP_OBJECTTYPEN_TOKEN",
    "PTEST_BOOTSTRAP_OPENKLANT_TOKEN",
    "PTEST_BOOTSTRAP_ADMIN_PASSWORD",
]
"""
)


def _check_all(action):
    return lambda _env, steps: [Outcome(s.name, action, "wiring off") for s in steps]


def test_environment_comes_from_the_profile_named_by_option(pytester):
    (pytester.path / "envs").mkdir()
    (pytester.path / "envs" / "x.yaml").write_text(
        "estate: externals\nallowed_tiers: [smoke]\nkube: {context: c, namespace: podiumd}\nurls: {}\n",
        encoding="utf-8",
    )
    pytester.makeconftest('pytest_plugins = ["podiumd_tests.pytest_plugin"]')
    pytester.makepyfile(
        "import pytest\n\n\n@pytest.mark.source('podiumd-tests', 'x')\n"
        "def test_env(podiumd_env):\n    assert podiumd_env.profile.name == 'x'\n"
    )
    envs_dir = f"--podiumd-envs-dir={pytester.path / 'envs'}"
    pytester.runpytest_inprocess(*INNER_ARGS, "--podiumd-env=x", envs_dir).assert_outcomes(passed=1)
    result = pytester.runpytest_inprocess(*INNER_ARGS, envs_dir)
    assert result.ret == 2
    result.stdout.fnmatch_lines(["*no environment: use `podiumd-tests run --env <name>`*"])


def test_api_fixtures_check_their_bootstrap_step_once(pytester, monkeypatch):
    checked = []

    def check(_env, steps):
        checked.extend(s.name for s in steps)
        return [Outcome(s.name, "present") for s in steps]

    monkeypatch.setattr(pytest_plugin, "check", check)
    pytester.makeconftest(WRITABLE_CONFTEST)
    pytester.makepyfile(
        """
def test_clients(openklant, objecten, objecttypen, openzaak, openzaak_openbaar, openzaak_noauth,
                 openzaak_productaanvraag, opennotificaties, mailpit, zgw_secret, run_tag):
    assert openklant.url("x") == "https://openklant.example.test/klantinteracties/api/v1/x"
    assert opennotificaties.url("x") == "https://opennotificaties.example.test/api/v1/x"
    assert zgw_secret == "s3cr3t"
    assert run_tag.startswith("ptest-")


def test_environment_fixtures(podiumd_env, kube, credentials, caps, urls, http):
    assert kube is podiumd_env.kube
    assert credentials is podiumd_env.credentials
    assert "cluster" not in caps.present
    assert urls["mailpit"] == "https://mailpit.example.test"
    assert http.get_adapter("https://mailpit.example.test")


def test_again(openzaak, callback, new_callback):
    assert callback.path != new_callback(fail_first=True).path
"""
    )
    pytester.runpytest_inprocess(*INNER_ARGS, "--podiumd-run-tag=ptest-unit").assert_outcomes(passed=3)
    assert checked.count("openzaak-client") == 1
    assert checked.count("infra-mock-server") == 1


NEEDS_A_STEP = """
def test_needs(need_bootstrap):
    need_bootstrap("openklant-token")
"""


@pytest.mark.parametrize(
    ("action", "args", "outcome", "message"),
    [
        ("skipped", (), "skipped", "*bootstrap step openklant-token: wiring off*"),
        ("missing", (), "failed", "*bootstrap missing on inner (openklant-token): run `podiumd-tests*"),
        ("missing", ("--auto-bootstrap",), "failed", "*--auto-bootstrap refused: inner is smoke-only*"),
    ],
)
def test_need_bootstrap_skips_or_fails_on_absent_steps(pytester, monkeypatch, action, args, outcome, message):
    monkeypatch.setattr(pytest_plugin, "check", _check_all(action))
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(NEEDS_A_STEP)
    result = pytester.runpytest_inprocess(*INNER_ARGS, "-rsf", *args)
    result.assert_outcomes(**{outcome: 1})
    result.stdout.fnmatch_lines([message])


@pytest.mark.parametrize(("created", "outcome"), [("created", "passed"), ("failed", "failed")])
def test_auto_bootstrap_applies_the_missing_steps(pytester, monkeypatch, created, outcome):
    monkeypatch.setattr(pytest_plugin, "check", _check_all("missing"))
    monkeypatch.setattr(
        pytest_plugin, "bootstrap", lambda _env, steps: [Outcome(s.name, created, "403") for s in steps]
    )
    pytester.makeconftest(WRITABLE_CONFTEST)
    pytester.makepyfile(NEEDS_A_STEP)
    result = pytester.runpytest_inprocess(*INNER_ARGS, "-rf", "--auto-bootstrap")
    result.assert_outcomes(**{outcome: 1})
    if outcome == "failed":
        result.stdout.fnmatch_lines(["*--auto-bootstrap: openklant-token failed: 403*"])


def test_need_bootstrap_fails_on_an_unknown_step(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile("def test_needs(need_bootstrap):\n    need_bootstrap('nope')\n")
    result = pytester.runpytest_inprocess(*INNER_ARGS, "-rf")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*unknown bootstrap steps: nope*"])


def test_profile_settings_fixtures_skip_without_their_setting(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(
        """
def test_type(productaanvraagtype):
    pass


def test_key(pabc_api_key):
    pass
"""
    )
    result = pytester.runpytest_inprocess(*INNER_ARGS, "-rs")
    result.assert_outcomes(skipped=2)
    result.stdout.fnmatch_lines(
        ["*profile inner has no settings.productaanvraag_type*", "*no secret pabc_api_key in the profile*"]
    )


def test_keep_data_leaves_registered_resources_behind(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(
        """
def test_create(registry):
    registry.add("zaak Z1", lambda: (_ for _ in ()).throw(AssertionError("deleted")))
"""
    )
    result = pytester.runpytest_inprocess(*INNER_ARGS, "-s", "--keep-data")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*--keep-data: left behind zaak Z1*"])


def test_a_non_strict_xpass_is_recorded_as_a_junit_property(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(
        """
import pytest


@pytest.mark.xfail(reason="known defect ZAC-1")
def test_fixed():
    pass
"""
    )
    junit = pytester.path / "junit.xml"
    pytester.runpytest_inprocess(*INNER_ARGS, f"--junitxml={junit}")
    assert '<property name="xpass" value="known defect ZAC-1"' in junit.read_text(encoding="utf-8")


def test_zac_and_zaaktype_fixtures(pytester, monkeypatch, fake_http):
    fake_http({"/catalogi/api/v1/zaaktypen": (200, {"results": [{"url": "zt-1"}], "next": None})})
    deleted = []
    monkeypatch.setattr(pytest_plugin, "check", lambda _env, steps: [Outcome(s.name, "present") for s in steps])
    monkeypatch.setattr(pytest_plugin, "zac_session", lambda _env, user, password: f"{user}:{password}")
    monkeypatch.setattr(pytest_plugin, "zaakafhandelparameters", lambda _zac, _url, zaaktype: [{"zaaktype": zaaktype}])
    monkeypatch.setattr(pytest_plugin, "confirmation_on", lambda _zac, _url, _zaaktype: False)
    monkeypatch.setattr(pytest_plugin, "objecttype_url", lambda _env, name: f"objecttype {name}")
    monkeypatch.setattr(pytest_plugin, "zaaktype_parts", lambda _client, zaaktype: f"parts of {zaaktype['url']}")
    monkeypatch.setattr(
        pytest_plugin,
        "create_zaak",
        lambda _zac, _url, _parameters, **fields: {"uuid": "u1", "identificatie": "ZAAK-1", **fields},
    )
    monkeypatch.setattr(pytest_plugin, "delete_zaak", lambda _client, url, with_documents: deleted.append(url))
    pytester.makeconftest(WRITABLE_CONFTEST)
    pytester.makepyfile(
        """
def test_fixtures(zac, zac_parameters, zac_zaak, parts, productaanvraag_objecttype):
    assert zac == "ptest-bootstrap-admin:s3cr3t"
    assert zac_parameters == {"zaaktype": "ZT-PA"}
    assert zac_zaak(toelichting="t")["omschrijving"] == "ptest-unit-zac-zaak"
    assert parts == "parts of zt-1"
    assert productaanvraag_objecttype.startswith("objecttype ")


def test_confirmation(ontvangstbevestiging):
    pass
"""
    )
    result = pytester.runpytest_inprocess(*INNER_ARGS, "-rs", "--podiumd-run-tag=ptest-unit")
    result.assert_outcomes(passed=1, skipped=1)
    result.stdout.fnmatch_lines(["*ZAC sends no ontvangstbevestiging for ZT-PA*"])
    assert deleted == ["https://openzaak.example.test/zaken/api/v1/zaken/u1"]


def test_zac_parameters_skip_without_parameters_in_zac(pytester, monkeypatch):
    monkeypatch.setattr(pytest_plugin, "check", lambda _env, steps: [Outcome(s.name, "present") for s in steps])
    monkeypatch.setattr(pytest_plugin, "zac_session", lambda _env, _user, _password: None)
    monkeypatch.setattr(pytest_plugin, "zaakafhandelparameters", lambda _zac, _url, _zaaktype: [])
    pytester.makeconftest(WRITABLE_CONFTEST)
    pytester.makepyfile("def test_parameters(zac_parameters):\n    pass\n")
    result = pytester.runpytest_inprocess(*INNER_ARGS, "-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*ZAC has no zaakafhandelparameters for ZT-PA*"])


def test_tests_without_a_valid_source_stop_the_run(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(
        """
import pytest


@pytest.mark.source("somewhere", "a reason")
def test_unknown_origin():
    pass
"""
    )
    result = pytester.runpytest_inprocess(*INNER_ARGS)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*source origin 'somewhere' starts with none of TA, MK*"])


def test_sources_become_junit_properties(pytester):
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(
        """
import pytest

pytestmark = pytest.mark.source("TA regression/1-x.spec.ts", "the module's reason")


@pytest.mark.source("ZAC features/1-login.feature", "the test's reason")
def test_sourced(request):
    assert [v for k, v in request.node.user_properties if k == "source"] == [
        "ZAC features/1-login.feature: the test's reason",
        "TA regression/1-x.spec.ts: the module's reason",
    ]
"""
    )
    pytester.runpytest_inprocess(*INNER_ARGS).assert_outcomes(passed=1)
