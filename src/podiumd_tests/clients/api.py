"""A JSON API client: base URL, auth headers, expected statuses, pagination."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.json_data import JsonObject

MAX_PAGES = 50


class ApiClient:
    """Calls to one API root; every call checks its status (UnexpectedStatusError).

    headers is a dict, or a function that returns them per request (e.g. a fresh ZGW token).
    """

    def __init__(
        self, http: requests.Session, base_url: str, headers: dict[str, str] | Callable[[], dict[str, str]]
    ) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._headers = headers

    def url(self, path: str) -> str:
        """Absolute URL of a path below the API root; absolute URLs pass unchanged."""
        return path if path.startswith(("http://", "https://")) else f"{self.base_url}/{path.lstrip('/')}"

    def headers(self) -> dict[str, str]:
        """The headers for the next request."""
        return self._headers() if callable(self._headers) else self._headers

    def request(self, method: str, path: str, *expected: int, **kwargs: object) -> requests.Response:
        """Send a request; UnexpectedStatusError unless its status is one of expected."""
        response = self.http.request(method, self.url(path), headers=self.headers(), **kwargs)  # pyright: ignore[reportArgumentType]
        return expect_status(response, *expected)

    def get(self, path: str, params: dict[str, str] | None = None) -> JsonObject:
        """GET a JSON object."""
        return cast("JsonObject", self.request("GET", path, HTTPStatus.OK, params=params).json())

    def post(self, path: str, body: object) -> JsonObject:
        """POST JSON; the created object."""
        return cast("JsonObject", self.request("POST", path, HTTPStatus.CREATED, json=body).json())

    def patch(self, path: str, body: object) -> JsonObject:
        """PATCH JSON; the updated object."""
        return cast("JsonObject", self.request("PATCH", path, HTTPStatus.OK, json=body).json())

    def delete(self, path: str) -> None:
        """DELETE; a resource that is already gone counts as deleted."""
        self.request("DELETE", path, HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND)

    def list(self, path: str, params: dict[str, str] | None = None) -> list[JsonObject]:
        """All results of a paginated list (ZGW style: results and next)."""
        found: list[JsonObject] = []
        page: JsonObject = self.get(path, params)
        for _ in range(MAX_PAGES):
            found += entries(page.get("results"))
            following = page.get("next")
            if not isinstance(following, str) or not following:
                return found
            page = self.get(following)
        msg = f"{self.url(path)}: more than {MAX_PAGES} pages"
        raise RuntimeError(msg)
