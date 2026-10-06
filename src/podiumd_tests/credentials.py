"""Secret resolution (PLAN.md R8): env var first, then the source in the profile.

Secrets are never stored in the repository. Every resolved value is
registered with the Redactor, so it never ends up in output or results.
"""

from __future__ import annotations

import os

# Only for subprocess.TimeoutExpired; processes are started in process.py.
import subprocess  # nosec B404

from typing import TYPE_CHECKING

from podiumd_tests.kube import Kube
from podiumd_tests.kube import KubeError
from podiumd_tests.kube import django_value
from podiumd_tests.process import Runner
from podiumd_tests.process import run_process

if TYPE_CHECKING:
    from podiumd_tests.config import Profile
    from podiumd_tests.config import SecretSpec

ENV_PREFIX = "PODIUMD_TESTS_SECRET_"
REDACTED = "***"

# Prints the shared secret of one JWTSecret row. The client id is inserted as a Python
# string literal (repr), so it cannot inject code.
_JWT_LOOKUP_SNIPPET = (
    "from vng_api_common.models import JWTSecret\n"
    "print('PTEST_VALUE=' + JWTSecret.objects.get(identifier={identifier!r}).secret)"
)


class SecretError(Exception):
    """A secret could not be resolved."""


class Redactor:
    """Collects secret values and masks them in any text."""

    def __init__(self) -> None:
        self._values: set[str] = set()

    def add(self, value: str) -> None:
        """Remember a secret value so it gets masked."""
        if len(value) >= 4:  # very short values would mask ordinary text
            self._values.add(value)

    def redact(self, text: str) -> str:
        """Replace every known secret value in text with ***."""
        for value in sorted(self._values, key=len, reverse=True):
            text = text.replace(value, REDACTED)
        return text


def env_var_name(secret_name: str) -> str:
    """Name of the environment variable that overrides a secret."""
    return ENV_PREFIX + secret_name.upper().replace("-", "_")


class SecretResolver:
    """Resolves the secrets of one profile, once each, and registers them for redaction."""

    def __init__(
        self,
        profile: Profile,
        kube: Kube,
        redactor: Redactor,
        runner: Runner = run_process,
        environ: dict[str, str] | None = None,
    ) -> None:
        self._profile = profile
        self._kube = kube
        self._redactor = redactor
        self._runner = runner
        self._environ = dict(os.environ) if environ is None else environ
        self._cache: dict[str, str] = {}

    @property
    def names(self) -> list[str]:
        """Names of the secrets in the profile."""
        return sorted(self._profile.secrets)

    def get(self, name: str) -> str:
        """Value of a secret; SecretError if it cannot be resolved."""
        if name not in self._cache:
            value = self._resolve(name)
            # Published dev defaults such as "admin" are no secret; masking them garbles ordinary text.
            if not self._is_dev_default(name):
                self._redactor.add(value)
            self._cache[name] = value
        return self._cache[name]

    def _is_dev_default(self, name: str) -> bool:
        spec = self._profile.secrets.get(name)
        return spec is not None and spec.source == "dev_default" and not self._environ.get(env_var_name(name))

    def _resolve(self, name: str) -> str:
        override = self._environ.get(env_var_name(name))
        if override:
            return override
        spec = self._profile.secrets.get(name)
        if spec is None:
            msg = f"secret {name!r}: not in profile {self._profile.name} and {env_var_name(name)} not set"
            raise SecretError(msg)
        try:
            return self._from_source(spec).strip()
        except (KubeError, ValueError) as exc:
            msg = f"secret {name!r} ({spec.source}): {exc}"
            raise SecretError(msg) from exc

    def _from_source(self, spec: SecretSpec) -> str:
        opts = spec.options
        match spec.source:
            case "dev_default":
                return opts["value"]
            case "k8s_secret":
                return self._kube.secret_value(opts["name"], opts["key"])
            case "pod_env":
                return self._kube.run("exec", f"deploy/{opts['deployment']}", "--", "printenv", opts["var"])
            case "zgw_jwt_secret":
                code = _JWT_LOOKUP_SNIPPET.format(identifier=opts["client_id"])
                return django_value(self._kube.exec_django_shell(opts["deployment"], code))
            case "keyvault":
                return self._from_keyvault(spec)
            case _:
                msg = f"secret {spec.name!r}: unknown source {spec.source!r}"
                raise SecretError(msg)

    def _from_keyvault(self, spec: SecretSpec) -> str:
        vault = spec.options.get("vault") or self._profile.keyvault
        if not vault:
            msg = f"secret {spec.name!r}: no Key Vault configured in profile {self._profile.name}"
            raise SecretError(msg)
        command = ["az", "keyvault", "secret", "show", "--vault-name", vault, "--name", spec.options["secret"]]
        command += ["--query", "value", "--output", "tsv"]
        try:
            result = self._runner(command, 60)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            msg = f"secret {spec.name!r}: az failed: {exc}"
            raise SecretError(msg) from exc
        if result.returncode != 0:
            msg = f"secret {spec.name!r}: az keyvault secret show failed: {result.stderr.strip()}"
            raise SecretError(msg)
        return result.stdout
