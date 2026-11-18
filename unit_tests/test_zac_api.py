"""Unit tests for the bridge between ZAC 5.9's and 5.12's REST API."""

from podiumd_tests.zac_api import NEW_NAMES
from podiumd_tests.zac_api import OLD_NAMES
from podiumd_tests.zac_api import READ
from podiumd_tests.zac_api import SENT
from podiumd_tests.zac_api import USER_CALLS


def test_booleans_get_zac_5_12_names_and_back():
    sent = {"valide": True, "humanTaskParameters": [{"actief": True}], "mail": "TAAK_AANVULLENDE_INFORMATIE"}
    assert SENT.apply(sent) == {
        "isValide": True,
        "humanTaskParameters": [{"actief": True}],
        "mail": "TAAK_AANVULLENDE_INFORMATIE",
    }
    assert READ.apply([{"isValide": True, "rechten": {"canAfbreken": True}}]) == [
        {"valide": True, "rechten": {"afbreken": True}}
    ]


def test_each_new_name_has_one_old_name():
    assert len(OLD_NAMES) == len(NEW_NAMES)


def test_a_users_id_is_its_username_from_zac_5_12():
    groep = {"id": "beheerders", "naam": "Beheerders"}
    sent = {"groep": groep, "behandelaar": {"id": "ptest-admin", "naam": "Admin"}}
    assert SENT.apply(sent) == {"groep": groep, "behandelaar": {"username": "ptest-admin", "naam": "Admin"}}
    assert READ.apply([{"username": "u1", "naam": "U"}], is_user=True) == [{"id": "u1", "naam": "U"}]


def test_the_calls_that_answer_users():
    paths = ("/rest/identity/users", "/rest/zaken/zaak/z1/zaakspecifiek-geautoriseerde-medewerkers/kandidaten")
    assert all(USER_CALLS.search(path) for path in paths)
    assert not USER_CALLS.search("/rest/zaken/zaak/z1")
