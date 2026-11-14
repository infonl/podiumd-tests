"""Referentielijsten test data; its API is read-only, so tabellen are made through Django."""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.django_snippets import run_snippet

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry


def make_tabel(env: Environment, registry: ResourceRegistry, code: str, items: Sequence[Mapping[str, str]]) -> None:
    """Create a tabel named code with items ({code, naam}); cleanup deletes it."""
    deployment = env.deployment_for("referentielijsten")
    params: dict[str, object] = {
        "action": "create",
        "code": code,
        "naam": code,
        "items": [dict(item) for item in items],
    }
    registry.add_snippet(
        f"tabel {code}", env.kube, deployment, "referentielijsten_tabel", {"action": "delete", "code": code}
    )
    run_snippet(env.kube, deployment, "referentielijsten_tabel", params)
