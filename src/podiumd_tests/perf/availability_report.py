"""What a perf.availability Watch shows: its problems against perf.yaml's limits, and its report with memory trends
and a timeline."""

from __future__ import annotations

import csv
import io

from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from itertools import chain
from itertools import groupby
from statistics import linear_regression
from typing import TYPE_CHECKING

from podiumd_tests.perf.availability import is_loaded

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Sequence

    from podiumd_tests.kubelet import ContainerKey
    from podiumd_tests.perf.availability import Sample
    from podiumd_tests.perf.availability import Series
    from podiumd_tests.perf.availability import Watch
    from podiumd_tests.perf.stats import EndpointStats

MIB = 1024 * 1024
# Seconds without failed requests that end a burst.
BURST_GAP_S = 5
QUIET = "No failed requests, failing root answers or pod changes."
# Lower CPU throttling shares would show as 0%.
SHOWN_SHARE = 0.005
# The report shows a container's RSS this many seconds apart.
TREND_STEP_S = 300
# Fewer RSS readings after the warm-up give no trend.
MIN_READINGS = 4


def availability(samples: Iterable[Sample]) -> dict[str, tuple[int, int]]:
    """Return (healthy, all) root samples per component."""
    ordered = sorted(samples, key=lambda sample: sample.component)
    grouped = groupby(ordered, key=lambda sample: sample.component)
    found: dict[str, tuple[int, int]] = {}
    for component, series in grouped:
        problems_seen = [sample.problem for sample in series]
        found[component] = (problems_seen.count(None), len(problems_seen))
    return found


def memory_ratios(watch: Watch) -> dict[ContainerKey, float]:
    """Return each container's peak RSS as a share of its memory limit; containers without one are left out."""
    found: dict[ContainerKey, float] = {}
    for key, peak in watch.rss.items():
        limit = watch.memory_limits.get(key)
        if limit:
            found[key] = peak / limit
    return found


def _container(key: ContainerKey) -> str:
    return f"{key[1]}/{key[2]}"


@dataclass(frozen=True)
class Trend:
    """A container's RSS during the load in MiB, and its growth in MiB per minute after the warm-up."""

    first: float
    last: float
    peak: float
    # The first reading at or after each TREND_STEP_S since the start of the load.
    steps: tuple[float, ...]
    growth: float
    # Growth in the last half of the time after the warm-up: whether it still grows at the end.
    late_growth: float


def growth_per_min(series: Series) -> float:
    """Return the least-squares growth of the readings in MiB per minute."""
    times, values = zip(*series, strict=True)
    return linear_regression(times, values).slope * 60 / MIB


def _steps(series: Series, started: float) -> tuple[float, ...]:
    found: list[float] = []
    due = started
    for at, value in series:
        if at >= due:
            found.append(value / MIB)
            due = at - (at - started) % TREND_STEP_S + TREND_STEP_S
    return tuple(found)


def memory_trend(series: Series, started: float, warmup_s: float) -> Trend | None:
    """Return the trend of the RSS readings of a load that started at `started` (Unix seconds).

    The warm-up starts with the load, or with the first reading of a container that started later. None when the
    readings after the warm-up span less than the warm-up itself, or either half of that time has too few readings.
    """
    warm = max(started, series[0][0]) + warmup_s
    window = [reading for reading in series if reading[0] >= warm]
    if len(window) < MIN_READINGS:
        return None
    first, last = window[0][0], window[-1][0]
    span = last - first
    late = [reading for reading in window if reading[0] >= first + span / 2]
    if span < max(warmup_s, 1) or len(late) < MIN_READINGS // 2:
        return None
    values = [value / MIB for _at, value in series]
    rss = (values[0], values[-1], max(values))
    return Trend(*rss, _steps(series, started), growth_per_min(window), growth_per_min(late))


def memory_trends(watch: Watch) -> dict[ContainerKey, Trend]:
    """Return the RSS trend of each container whose readings span enough time after perf.yaml's warm-up."""
    found: dict[ContainerKey, Trend] = {}
    for key, series in watch.rss_series.items():
        trend = memory_trend(series, watch.started, watch.limits.memory_warmup_s)
        if trend is not None:
            found[key] = trend
    return found


def capacity(watch: Watch, component: str, per_vcpu: float, measured: EndpointStats) -> str:
    """Return the measured rate and p95 against per_vcpu requests per second per vCPU of the component's CPU limits."""
    rate = f"{measured.per_second:.1f}/s at p95 {measured.p95_ms:.0f} ms; reference {per_vcpu:g}/s per vCPU"
    mine = frozenset((component,))
    limits = [limit for key, limit in watch.cpu_limits.items() if is_loaded(key[1], mine)]
    if not limits or None in limits:
        return f"{rate}; {component} has no CPU limit"
    cores = sum(limit for limit in limits if limit is not None)
    return f"{rate}, {per_vcpu * cores:.0f}/s for the {cores:g} vCPU of {component}'s CPU limits"


