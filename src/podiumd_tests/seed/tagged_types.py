"""Run-tagged types whose API refuses to delete them once published: a Django snippet lists and deletes them.

Each snippet takes action list (param prefix) or delete (param name) besides the params of the kind's scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.results import RUN_TAG
from podiumd_tests.results import TAG_PREFIX

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping

    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry


def everywhere(_env: Environment) -> Mapping[str, object]:
    """Scope of a kind whose snippet takes no params of its own."""
    return {}


@dataclass(frozen=True)
class TaggedTypes:
    """The run-tagged types of one kind: sweep's name for them, their component, snippet and its params per environment.

    scope: the snippet's params for where tests write this kind on an environment.
    """

    kind: str
    component: str
    snippet: str
    scope: Callable[[Environment], Mapping[str, object]] = everywhere

    def forget(
        self, env: Environment, registry: ResourceRegistry, name: str, scope: Mapping[str, object] | None = None
    ) -> None:
        """Delete the type at cleanup; scope narrows the snippet's params to where the type is."""
        params = self._deletion(name, self.scope(env) if scope is None else scope)
        registry.add_snippet(f"{self.kind} {name}", env.kube, env.deployment_for(self.component), self.snippet, params)

    def remove(self, env: Environment, name: str) -> None:
        """Delete a run-tagged type, published or not, with what belongs to it."""
        params = self._deletion(name, self.scope(env))
        run_snippet(env.kube, env.deployment_for(self.component), self.snippet, params)

    def tagged(self, env: Environment) -> list[str]:
        """Return the names of the types that start with ptest-, bootstrap ones included."""
        params = {**self.scope(env), "action": "list", "prefix": TAG_PREFIX}
        found = run_snippet(env.kube, env.deployment_for(self.component), self.snippet, params)
        return [str(name) for name in cast("list[object]", found)]

    def _deletion(self, name: str, scope: Mapping[str, object]) -> dict[str, object]:
        if not RUN_TAG.search(name):
            msg = f"refusing to delete {self.kind} {name}: it carries no run tag"
            raise ValueError(msg)
        return {**scope, "action": "delete", "name": name}
