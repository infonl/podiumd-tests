"""Environment bootstrap: test-only credentials and wiring, all named ptest-bootstrap-* (PLAN.md §4 A, §11a).

Each Step is idempotent and reversible. `bootstrap` applies the steps whose
capabilities the environment has, `unbootstrap` removes them in reverse
order, and `check` tells whether they are in place (fixture bootstrap_ok).
Credentials a step creates go to the credentials Secret only.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Literal
from typing import Protocol

from podiumd_tests.capabilities import CLUSTER
from podiumd_tests.credential_store import CredentialStore

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from podiumd_tests.config import Profile
    from podiumd_tests.environment import Environment

Action = Literal["created", "present", "removed", "absent", "skipped", "missing"]


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

    def is_present(self, ctx: Context, /) -> bool:
        """True when the step's objects and stored credentials are in place."""
        ...

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Create the step's objects (replacing stale ones); return credentials to store."""
        ...

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the step's objects; return the credential keys to drop from the store."""
        ...


@dataclass(frozen=True)
class Outcome:
    """What happened to one step."""

    step: str
    action: Action
    detail: str = ""


def refusal(profile: Profile) -> str | None:
    """Why bootstrap may not run on this environment, or None (PLAN.md R20: smoke-only stays untouched)."""
    if set(profile.allowed_tiers) <= {"smoke"}:
        return f"{profile.name} is smoke-only (allowed_tiers: {', '.join(profile.allowed_tiers)}); bootstrap changes it"
    return None


def _each(env: Environment, steps: Sequence[Step], act: Callable[[Context, Step], Outcome]) -> list[Outcome]:
    """Run act on every step the environment has the capabilities for; skip the others with a reason."""
    ctx = Context(env, CredentialStore(env.kube))
    outcomes: list[Outcome] = []
    for step in steps:
        reason = env.capabilities.skip_reason(CLUSTER, *step.requires)
        outcomes.append(Outcome(step.name, "skipped", reason) if reason else act(ctx, step))
    return outcomes


def bootstrap(env: Environment, steps: Sequence[Step], *, rotate: bool = False) -> list[Outcome]:
    """Apply every applicable step that is not in place (all of them with rotate)."""

    def apply(ctx: Context, step: Step) -> Outcome:
        if not rotate and step.is_present(ctx):
            return Outcome(step.name, "present")
        ctx.notes.clear()
        values = step.apply(ctx)
        if values:
            ctx.store.write(values)
        return Outcome(step.name, "created", "; ".join([", ".join(sorted(values)), *ctx.notes]))

    return _each(env, steps, apply)


def unbootstrap(env: Environment, steps: Sequence[Step]) -> list[Outcome]:
    """Remove every applicable step, in reverse order."""

    def remove(ctx: Context, step: Step) -> Outcome:
        present = step.is_present(ctx)
        keys = step.remove(ctx)
        if keys:
            ctx.store.remove(*keys)
        return Outcome(step.name, "removed" if present else "absent")

    return _each(env, list(reversed(steps)), remove)


def check(env: Environment, steps: Sequence[Step]) -> list[Outcome]:
    """Whether every applicable step is in place; changes nothing."""
    return _each(env, steps, lambda ctx, step: Outcome(step.name, "present" if step.is_present(ctx) else "missing"))


def format_outcomes(outcomes: Sequence[Outcome]) -> str:
    """One line per step for the terminal."""
    width = max((len(o.step) for o in outcomes), default=0)
    return "\n".join(f"{o.action:8} {o.step.ljust(width)}  {o.detail}".rstrip() for o in outcomes)