def problems(watch: Watch) -> list[str]:
    """Return what the load did that perf.yaml's availability limits forbid; empty when nothing."""
    limits = watch.limits
    found = [f"{disruption.text} during the load" for disruption in watch.disruptions]
    found += [f"{pod} not Ready {limits.recovery_s:g}s after the load" for pod in watch.unready]
    for component, (healthy, total) in sorted(availability(watch.samples).items()):
        if healthy < limits.min_available * total:
            found.append(f"{component} root healthy in {healthy} of {total} samples < {limits.min_available:.0%}")
    for key, ratio in sorted(memory_ratios(watch).items()):
        if ratio > limits.max_memory_ratio:
            peak = f"{_container(key)} peak RSS {watch.rss[key] / MIB:.0f} MiB"
            found.append(f"{peak} = {ratio:.0%} of its limit > {limits.max_memory_ratio:.0%}")
    growth_limit = limits.max_rss_growth_mib_per_min
    for key, trend in sorted(memory_trends(watch).items()):
        if min(trend.growth, trend.late_growth) > growth_limit:
            rates = f"{trend.growth:.1f} MiB/min after the warm-up, {trend.late_growth:.1f} in its last half"
            found.append(f"{_container(key)} RSS keeps growing: {rates} > {growth_limit:g}")
    return found


@dataclass(frozen=True)
class Event:
    """A line of the timeline: from start to end (Unix seconds; None: the cluster does not tell)."""

    start: float | None
    end: float | None
    text: str


@dataclass
class _Burst:
    start: int
    end: int
    failures: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def _new_failures(history_csv: str) -> list[tuple[int, str, int]]:
    """Return (second, endpoint, failures) from Locust's --csv-full-history; a dropping total is Locust's reset."""
    last: dict[str, int] = {}
    found: list[tuple[int, str, int]] = []
    for row in csv.DictReader(io.StringIO(history_csv)):
        name = row["Name"]
        if name == "Aggregated":
            continue
        total = int(row["Total Failure Count"])
        previous = last.get(name, 0)
        last[name] = total
        new = total if total < previous else total - previous
        if new:
            found.append((int(row["Timestamp"]), name, new))
    return found


def failure_bursts(history_csv: str) -> list[Event]:
    """Return the bursts of failed requests in Locust's --csv-full-history; BURST_GAP_S quiet seconds end one."""
    bursts: list[_Burst] = []
    for second, name, count in _new_failures(history_csv):
        if not bursts or second - bursts[-1].end > BURST_GAP_S:
            bursts.append(_Burst(second, second))
        bursts[-1].end = second
        bursts[-1].failures[name] += count
    return [Event(burst.start, burst.end, _failed_text(burst.failures)) for burst in bursts]


def _failed_text(counts: dict[str, int]) -> str:
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    endpoints = ", ".join(f"{name} {count}" for name, count in ordered)
    return f"{sum(counts.values())} failed requests ({endpoints})"


def _runs(series: Sequence[Sample]) -> list[list[Sample]]:
    """Split one component's samples into its series of failing samples."""
    runs: list[list[Sample]] = [[]]
    for sample in series:
        if sample.problem is None:
            runs.append([])
        else:
            runs[-1].append(sample)
    return [run for run in runs if run]


def unhealthy_runs(samples: Iterable[Sample]) -> list[Event]:
    """Return each series of failing root samples of a component, ended by a healthy one."""
    ordered = sorted(samples, key=lambda sample: (sample.component, sample.at))
    found: list[Event] = []
    for component, series in groupby(ordered, key=lambda sample: sample.component):
        for run in _runs(list(series)):
            answers = ", ".join(sorted({str(sample.problem) for sample in run}))
            text = f"{component} root: {answers} in {len(run)} samples"
            found.append(Event(run[0].at, run[-1].at, text))
    return found


def _iso_seconds(timestamp: str) -> float | None:
    return datetime.fromisoformat(timestamp).timestamp() if timestamp else None


def timeline(watch: Watch, history_csv: str) -> list[Event]:
    """Return failed-request bursts, failing root samples and pod changes, in time order; untimed ones last."""
    changes = ((_iso_seconds(disruption.at), disruption.text) for disruption in watch.disruptions)
    events = [*failure_bursts(history_csv), *unhealthy_runs(watch.samples)]
    events += [Event(at, at, text) for at, text in changes]
    return sorted(events, key=lambda event: (event.start is None, event.start or 0))


