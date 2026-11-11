"""Bootstrap step runner: test-only credentials and wiring, all named ptest-bootstrap-*.

Each Step is idempotent and reversible. `bootstrap` applies the steps whose
capabilities the environment has, `unbootstrap` removes them in reverse
order, and `check` tells whether they are in place (fixture bootstrap_ok).
Credentials a step creates go to the credentials Secret only.
"""

from __future__ import annotations

import time

from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from threading import Lock
from typing import TYPE_CHECKING
from typing import Literal
from typing import Protocol
from typing import runtime_checkable

import requests

from podiumd_tests.auth.keycloak import TokenError
from podiumd_tests.capabilities import CLUSTER
from podiumd_tests.credential_store import CredentialStore
from podiumd_tests.credentials import SecretError
from podiumd_tests.django_snippets import try_snippets
from podiumd_tests.process import ProcessError

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from podiumd_tests.config import Profile
    from podiumd_tests.django_snippets import SnippetCall
    from podiumd_tests.environment import Environment

Action = Literal["created", "present", "removed", "absent", "skipped", "missing", "failed"]
_STEP_ERRORS = (
    ProcessError,
    SecretError,
    TokenError,
    AssertionError,
    LookupError,
    ValueError,
    requests.RequestException,
)


@dataclass(frozen=True)
class Context:
    """What a step works with."""

    env: Environment
    store: CredentialStore
    # What a step wants the user to know, e.g. roles the realm lacks; shown in the step's outcome.
    notes: list[str] = field(default_factory=list[str])


class Step(Protocol):
    """One reversible piece of bootstrap."""

    @property
    def name(self) -> str:
        """Short name for output, e.g. "openzaak-client"."""
        ...

    @property
    def requires(self) -> tuple[str, ...]:
        """Capabilities the step needs; it is skipped without them."""
        ...

    @property
    def wiring(self) -> bool:  # noqa: FNE005  # Step protocol member, the wiring field of every step dataclass
        """True for platform wiring: skipped unless the profile allows wiring."""
        ...

    def is_present(self, ctx: Context, /) -> bool:
        """Return True when the step's objects and stored credentials are in place."""
        ...

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Create the step's objects (replacing stale ones); return credentials to store."""
        ...

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the step's objects; return the credential keys to drop from the store."""
        ...


@runtime_checkable
class SnippetChecks(Step, Protocol):
    """Optional Step methods of a step checked by a Django snippet: one shell for check and apply, batched status."""

    def ensure(self, ctx: Context, /) -> dict[str, str] | None:
        """Apply unless is_present; return the credentials to store, None when present."""
        ...

    def status_call(self, ctx: Context, /) -> tuple[str, SnippetCall] | None:
        """Return is_present's snippet call and its deployment; None when is_present needs no shell."""
        ...

    def is_present_in(self, ctx: Context, status: object, /) -> bool:
        """Return is_present for the result of status_call."""
        ...


type _Calls = list[tuple[SnippetChecks, SnippetCall]]


@dataclass(frozen=True)
class Outcome:
    """What happened to one step."""

    step: str
    action: Action
    detail: str = ""
    seconds: float = 0


def refusal(profile: Profile) -> str | None:
    """Why bootstrap may not run on this environment, or None: smoke-only environments stay untouched."""
    if profile.is_smoke_only:
        return f"{profile.name} is smoke-only (allowed_tiers: {', '.join(profile.allowed_tiers)}); bootstrap changes it"
    return None


def not_allowed(ctx: Context, step: Step) -> str | None:
    """Why the profile does not allow the step (an opt-in setting is off), or None.

    Optional on a step: one without `not_allowed` is always allowed. check and bootstrap then report the step
    as skipped, so a test that needs it skips with the reason; unbootstrap still removes what an earlier run set.
    """
    reason = getattr(step, "not_allowed", None)
    if not callable(reason):
        return None
    found = reason(ctx)
    return str(found) if found else None


# Steps run at the same time when they share no component; more would mostly queue on the cluster's CPU.
PARALLEL_STEPS = 4


