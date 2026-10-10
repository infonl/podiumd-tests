"""Unit tests for the volume seed's counts, corpus and report."""

from podiumd_tests.environment import Environment
from podiumd_tests.seed.volume import KINDS
from podiumd_tests.seed.volume import SCALES
from podiumd_tests.seed.volume import Seeded
from podiumd_tests.seed.volume import corpus
from podiumd_tests.seed.volume import format_seeded
from podiumd_tests.seed.volume import target


def test_a_profile_setting_replaces_only_the_perf_count(profile_factory, fake_runner):
    env = Environment(profile_factory(settings={"seed_volume_zaken": "2000"}), fake_runner, environ={})
    assert target(env, "perf", "zaken") == 2000
    assert target(env, "smoke", "zaken") == SCALES["smoke"]["zaken"]
    assert target(env, "perf", "partijen") == SCALES["perf"]["partijen"]


def test_corpus_picks_wrap_around():
    names = corpus()
    assert names.persoon(len(names.personen)) == names.persoon(0)
    assert names.scenario(len(names.scenarios) + 1) == names.scenario(1)


def test_report_shows_counts_or_the_skip_reason():
    report = format_seeded([Seeded("zaken", 3, 50), Seeded("objecten", 0, 0, "skipped: no objecten")])
    assert report.splitlines() == ["zaken          3 -> 50", "objecten       skipped: no objecten"]


def test_zaken_in_zac_need_the_profile_setting(profile_factory, fake_runner):
    zaken_in_zac = next(k for k in KINDS if k.name == "zaken_in_zac")
    refused = Environment(profile_factory(), fake_runner, environ={})
    allowed = Environment(profile_factory(settings={"pabc_volume_zaaktype": "True"}), fake_runner, environ={})
    assert "pabc_volume_zaaktype" in str(zaken_in_zac.refused(refused))
    assert zaken_in_zac.refused(allowed) is None
    assert zaken_in_zac.target_kind == "zaken"