def _clock(seconds: float | None) -> str:
    return "?" if seconds is None else datetime.fromtimestamp(seconds, UTC).strftime("%H:%M:%S")


def _span(event: Event) -> str:
    start, end = _clock(event.start), _clock(event.end)
    return start if start == end else f"{start}-{end}"


def _highest_share(watch: Watch, mine: list[ContainerKey]) -> str:
    ratios = memory_ratios(watch)
    peak = max(((ratios[key], key) for key in mine if key in ratios), default=None)
    if peak is None:
        return "-"
    ratio, key = peak
    return f"{ratio:.0%} ({_container(key)})"


def _largest(watch: Watch, mine: list[ContainerKey]) -> str:
    sets = watch.working_set
    largest = max(((sets[key], key) for key in mine if key in sets), default=None)
    if largest is None:
        return "-"
    peak, key = largest
    unlimited = ", no limit" if watch.memory_limits.get(key, 0) is None else ""
    return f"{peak / MIB:.0f} MiB ({_container(key)}{unlimited})"


def _component_rows(watch: Watch) -> list[str]:
    counts = availability(watch.samples)
    rows = ["| Component | Healthy root answers | Highest RSS share of a memory limit | Largest working set |"]
    rows.append("|---|---|---|---|")
    for component in sorted(watch.components):
        healthy, total = counts.get(component, (0, 0))
        only = frozenset((component,))
        measured = watch.working_set.keys() | watch.rss.keys()
        mine = [key for key in measured if is_loaded(key[1], only)]
        memory = f"{_highest_share(watch, mine)} | {_largest(watch, mine)}"
        rows.append(f"| {component} | {healthy}/{total} | {memory} |")
    return rows


def _fastest_first(item: tuple[ContainerKey, Trend]) -> tuple[float, ContainerKey]:
    return -item[1].growth, item[0]


def _trend_rows(watch: Watch) -> list[str]:
    trends = sorted(memory_trends(watch).items(), key=_fastest_first)
    if not trends:
        return []
    warmup = f"after a warm-up of {watch.limits.memory_warmup_s:g} s"
    every = f"Every {TREND_STEP_S // 60} min"
    header = f"| Container | Start | End | Peak | Growth MiB/min | In its last half | {every} |"
    rows = ["", f"RSS in MiB; growth {warmup}, least squares.", "", header, "|---|---|---|---|---|---|---|"]
    for key, trend in trends:
        rss = f"{trend.first:.0f} | {trend.last:.0f} | {trend.peak:.0f}"
        growth = f"{trend.growth:+.2f} | {trend.late_growth:+.2f}"
        steps = " ".join(f"{step:.0f}" for step in trend.steps)
        rows.append(f"| {_container(key)} | {rss} | {growth} | {steps} |")
    return rows


def _remarks(watch: Watch) -> list[str]:
    shares_by_key = watch.throttled.items()
    throttled = sorted(((share, key) for key, share in shares_by_key if share >= SHOWN_SHARE), reverse=True)
    no_limit = sorted(_container(key) for key, limit in watch.memory_limits.items() if limit is None)
    shares = ", ".join(f"{_container(key)} {share:.0%}" for share, key in throttled)
    found = [f"CPU throttled (share of CFS periods): {shares}."] if throttled else []
    found += [f"No memory limit: {', '.join(no_limit)}."] if no_limit else []
    found += [f"Not Ready before the load: {', '.join(watch.unready_before)}."] if watch.unready_before else []
    return found + [f"Not measured: {note}." for note in watch.notes]


def report(watch: Watch, history_csv: str) -> str:
    """Return the Markdown report of the watch: per component, the memory trends, then the timeline and remarks."""
    recovery = "not all Ready again"
    if watch.recovered_s is not None:
        recovery = f"Ready again {watch.recovered_s:.0f} s after it"
    load = f"{_clock(watch.started)}-{_clock(watch.ended)}"
    lines = [f"Load {load} UTC; {recovery}.", "", *_component_rows(watch), *_trend_rows(watch)]
    events = timeline(watch, history_csv)
    lines += ["", "| Time (UTC) | Event |", "|---|---|"] if events else ["", QUIET]
    lines += [f"| {_span(event)} | {event.text} |" for event in events]
    remarks = chain.from_iterable(("", remark) for remark in _remarks(watch))
    return "\n".join([*lines, *remarks])
