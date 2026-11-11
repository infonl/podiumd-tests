"""A bootstrap step done by one Django snippet."""

from __future__ import annotations

import json
import secrets

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.django_snippets import run_snippet

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.bootstrap.runner import Context
    from podiumd_tests.django_snippets import SnippetCall


@dataclass(frozen=True)
class SnippetStep:  # pylint: disable=too-many-instance-attributes  # a declarative step definition
    """A step done by one Django snippet with actions status, apply and remove (and ensure, see _ensure.py).

    Secret mode (default): a random secret is generated here, sent to the snippet and stored
    under store_key. Record mode (record=True), for wiring that adds to shared objects: apply
    gets the stored record and returns it extended with what it added; remove gets it back
    and undoes exactly that. Without store_key the step stores nothing. With opt_in, apply
    does nothing unless the profile allows that setting.
    """

    name: str
    # The first component is the one the snippet runs in.
    requires: tuple[str, ...]
    snippet: str
    store_key: str | None
    params: dict[str, object] = field(default_factory=dict[str, object])
    record: bool = False
    wiring: bool = False
    opt_in: str | None = None
    # Parameters known only at run time, e.g. a stored secret or an in-cluster URL.
    context_params: Callable[[Context], dict[str, object]] | None = None

    def is_present(self, ctx: Context, /) -> bool:
        """Not allowed (nothing to do), or the objects exist and what the step stores is in the credentials Secret."""
        if self._is_refused(ctx):
            return True
        return self.is_present_in(ctx, self._run(ctx, "status"))

    def status_call(self, ctx: Context, /) -> tuple[str, SnippetCall] | None:
        """Return is_present's snippet call and its deployment; None when not allowed (present without a shell)."""
        return None if self._is_refused(ctx) else self._call(ctx, "status")

    def is_present_in(self, ctx: Context, status: object, /) -> bool:
        """Return is_present for the result of status_call."""
        stored = self._is_stored(ctx)
        return bool(cast("dict[str, object]", status)["present"]) and stored

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Create the objects: with a new random secret, or extending the stored record."""
        if self._is_refused(ctx):
            ctx.notes.append(f"not allowed: profile setting {self.opt_in} is off")
            return {}
        return self._applied(ctx, "apply") or {}

    def ensure(self, ctx: Context, /) -> dict[str, str] | None:
        """Apply unless is_present, in one Django shell; the credentials to store, None when present."""
        if self._is_refused(ctx):
            return None
        return self._applied(ctx, "ensure", stored=self._is_stored(ctx))

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the objects, or undo what the stored record lists."""
        self._run(ctx, "remove", **({"record": self._stored_record(ctx)} if self.record else {}))
        return () if self.store_key is None else (self.store_key,)

    def _call(self, ctx: Context, action: str, **extra: object) -> tuple[str, SnippetCall]:
        deployment = ctx.env.deployment_for(self.requires[0])
        runtime = self.context_params(ctx) if self.context_params else {}
        return deployment, (self.snippet, {**self.params, **runtime, "action": action, **extra})

    def _run(self, ctx: Context, action: str, **extra: object) -> dict[str, object]:
        deployment, (snippet, params) = self._call(ctx, action, **extra)
        return cast("dict[str, object]", run_snippet(ctx.env.kube, deployment, snippet, params))

    def _is_refused(self, ctx: Context) -> bool:
        return self.opt_in is not None and not ctx.env.profile.is_allowed(self.opt_in)

    def _stored_record(self, ctx: Context) -> object:
        return json.loads(ctx.store.read().get(self.store_key or "", "{}"))

    def _is_stored(self, ctx: Context) -> bool:
        return self.store_key is None or self.store_key in ctx.store.read()

    def _applied(self, ctx: Context, action: str, **extra: object) -> dict[str, str] | None:
        """Run apply or ensure; the credentials to store, None when ensure found the step present."""
        if self.store_key is None:
            return None if self._apply(ctx, action, **extra) is None else {}
        if self.record:
            result = self._apply(ctx, action, record=self._stored_record(ctx), **extra)
            return None if result is None else {self.store_key: json.dumps(result["record"], sort_keys=True)}
        secret = secrets.token_hex(20)  # 40 characters: the longest TokenAuth.token allows
        return None if self._apply(ctx, action, secret=secret, **extra) is None else {self.store_key: secret}

    def _apply(self, ctx: Context, action: str, **extra: object) -> dict[str, object] | None:
        """Run apply or ensure; its result, None when ensure created nothing. Its "notes" go to the outcome."""
        result = self._run(ctx, action, **extra)
        if action == "ensure" and not result["created"]:
            return None
        notes = cast("list[object]", result.get("notes") or [])
        ctx.notes.extend(str(note) for note in notes)
        return result
