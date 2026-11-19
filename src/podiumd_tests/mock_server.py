"""podiumd-tests' mock server in the cluster (infra/mock-server), and reading what it received.

The mock server records every POST in a JSON-lines file and answers 204 only when it carries auth;
tests read that file through `kubectl exec`, so the mock server needs no ingress. Each test uses its own callback
path, which keeps parallel tests apart.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

import yaml

from podiumd_tests.config import REPO_ROOT
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.wait import WaitTimeoutError
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from podiumd_tests.bootstrap.runner import Context
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

NAME = "ptest-bootstrap-mock-server"
INFRA = REPO_ROOT / "infra" / "mock-server"
RECEIVED_FILE = "/data/received.jsonl"
# Where the mock server keeps the Worldline checkouts it plays.
CHECKOUTS_DIR = "/data/worldline"
# The mock server's Notify (NotifyNL) API. OMC's Notify client keeps only the host of its base URL
# (podiumd-minikube sets <mock server>/notify), so the path has no /notify prefix.
NOTIFY_EMAIL = "/v2/notifications/email"
NOTIFY_SMS = "/v2/notifications/sms"
NOTIFY_MESSAGEBOX = "/v2/notifications/messagebox"
ROLLOUT_TIMEOUT = 180
# Kanaal, resource and actie of the notification of a new zaak.
ZAAK_CREATE = ("zaken", "zaak", "create")


# The Deployment's annotation with the hash of infra/mock-server: a changed manifest also makes the step missing.
INFRA_HASH = "podiumd-tests/infra-hash"


def infra_hash() -> str:
    """Return a short hash of the mock server's manifests and code in this checkout."""
    digest = hashlib.sha256()
    for name in ("manifests.yaml", "server.py"):
        digest.update((INFRA / name).read_bytes())
    return digest.hexdigest()[:16]


def manifests(image: str = "") -> list[dict[str, object]]:
    """Return the mock server's ConfigMap, Deployment and Service, with server.py; image replaces the default image."""
    docs = [
        cast("dict[str, object]", manifest)
        for manifest in yaml.safe_load_all((INFRA / "manifests.yaml").read_text())
        if manifest
    ]
    for doc in docs:
        if doc["kind"] == "ConfigMap":
            doc["data"] = {"server.py": (INFRA / "server.py").read_text()}
        if doc["kind"] == "Deployment":
            metadata = cast("dict[str, object]", doc["metadata"])
            metadata["annotations"] = {**section(metadata, "annotations"), INFRA_HASH: infra_hash()}
            if image:
                _container(doc)["image"] = image
    return docs


def _container(deployment: JsonObject) -> dict[str, object]:
    return cast(
        "dict[str, object]",
        entries(section(section(section(deployment, "spec"), "template"), "spec").get("containers"))[0],
    )


def _image(env: Environment) -> str:
    """Return the profile's settings.mock_server_image (a registry the cluster's policy allows), or the default."""
    return env.profile.settings.get("mock_server_image", "")


def _entry(line: str) -> JsonObject | None:
    """One recorded request; None for a line cut short by a failed or ongoing write."""
    try:
        found: object = json.loads(line)
    except ValueError:
        return None
    return cast("JsonObject", found) if isinstance(found, dict) else None


def mock_server_root(env: Environment) -> str:
    """Return the root URL the platform reaches the mock server on from inside the cluster."""
    return f"http://{NAME}.{env.profile.kube.namespace}"


def _about(entry: JsonObject) -> tuple[object, ...]:
    """Kanaal, resource, actie and hoofdObject of a received notification."""
    body = section(entry, "body")
    return body.get("kanaal"), body.get("resource"), body.get("actie"), body.get("hoofdObject")


def notification(kanaal: str, resource: str, actie: str, hoofd: object) -> Callable[[JsonObject], bool]:
    """Return a match of received entries: a notification of this kind about hoofd (a URL)."""
    return lambda entry: _about(entry) == (kanaal, resource, actie, hoofd)


