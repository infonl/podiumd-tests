"""Grafana API and its datasource proxy: metrics and logs without direct access to Prometheus or Loki."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    import requests

type Json = dict[str, object]


class GrafanaError(AssertionError):
    """Grafana or a datasource behind it did not answer as expected. An AssertionError for pytest."""


class Grafana:
    """Calls to Grafana; datasources are found by type, as their names differ per estate."""

    def __init__(self, http: requests.Session, base: str, auth: tuple[str, str] | None = None) -> None:
        self.http = http
        self.base = base
        self.auth = auth
        self.datasources: list[Json] = []

    def get(self, path: str, params: dict[str, str] | None = None) -> requests.Response:
        """GET a Grafana path."""
        return self.http.get(self.base + path, params=params, auth=self.auth)

    def load_datasources(self) -> requests.Response:
        """Fetch the datasource list; returns the response so callers can tell a login problem apart."""
        response = self.get("/api/datasources")
        if response.ok:
            self.datasources = cast("list[Json]", response.json())
        return response

    def uid(self, kind: str) -> str | None:
        """uid of the first datasource of a type (prometheus, loki, tempo), or None."""
        return next((str(d["uid"]) for d in self.datasources if d.get("type") == kind), None)

    def proxy(self, kind: str, path: str, params: dict[str, str] | None = None) -> Json:
        """GET through the proxy of the datasource of a type; the JSON body."""
        uid = self.uid(kind)
        if uid is None:
            msg = f"no {kind} datasource"
            raise GrafanaError(msg)
        response = self.get(f"/api/datasources/proxy/uid/{uid}{path}", params)
        if response.status_code != 200:
            msg = f"{kind}{path}: HTTP {response.status_code}"
            raise GrafanaError(msg)
        return cast("Json", response.json())


def down_targets(targets_response: Mapping[str, object]) -> list[str]:
    """Prometheus scrape targets that are not up, as "job url: error", from a /api/v1/targets body."""
    data = cast("Json", targets_response.get("data") or {})
    targets = cast("list[Json]", data.get("activeTargets") or [])
    return [
        f"{cast('Json', t.get('labels') or {}).get('job')} {t.get('scrapeUrl')}: {t.get('lastError')}"
        for t in targets
        if t.get("health") != "up"
    ]


def target_count(targets_response: Mapping[str, object]) -> int:
    """Number of active scrape targets in a /api/v1/targets body."""
    data = cast("Json", targets_response.get("data") or {})
    return len(cast("list[Json]", data.get("activeTargets") or []))