def _each(env: Environment, steps: Sequence[Step], act: Callable[[Context, Step], Outcome]) -> list[Outcome]:
    """Run act on every step the environment has the capabilities for; skip the others with a reason.

    A step waits for every earlier step that shares a component with it; the others run in parallel.
    Outcomes come back in the order of steps.
    """
    store = CredentialStore(env.kube)

    def run(step: Step) -> Outcome:
        reason = _skip_reason(env, step)
        if reason:
            return Outcome(step.name, "skipped", reason)
        started = time.monotonic()
        try:
            outcome = act(Context(env, store), step)
        except _STEP_ERRORS as exc:
            # One broken step must not stop the others, least of all during unbootstrap.
            outcome = Outcome(step.name, "failed", str(exc))
        return replace(outcome, seconds=time.monotonic() - started)

    return in_dependency_order(steps, run, PARALLEL_STEPS)


def _components(step: Step) -> set[str]:
    return set(step.requires) - {CLUSTER}


def in_dependency_order(steps: Sequence[Step], run: Callable[[Step], Outcome], workers: int) -> list[Outcome]:
    """Run each step once all earlier steps sharing a component with it are done; the outcomes in step order."""
    after = [
        {earlier for earlier in range(index) if _components(steps[earlier]) & _components(step)}
        for index, step in enumerate(steps)
    ]
    outcomes: dict[int, Outcome] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        running: dict[Future[Outcome], int] = {}
        waiting = list(range(len(steps)))
        while waiting or running:
            ready = [pending for pending in waiting if after[pending] <= outcomes.keys()]
            for index in ready:
                waiting.remove(index)
                running[pool.submit(run, steps[index])] = index
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in finished:
                outcomes[running.pop(future)] = future.result()
    return [outcomes[index] for index in range(len(steps))]


def _skip_reason(env: Environment, step: Step) -> str | None:
    if step.wiring and not env.profile.wiring:
        return f"wiring is off for {env.profile.name} (profile bootstrap.wiring)"
    return env.capabilities.skip_reason(CLUSTER, *step.requires)


class _Statuses:
    """is_present of snippet steps from one Django shell per deployment, until a step may have changed something.

    A status can depend on what an earlier step creates (a group, a zaaktype, a stored secret), so once a step
    is created or fails, the remaining steps check themselves again.
    """

    def __init__(self, steps: Sequence[Step]) -> None:
        self._lock: Lock = Lock()  # steps ask from parallel threads
        self._steps: Sequence[Step] = steps
        # Per step name: its deployment and the status calls of that deployment's steps.
        self._batches: dict[str, tuple[str, _Calls]] | None = None
        self._present: dict[str, bool] = {}
        self._valid: bool = True

    def is_present(self, ctx: Context, step: Step) -> bool | None:
        """Return is_present of the step from its deployment's batch; None when no batch has it."""
        if not self._valid or not isinstance(step, SnippetChecks):
            return None
        with self._lock:
            return self._is_present_in_batch(ctx, step) if self._valid else None

    def invalidate(self) -> None:
        """Forget the batches: a step may have changed what the remaining ones check."""
        self._valid = False

    def _is_present_in_batch(self, ctx: Context, step: SnippetChecks) -> bool | None:
        if self._batches is None:
            self._batches = _batches(ctx, self._steps)
        batch = self._batches.get(step.name)
        if batch:
            deployment, calls = batch
            for member, _ in calls:
                self._batches.pop(member.name)
            self._present.update(_batch_status(ctx, deployment, calls))
        return self._present.get(step.name)


def _batches(ctx: Context, steps: Sequence[Step]) -> dict[str, tuple[str, _Calls]]:
    """Return per step name its deployment and that deployment's status calls; only deployments with several."""
    calls: defaultdict[str, _Calls] = defaultdict(list)
    checked = (step for step in steps if isinstance(step, SnippetChecks))
    for step in checked:
        found = _status_call(ctx, step)
        if found:
            calls[found[0]].append((step, found[1]))
    several = {deployment: group for deployment, group in calls.items() if len(group) > 1}
    return {step.name: (deployment, group) for deployment, group in several.items() for step, _ in group}


