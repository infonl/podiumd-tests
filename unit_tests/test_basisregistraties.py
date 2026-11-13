"""Unit tests for the BRP and KvK helpers."""

from podiumd_tests.basisregistraties import kvk_foutcodes


def test_kvk_foutcodes_lists_the_codes_of_the_fout_list(response_factory):
    body = {"fout": [{"code": "IPD5200", "omschrijving": "Er zijn geen gegevens gevonden"}, {"code": "IPD0005"}]}
    assert kvk_foutcodes(response_factory(status=404, json_body=body)) == {"IPD5200", "IPD0005"}


def test_kvk_foutcodes_is_empty_without_a_fout_list(response_factory):
    assert kvk_foutcodes(response_factory(json_body={"resultaten": []})) == set()
