"""A hot zaak: --perf-users users link new documents to one zaak without pause, HOT_ZAAK_LINKS links in all.

Open Zaak #2577: before 1.31.1 each new zaakinformatieobject recalculated the ETags of the whole zaak, so a link
took longer the more documents the zaak had, and concurrent links deadlocked (500; from 1.31.1 503 with Retry-After).
Locust's stats split the links per HOT_ZAAK_BUCKET (stats.labelled), so the first links compare with the last.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.config import REPO_ROOT
from podiumd_tests.perf.availability import Watch
from podiumd_tests.perf.availability import availability_limits
from podiumd_tests.perf.availability import watched
from podiumd_tests.perf.availability_report import problems
from podiumd_tests.perf.availability_report import report
from podiumd_tests.perf.runs import HOT_ZAAK
from podiumd_tests.perf.runs import HOT_ZAAK_BUCKET
from podiumd_tests.perf.runs import HOT_ZAAK_LINKS
from podiumd_tests.perf.runs import locust_command
from podiumd_tests.perf.stats import FAILURES
from podiumd_tests.perf.stats import HISTORY
from podiumd_tests.perf.stats import STATS
from podiumd_tests.perf.stats import EndpointStats
from podiumd_tests.perf.stats import by_label
from podiumd_tests.perf.stats import locust_csv
from podiumd_tests.perf.stats import read_failures
from podiumd_tests.perf.stats import read_stats
from podiumd_tests.perf.stats import slowdown_limit
from podiumd_tests.perf.stats import summed
from podiumd_tests.perf.stats import thresholds
from podiumd_tests.perf.stats import violations
from podiumd_tests.process import run_checked
from podiumd_tests.process import run_process
from podiumd_tests.seed.openzaak import delete_zaak_at_cleanup
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.registry import ResourceRegistry

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator
    from pathlib import Path

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

pytestmark = [
    pytest.mark.perf,
    pytest.mark.requires("openzaak"),
    pytest.mark.source(
        "upstream open-zaak/open-zaak issue 2577",
        "Den Haag's hot zaak: adding documents to a zaak got slower the more it had, and concurrent adds deadlocked.",
    ),
]

LOCUSTFILE = REPO_ROOT / "src" / "podiumd_tests" / "perf" / "locustfile.py"
# A cap: Locust stops once the links are made.
RUN_TIME = "10m"
PREFIX = "hot-zaak"
# Open Zaak 1.29.3 took over 30 s to delete a zaak with 400 documents: requests time out, the delete completes.
DELETE_TIMEOUT = 600
# The link stats per bucket of HOT_ZAAK_BUCKET, Locust's failures CSV and the availability of Open Zaak.
type HotZaak = tuple[dict[int, EndpointStats], str, Watch]


@pytest.fixture(scope="module", name="module_registry")
def fixture_module_registry(request: pytest.FixtureRequest, run_tag: str) -> Iterator[ResourceRegistry]:
    """Cleanup at the end of the module, for the hot zaak and its documents."""
    registry = ResourceRegistry(run_tag, keep=bool(request.config.getoption("--keep-data")))
    try:
        yield registry
    finally:
        registry.cleanup()


@pytest.fixture(scope="module", name="hot_zaak")
def fixture_hot_zaak(
    request: pytest.FixtureRequest,
    module_registry: ResourceRegistry,
    podiumd_env: Environment,
    urls: dict[str, str],
    openzaak: ApiClient,
    test_zaaktype: JsonObject,
    perf_dir: Path,
    run_tag: str,
) -> HotZaak:
    """The hot zaak's Locust run; cleanup deletes the zaak with its documents."""
    zaak = str(make_zaak(openzaak, module_registry, str(test_zaaktype["url"]))["url"])
    delete_zaak_at_cleanup(openzaak, module_registry, zaak, with_documents=True, timeout=DELETE_TIMEOUT)
    prefix = perf_dir / PREFIX
    users = str(request.config.getoption("--perf-users"))
    command = locust_command(LOCUSTFILE, users, RUN_TIME, prefix, podiumd_env.profile.name, urls=urls)
    command += ["--podiumd-run-tag", run_tag, "--podiumd-zaak", zaak, "HotZaakUser"]
    with watched(podiumd_env, urls, ["openzaak"], availability_limits(REPO_ROOT / "perf.yaml")) as watch:
        run_checked(run_process, command, timeout=900)
    stats = read_stats(locust_csv(prefix, STATS).read_text(encoding="utf-8"))
    failures = locust_csv(prefix, FAILURES).read_text(encoding="utf-8")
    return {number: found[HOT_ZAAK] for number, found in by_label(stats).items()}, failures, watch