def _status_call(ctx: Context, step: SnippetChecks) -> tuple[str, SnippetCall] | None:
    """Return the step's status call; None when it will not run, needs no shell or fails (it reports that itself)."""
    if _skip_reason(ctx.env, step):
        return None
    with suppress(*_STEP_ERRORS):
        return None if not_allowed(ctx, step) else step.status_call(ctx)
    return None


def _batch_status(ctx: Context, deployment: str, calls: _Calls) -> dict[str, bool]:
    """Return is_present per step name from one Django shell; empty when it failed, so each step checks itself."""
    statuses = try_snippets(ctx.env.kube, deployment, [call for _, call in calls])
    present: dict[str, bool] = {}
    for (step, _), status in zip(calls, statuses or [], strict=False):
        with suppress(*_STEP_ERRORS):  # the step reports it when it runs
            present[step.name] = step.is_present_in(ctx, status)
    return present


def has_failure(outcomes: Sequence[Outcome]) -> bool:
    """Return True when any step failed."""
    return any(outcome.action == "failed" for outcome in outcomes)


def bootstrap(env: Environment, steps: Sequence[Step], *, rotate: bool = False) -> list[Outcome]:
    """Apply every applicable step that is not in place (all of them with rotate)."""
    statuses = _Statuses(steps)

    def apply(ctx: Context, step: Step) -> Outcome:
        reason = not_allowed(ctx, step)
        if reason:
            return Outcome(step.name, "skipped", reason)
        try:
            values = _apply_missing(ctx, step, statuses, rotate=rotate)
        except _STEP_ERRORS:
            statuses.invalidate()
            raise
        if values is None:
            return Outcome(step.name, "present")
        statuses.invalidate()
        if values:
            ctx.store.write(values)
            ctx.env.credentials.forget(*values)
        stored = ", ".join(sorted(values))
        return Outcome(step.name, "created", "; ".join([stored, *ctx.notes]))

    return _each(env, steps, apply)


def _apply_missing(ctx: Context, step: Step, statuses: _Statuses, *, rotate: bool) -> dict[str, str] | None:
    """Apply the step unless it is present (always with rotate); the credentials to store, None when present."""
    present = False if rotate else statuses.is_present(ctx, step)
    if present is None and not isinstance(step, SnippetChecks):
        present = step.is_present(ctx)
    if present:
        return None
    ctx.notes.clear()
    if present is None and isinstance(step, SnippetChecks):
        return step.ensure(ctx)
    return step.apply(ctx)


def unbootstrap(env: Environment, steps: Sequence[Step]) -> list[Outcome]:
    """Remove every applicable step, in reverse order."""

    def remove(ctx: Context, step: Step) -> Outcome:
        present = step.is_present(ctx)
        keys = step.remove(ctx)
        if keys:
            ctx.store.remove(*keys)
            ctx.env.credentials.forget(*keys)
        return Outcome(step.name, "removed" if present else "absent")

    return _each(env, list(reversed(steps)), remove)


def check(env: Environment, steps: Sequence[Step]) -> list[Outcome]:
    """Whether every applicable step is in place; changes nothing."""
    statuses = _Statuses(steps)

    def present(ctx: Context, step: Step) -> Outcome:
        reason = not_allowed(ctx, step)
        if reason:
            return Outcome(step.name, "skipped", reason)
        found = statuses.is_present(ctx, step)
        if found is None:
            found = step.is_present(ctx)
        return Outcome(step.name, "present" if found else "missing")

    return _each(env, steps, present)


def outcome_report(outcomes: Sequence[Outcome]) -> str:
    """One line per step for the terminal, with its seconds, and the total."""
    width = max([len("total"), *(len(outcome.step) for outcome in outcomes)])
    lines = [
        _report_line(outcome.action, outcome.step.ljust(width), outcome.seconds, outcome.detail) for outcome in outcomes
    ]
    lines.append(_report_line("", "total".ljust(width), sum(outcome.seconds for outcome in outcomes)))
    return "\n".join(line.rstrip() for line in lines)


def _report_line(action: str, step: str, seconds: float, detail: str = "") -> str:
    return f"{action:8} {step} {seconds:6.1f}s  {detail}"
