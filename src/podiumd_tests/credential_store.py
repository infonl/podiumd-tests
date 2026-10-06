"""The credentials bootstrap creates, kept in one Secret in the environment's namespace (PLAN.md §11a).

Only this Secret holds them: never the repository, never a local file. The
SecretResolver reads it as the last source, so tests use bootstrap
credentials without profile entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from podiumd_tests.json_data import section
from podiumd_tests.kube import decode_secret_data

if TYPE_CHECKING:
    from podiumd_tests.kube import Kube

STORE_NAME = "podiumd-tests-credentials"
MANAGED_BY = {"app.kubernetes.io/managed-by": "podiumd-tests"}


class CredentialStore:
    """Read and write the bootstrap credentials Secret."""

    def __init__(self, kube: Kube) -> None:
        self.kube = kube

    def read(self) -> dict[str, str]:
        """All stored values; empty when the Secret does not exist."""
        secret = self.kube.get_optional("secret", STORE_NAME)
        return decode_secret_data(section(secret, "data")) if secret else {}

    def write(self, values: dict[str, str]) -> None:
        """Merge values into the Secret, creating it when needed. Values go over stdin, not argv."""
        self._put(self.read() | values)

    def remove(self, *keys: str) -> None:
        """Drop keys; the Secret itself is deleted when nothing is left."""
        remaining = {k: v for k, v in self.read().items() if k not in keys}
        # apply would merge stringData into the old keys, so the Secret is recreated instead.
        self.kube.delete("secret", STORE_NAME)
        if remaining:
            self._put(remaining)

    def _put(self, values: dict[str, str]) -> None:
        self.kube.apply(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": STORE_NAME, "namespace": self.kube.namespace, "labels": MANAGED_BY},
                "type": "Opaque",
                "stringData": values,
            }
        )