def _failures(failures_csv: str) -> str:
    return "\n".join(f"- {count}x {name}: {error}" for name, error, count in read_failures(failures_csv))


@pytest.mark.scenario("""
    Given several users add new documents to the same zaak at the same time
    When hundreds of documents have been added
    Then nearly every addition succeeded, and none answered a server error
    And the 95th percentile time of an addition stays within its threshold
""")
def test_hot_zaak_links_succeed(hot_zaak: HotZaak, record_property: Callable[[str, object], None]) -> None:
    """The links' failure ratio and p95 stay within perf.yaml, without a 500; the failures by error go to the report."""
    buckets, failures, _watch = hot_zaak
    record_property("report", _failures(failures) or "No failed links.")
    total = summed(buckets.values())
    # Locust's stop drops the links still in progress.
    reached = max(buckets, default=0) + HOT_ZAAK_BUCKET
    assert reached >= HOT_ZAAK_LINKS, f"{total.requests} of {HOT_ZAAK_LINKS} links made in {RUN_TIME}"
    found = violations(total, thresholds(REPO_ROOT / "perf.yaml", HOT_ZAAK))
    server_errors = sum(count for _name, error, count in read_failures(failures) if "HTTP 500" in error)
    if server_errors:
        found.append(f"{server_errors} links answered 500")
    assert found == []


@pytest.mark.scenario("""
    Given several users add new documents to the same zaak at the same time
    When the zaak has hundreds of documents
    Then adding a document takes no longer than when the zaak had few
""")
def test_hot_zaak_links_do_not_slow_down(hot_zaak: HotZaak, record_property: Callable[[str, object], None]) -> None:
    """The p95 of the last bucket of links is no slowdown (stats.slowdown_limit) against the first bucket's."""
    buckets = hot_zaak[0]
    rows = [
        f"| {n + 1}-{n + HOT_ZAAK_BUCKET} | {s.requests} | {s.failures} | {s.p95_ms:.0f} |" for n, s in buckets.items()
    ]
    record_property("report", "\n".join(["| Links | Requests | Failed | p95 ms |", "|---|---|---|---|", *rows]))
    assert len(buckets) > 1, f"links in {len(buckets)} bucket: too few to compare"
    first, last = buckets[min(buckets)], buckets[max(buckets)]
    limit = slowdown_limit(thresholds(REPO_ROOT / "perf.yaml", HOT_ZAAK), first.p95_ms)
    assert last.p95_ms <= limit, (
        f"p95 of the last links {last.p95_ms:.0f} ms > {limit:.0f} ms (first {first.p95_ms:.0f})"
    )


@pytest.mark.scenario("""
    Given several users add new documents to the same zaak at the same time
    When the additions end
    Then Open Zaak did not restart, is ready again and answered its health check during the load
""")
def test_hot_zaak_keeps_open_zaak_available(
    hot_zaak: tuple[dict[int, EndpointStats], str, Watch],
    perf_dir: Path,
    record_property: Callable[[str, object], None],
) -> None:
    """Open Zaak stays within perf.yaml's availability limits; the timeline goes to summary.md."""
    watch = hot_zaak[2]
    record_property("report", report(watch, locust_csv(perf_dir / PREFIX, HISTORY).read_text(encoding="utf-8")))
    assert problems(watch) == []
