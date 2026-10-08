"""Open Inwoner's search: products by name and keyword, filtering on onderwerp, feedback, switching it off.

Ported from TA interaction 107 and regression 161 (the anonymous search) and the draaiboek's Portaal
search cases. The products and categories are the test's own (snippet oi_search_data); search
needs the onderwerpen page with ProductsApphook (bootstrap openinwoner-cms-pages) to link its hits.
One test switches search off for the whole site, so the module runs on one worker.
"""

from __future__ import annotations

import re
import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.openinwoner import search_data
from podiumd_tests.openinwoner import set_site_configuration
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    import requests

    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("openinwoner", "cluster"),
    pytest.mark.xdist_group("openinwoner-search"),
]

# Words that occur only in the test's own products; a hex suffix keeps runs apart. Their first
# letters differ: the index also matches word prefixes (edge n-grams).
SUFFIX = secrets.token_hex(3)
PASPOORT, GROFVUIL, KEYWORD, BOTH = (f"{w}{SUFFIX}" for w in ("paspoort", "grofvuil", "reisdocument", "beide"))


@pytest.fixture(scope="module", name="categories")
def fixture_categories(
    podiumd_env: Environment, run_tag: str, need_bootstrap: Callable[..., None]
) -> Iterator[dict[str, str]]:
    """Two published products in their own categories; the categories' slugs by name."""
    need_bootstrap("openinwoner-cms-pages")
    tag = f"{run_tag}-zoeken"
    products: list[dict[str, object]] = [
        {"name": f"Paspoort {PASPOORT} {BOTH}", "keywords": [KEYWORD], "category": f"Burgerzaken {SUFFIX}"},
        {"name": f"Grofvuil {GROFVUIL} {BOTH}", "category": f"Afval {SUFFIX}"},
    ]
    created = search_data(podiumd_env, "apply", tag, products)
    yield dict(created["categories"])
    search_data(podiumd_env, "remove", tag)


def hits(http: requests.Session, urls: dict[str, str], **params: str) -> list[str]:
    """The names of the test's products on the results page of a search."""
    html = expect_status(http.get(urls["openinwoner"] + "/search/", params=params), HTTPStatus.OK).text
    return sorted(set(re.findall(rf"(?:Paspoort|Grofvuil) \w+{SUFFIX}", html)))


@pytest.mark.parametrize("query", ["informatie", "ptest-xyzzy-geen-resultaat"])
def test_search_answers(http: requests.Session, urls: dict[str, str], query: str) -> None:
    """Search answers with its form; a query without hits says so (TA int-107, reg-161c/d)."""
    html = expect_status(http.get(urls["openinwoner"] + "/search/", params={"query": query}), HTTPStatus.OK).text
    assert 'name="query"' in html
    if "geen" in query:
        assert "We konden geen zoekresultaten vinden" in html


@pytest.mark.tc("OI-092")
@pytest.mark.usefixtures("categories")
@pytest.mark.parametrize("query", [PASPOORT, KEYWORD], ids=["name", "keyword"])
def test_search_finds_a_product(http: requests.Session, urls: dict[str, str], query: str) -> None:
    """A product is found by a word of its name and by its keyword, and only that product."""
    assert hits(http, urls, query=query) == [f"Paspoort {PASPOORT}"]


@pytest.mark.tc("OI-093", "OI-095")
def test_results_filter_on_onderwerp(http: requests.Session, urls: dict[str, str], categories: dict[str, str]) -> None:
    """Both products match; filtering on an onderwerp (category) keeps only that onderwerp's product."""
    assert hits(http, urls, query=BOTH) == [f"Grofvuil {GROFVUIL}", f"Paspoort {PASPOORT}"]
    afval = categories[f"Afval {SUFFIX}"]
    assert hits(http, urls, query=BOTH, categories=afval) == [f"Grofvuil {GROFVUIL}"]


@pytest.mark.tc("OI-094")
def test_feedback_on_a_search_is_stored(
    http: requests.Session, urls: dict[str, str], podiumd_env: Environment, run_tag: str, categories: dict[str, str]
) -> None:
    """Feedback given on a results page is kept with the search it was given on."""
    del categories  # results to give feedback on
    search = f"{urls['openinwoner']}/search/?query={PASPOORT}"
    page = expect_status(http.get(search), HTTPStatus.OK).text
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
    assert token, "no feedback form on the results page"
    remark = f"{run_tag}-zoeken nuttig"
    form = {"csrfmiddlewaretoken": token[1], "positive": "true", "remark": remark}
    expect_status(http.post(search, data=form, headers={"Referer": search}), HTTPStatus.OK)
    stored = search_data(podiumd_env, "feedback", f"{run_tag}-zoeken")["feedback"]
    assert [(f["positive"], f["remark"]) for f in stored] == [(True, remark)]
    assert PASPOORT in stored[0]["query"]


@pytest.mark.tc("OI-097")
@pytest.mark.usefixtures("categories")
@pytest.mark.xfail(
    strict=True,
    reason="Open Inwoner offers no 'did you mean': a search without hits shows fixed tips only; its"
    " fuzzy matching lives in the autocomplete, not on the results page",
)
def test_no_results_suggest_what_was_meant(http: requests.Session, urls: dict[str, str]) -> None:
    """A misspelt search without hits suggests the product that was probably meant."""
    html = expect_status(http.get(urls["openinwoner"] + "/search/", params={"query": "Pasport"}), HTTPStatus.OK).text
    assert "We konden geen zoekresultaten vinden" in html
    assert PASPOORT in html


@pytest.mark.tc("OI-098", "OI-099")
def test_search_can_be_switched_off(http: requests.Session, urls: dict[str, str], podiumd_env: Environment) -> None:
    """With search switched off in the admin, the search page and links to it answer 404, and the form is gone."""
    old = set_site_configuration(podiumd_env, search_enabled=False)
    try:
        expect_status(http.get(urls["openinwoner"] + "/search/", params={"query": PASPOORT}), HTTPStatus.NOT_FOUND)
        assert 'id="search-form"' not in expect_status(http.get(urls["openinwoner"] + "/"), HTTPStatus.OK).text
    finally:
        set_site_configuration(podiumd_env, **old)
