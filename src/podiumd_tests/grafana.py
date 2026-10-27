"""Grafana API and its datasource proxy: metrics and logs without direct access to Prometheus or Loki."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.components import COMPONENTS
from podiumd_tests.components import deployed_components
from podiumd_tests.json_data import JsonObject
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import parse_duration

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Sequence

    import requests

    from podiumd_tests.credentials import SecretResolver

type Json = dict[str, object]

# kubectl kind of a Prometheus Operator monitor and the scrape pool prefix Prometheus gives its targets.
MONITOR_POOLS = {"servicemonitors": "serviceMonitor", "podmonitors": "podMonitor"}
# A younger pod may not have been collected by Alloy yet.
MIN_POD_AGE = timedelta(minutes=10)


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
        response = expect_status(self.get(f"/api/datasources/proxy/uid/{uid}{path}", params), HTTPStatus.OK)
        return cast("Json", response.json())


def grafana_auth(credentials: SecretResolver) -> tuple[str, str] | None:
    """Basic auth from the secrets grafana_username and grafana_password; None for anonymous access."""
    username = credentials.optional("grafana_username")
    password = credentials.optional("grafana_password")
    return (username, password) if username and password else None


def _active_targets(targets_response: JsonObject) -> list[JsonObject]:
    return entries(section(targets_response, "data").get("activeTargets"))


def down_targets(targets_response: JsonObject, prometheus_age: timedelta) -> list[str]:
    """Prometheus scrape targets that are down, as "job url: error", from a /api/v1/targets body.

    A target not scraped yet (health "unknown") counts as down only once Prometheus has run longer than its scrape
    interval plus timeout: after a restart, a PodMonitor with a 5m interval stays unknown for up to 5 minutes.
    """
    return [
        f"{section(t, 'labels').get('job')} {t.get('scrapeUrl')}: {t.get('lastError') or t.get('health')}"
        for t in _active_targets(targets_response)
        if t.get("health") == "down" or (t.get("health") != "up" and prometheus_age > _first_scrape_due(t))
    ]


def _first_scrape_due(target: JsonObject) -> timedelta:
    return parse_duration(str(target.get("scrapeInterval"))) + parse_duration(str(target.get("scrapeTimeout")))


def target_count(targets_response: JsonObject) -> int:
    """Number of active scrape targets in a /api/v1/targets body."""
    return len(_active_targets(targets_response))


def monitors_without_targets(monitors: Sequence[str], targets_response: JsonObject) -> list[str]:
    """Monitors, as "<scrape pool prefix>/<namespace>/<name>", without an active target in a /api/v1/targets body."""
    pools = {str(t.get("scrapePool")) for t in _active_targets(targets_response)}
    return [m for m in monitors if not any(p.startswith(f"{m}/") for p in pools)]


def otel_jobs_query(components: Iterable[str]) -> str:
    """PromQL for the jobs of the components' OTEL services; remote write sets job to [<namespace>/]<service.name>.

    An app may name its processes <service>-<role> (Open Inwoner: openinwoner-web, openinwoner-celery-worker).
    """
    services = sorted(COMPONENTS[c].otel_service for c in components if COMPONENTS[c].otel_service)
    return f'group by (job) ({{job=~"(.+/)?({"|".join(services)})(-.+)?"}})'


def _has_otel_job(service: str, jobs: set[str]) -> bool:
    return any(job == service or job.startswith(f"{service}-") for job in jobs)


def without_metrics(
    components: Iterable[str], targets_response: JsonObject, otel_response: JsonObject
) -> tuple[list[str], list[str]]:
    """Monitored and OTEL components without series, from a /api/v1/targets body and an otel_jobs_query result.

    A monitored component needs a ServiceMonitor or PodMonitor named like one of its workloads with a target up.
    """
    pools = [str(t.get("scrapePool")).split("/") for t in _active_targets(targets_response) if t.get("health") == "up"]
    up = deployed_components([p[2] for p in pools if len(p) > 2 and p[0] in MONITOR_POOLS.values()])
    results = entries(section(otel_response, "data").get("result"))
    jobs = {str(section(r, "metric").get("job")).rpartition("/")[2] for r in results}
    ordered = sorted(components)
    return (
        [c for c in ordered if COMPONENTS[c].monitored and c not in up],
        [c for c in ordered if COMPONENTS[c].otel_service and not _has_otel_job(COMPONENTS[c].otel_service, jobs)],
    )


def pods_in_loki(query_response: JsonObject) -> set[tuple[str, str]]:
    """(namespace, pod) of each series in a Loki `sum by (namespace, pod)` query result."""
    metrics = (section(r, "metric") for r in entries(section(query_response, "data").get("result")))
    return {(str(m.get("namespace")), str(m.get("pod"))) for m in metrics}


def running_pods_not_in_loki(
    pods: Sequence[JsonObject], in_loki: set[tuple[str, str]], now: datetime
) -> list[JsonObject]:
    """Running pods older than MIN_POD_AGE that have no log lines in Loki."""
    return [
        p
        for p in pods
        if section(p, "status").get("phase") == "Running"
        and now - datetime.fromisoformat(str(section(p, "metadata").get("creationTimestamp"))) >= MIN_POD_AGE
        and (str(section(p, "metadata").get("namespace")), str(section(p, "metadata").get("name"))) not in in_loki
    ]
