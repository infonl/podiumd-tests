"""Cleanup of created resources.

Factories register a deleter for everything they create. On teardown the
registry deletes in reverse order (LIFO), also when the test failed, and
reports every deleter that failed instead of stopping at the first one.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from typing import TYPE_CHECKING

from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.django_snippets import run_snippets

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from podiumd_tests.kube import Kube


@dataclass(frozen=True)
class _Snippet:
    kube: Kube
    deployment: str
    name: str
    params: dict[str, object]


@dataclass(frozen=True)
class _Entry:
    description: str
    delete: Callable[[], object]
    snippet: _Snippet | None = None


class CleanupError(Exception):
    """One or more deleters failed; the message lists them all."""


class ResourceRegistry:
    """Created resources of one test, with their deleters."""

    def __init__(self, run_tag: str, *, keep: bool = False) -> None:
        self.run_tag = run_tag
        self.keep = keep
        self._entries: list[_Entry] = []

    def tagged(self, name: str) -> str:
        """A name carrying the run tag, so sweep can find leftovers."""
        return f"{self.run_tag}-{name}"

    def add(self, description: str, delete: Callable[[], object]) -> None:
        """Register a deleter for a created resource."""
        self._entries.append(_Entry(description, delete))

    def add_snippet(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # run_snippet's parameters
        self, description: str, kube: Kube, deployment: str, name: str, params: dict[str, object]
    ) -> None:
        """Register a snippet as deleter; cleanup runs consecutive snippets of one deployment in one Django shell.

        The snippet must be safe to run twice: when the shell fails, cleanup runs each snippet of it again.
        """
        snippet = _Snippet(kube, deployment, name, params)
        self._entries.append(_Entry(description, lambda: run_snippet(kube, deployment, name, params), snippet))

    def __len__(self) -> int:
        return len(self._entries)

    def cleanup(self) -> list[str]:
        """Delete everything; return the descriptions kept (with keep=True) or raise CleanupError."""
        entries, self._entries = self._entries, []
        if self.keep:
            return [e.description for e in entries]
        errors: list[str] = []
        for _, group in groupby(reversed(entries), _batch_key):
            batch = list(group)
            if len(batch) > 1 and _run_batch(batch):
                continue
            for entry in batch:
                try:
                    entry.delete()
                except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # collect all, report together
                    errors.append(f"{entry.description}: {type(exc).__name__}: {exc}")
        if errors:
            raise CleanupError("cleanup failed for: " + "; ".join(errors))
        return []


def _batch_key(entry: _Entry) -> object:
    """Snippets of one deployment share a key; any other entry has its own."""
    return (id(entry.snippet.kube), entry.snippet.deployment) if entry.snippet else id(entry)


def _run_batch(batch: Sequence[_Entry]) -> bool:
    """Run the entries' snippets in one Django shell; False when that failed, to run each and report which one."""
    snippets = [e.snippet for e in batch if e.snippet]
    try:
        run_snippets(snippets[0].kube, snippets[0].deployment, [(s.name, s.params) for s in snippets])
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught  # each deleter again reports the error
        return False
    return True