@dataclass(frozen=True)
class Callback:
    """One test's callback path on the mock server."""

    env: Environment
    path: str

    @property
    def url(self) -> str:
        """URL the platform reaches the callback on from inside the cluster."""
        return mock_server_root(self.env) + self.path

    @classmethod
    def new(cls, env: Environment, run_tag: str, *, answer: str = "") -> Callback:
        """Return a callback path of its own, under the run tag.

        answer: "fail-first" (the first notification gets 500) or "refuse" (every notification gets 403).
        """
        answer_part = f"/{answer}" if answer else ""
        return cls(env, f"/{run_tag}{answer_part}/{secrets.token_hex(6)}")

    def received(self) -> list[JsonObject]:
        """Everything the mock server got on this path, oldest first."""
        out = self.env.kube.exec(NAME, "sh", "-c", f"cat {RECEIVED_FILE} 2>/dev/null || true")
        parsed = map(_entry, out.splitlines())
        return [entry for entry in parsed if entry is not None and entry.get("path") == self.path]

    def notified(self, kanaal: str, resource: str, actie: str) -> Counter[object]:
        """Return how many notifications of this kind the path received, per hoofdObject."""
        kind = (kanaal, resource, actie)
        found = [_about(entry) for entry in self.received()]
        return Counter(about[-1] for about in found if about[:3] == kind)

    def missing(
        self, hoofden: Sequence[str], timeout: float = 0, kind: tuple[str, str, str] = ZAAK_CREATE
    ) -> list[str]:
        """Return the hoofdObjecten among `hoofden` that no notification of this (kanaal, resource, actie) reached.

        Waits up to `timeout` seconds for all of them.
        """

        def lacking() -> list[str]:
            received = self.notified(*kind)
            return [hoofd for hoofd in hoofden if not received[hoofd]]

        with suppress(WaitTimeoutError):
            wait_until(lambda: not lacking(), timeout=timeout, interval=10, description=f"every {' '.join(kind)}")
        return lacking()

    def wait_for(self, match: Callable[[JsonObject], bool], *, timeout: float, description: str) -> JsonObject:
        """Return the first received entry that matches; WaitTimeoutError when none arrives in time."""
        return wait_until(
            lambda: next((entry for entry in self.received() if match(entry)), None),
            timeout=timeout,
            description=description,
        )


@dataclass(frozen=True)
class MockServer:
    """Bootstrap step: deploy the mock server; it is present when its Deployment is ready and runs the current code."""

    name: str = "infra-mock-server"
    requires: tuple[str, ...] = ("cluster",)
    wiring: bool = False

    def is_present(self, ctx: Context, /) -> bool:  # noqa: PLR6301  # a Step method
        """Return whether the Deployment runs this checkout's infra/mock-server with the current image, and is ready."""
        kube = ctx.env.kube
        config_map = kube.get_optional("configmap", NAME)
        deployment = kube.get_optional("deployment", NAME)
        if config_map is None or deployment is None:
            return False
        code = cast("dict[str, object]", config_map.get("data") or {}).get("server.py")
        ready = cast("dict[str, object]", deployment.get("status") or {}).get("readyReplicas")
        wanted = _container(manifests(_image(ctx.env))[1])["image"]
        same_image = _container(deployment).get("image") == wanted
        current = section(section(deployment, "metadata"), "annotations").get(INFRA_HASH) == infra_hash()
        return code == (INFRA / "server.py").read_text() and bool(ready) and same_image and current

    def apply(self, ctx: Context, /) -> dict[str, str]:  # noqa: PLR6301  # a Step method
        """Apply the manifests, restart on new code, and wait until the Deployment is ready."""
        ctx.env.kube.deploy(manifests(_image(ctx.env)), NAME, ROLLOUT_TIMEOUT, restart=True)
        return {}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:  # noqa: PLR6301  # a Step method
        """Delete the manifests' objects."""
        ctx.env.kube.delete_all(manifests())
        return ()


# Run in the mock server's pod: GET / of each URL with its own host as Host, without following redirects.
_STATUS_SCRIPT = """
import http.client, json, sys
from urllib.parse import urlsplit
found = {}
for url in json.loads(sys.argv[1]):
    part = urlsplit(url)
    try:
        connection = http.client.HTTPConnection(part.hostname, part.port, timeout=10)
        connection.request("GET", part.path or "/", headers={"Host": part.netloc})
        found[url] = connection.getresponse().status
    except Exception as error:
        found[url] = type(error).__name__
print(json.dumps(found))
"""


def in_cluster_statuses(env: Environment, urls: Sequence[str]) -> dict[str, int | str]:
    """Return the HTTP status of GET each URL from inside the cluster (the mock server's pod), or the error's name."""
    timeout = 30 + 12 * len(urls)
    out = env.kube.exec(NAME, "python", "-c", _STATUS_SCRIPT, json.dumps(list(urls)), timeout=timeout)
    return cast("dict[str, int | str]", json.loads(out))
