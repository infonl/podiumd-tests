"""Unit tests for the Django snippets and how they are run."""

import ast
import json

from importlib import resources

import pytest

from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.django_snippets import run_snippets
from podiumd_tests.django_snippets import snippet_source
from podiumd_tests.kube import Kube

SNIPPETS = sorted(
    p.name.removesuffix(".py")
    for p in resources.files("podiumd_tests.snippets").iterdir()
    if p.name.endswith(".py") and not p.name.startswith("_")
)


@pytest.mark.parametrize("name", SNIPPETS)
def test_snippet_compiles_and_defines_run(name):
    tree = ast.parse(snippet_source(name))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "run" in functions
    assert [a.arg for a in functions["run"].args.args] == ["params"]


def test_snippet_source_puts_its_includes_first():
    source = snippet_source("token_auth")
    assert source.index("def objecttype_models") < source.index("def run")


def test_run_snippet_sends_code_and_params_over_stdin(fake_runner):
    fake_runner.answers["exec -i deploy/openzaak"] = (0, 'chatter\nPTEST_VALUE={"ok": true}\n')
    result = run_snippet(Kube("ctx", "ns", fake_runner), "openzaak", "jwt_secret", {"client_id": "s3cret-client"})
    assert result == {"ok": True}
    assert "s3cret-client" not in " ".join(fake_runner.calls[0])
    code = fake_runner.stdins[0]
    assert "def run(params)" in code
    compile(code, "<snippet>", "exec")
    assert json.dumps({"client_id": "s3cret-client"}) in code


def test_run_snippets_runs_them_in_order_in_one_shell(fake_runner):
    fake_runner.answers["exec -i deploy/openzaak"] = (0, "chatter\nPTEST_VALUE=1\nPTEST_VALUE=[2]\n")
    calls: list[tuple[str, dict[str, object]]] = [
        ("jwt_secret", {"client_id": "a"}),
        ("token_auth", {"identifier": "b"}),
    ]
    assert run_snippets(Kube("ctx", "ns", fake_runner), "openzaak", calls) == [1, [2]]
    assert len(fake_runner.calls) == 1
    code = fake_runner.stdins[0]
    compile(code, "<snippets>", "exec")
    assert code.index("snippets/jwt_secret.py") < code.index("snippets/token_auth.py")
