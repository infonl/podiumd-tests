"""Run the Python snippets in podiumd_tests/snippets/ inside a Django component.

Each snippet module defines run(params) -> JSON-serialisable result and imports
the component's models inside it: they exist only in the component's image.
That is why basedpyright, pylint and vulture skip snippets/; ruff and bandit
still check it, and a unit test checks that every snippet compiles. Modules named _<name> hold
code that snippets include.

The code and its parameters go to `manage.py shell` over stdin, so secrets
never appear in a command line or an error message.
"""

from __future__ import annotations

import json
import re

from importlib import resources
from typing import TYPE_CHECKING

from podiumd_tests.kube import django_values

if TYPE_CHECKING:
    from collections.abc import Sequence

    from podiumd_tests.kube import Kube

INCLUDE = re.compile(r"^# include: (\w+)$", re.MULTILINE)
# Each snippet runs in its own namespace: snippets define the same names (run, helpers).
_CALLS = """
import json as _json
for _name, _source, _params in _json.loads({calls!r}):
    _namespace = dict(globals())
    exec(compile(_source, _name, "exec"), _namespace)
    print("PTEST_VALUE=" + _json.dumps(_namespace["run"](_params)))
"""


def snippet_source(name: str) -> str:
    """The source of snippets/<name>.py, after the snippets its `# include: <name>` lines name."""
    source = resources.files("podiumd_tests.snippets").joinpath(f"{name}.py").read_text(encoding="utf-8")
    included = [snippet_source(i) for i in INCLUDE.findall(source)]
    return "\n\n".join([*included, source])


def run_snippets(
    kube: Kube, deployment: str, calls: Sequence[tuple[str, dict[str, object]]], timeout: int = 120
) -> list[object]:
    """Run (name, params) snippets in order in one Django shell of a deployment; their run() results.

    One shell saves Django's start, which takes seconds per call (Open Inwoner: 6 s).
    """
    batch = [[f"snippets/{name}.py", snippet_source(name), params] for name, params in calls]
    code = _CALLS.format(calls=json.dumps(batch))
    return [json.loads(v) for v in django_values(kube.exec_django_shell(deployment, code, timeout))]


def run_snippet(kube: Kube, deployment: str, name: str, params: dict[str, object], timeout: int = 120) -> object:
    """Run snippets/<name>.py in a Django deployment; its run() result, parsed from JSON."""
    return run_snippets(kube, deployment, [(name, params)], timeout)[0]
