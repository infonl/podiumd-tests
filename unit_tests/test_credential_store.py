"""Unit tests for the bootstrap credential store."""

import base64
import threading

from typing import final

from podiumd_tests.credential_store import CredentialStore


@final
class SlowKube:
    """A Kube whose Secret delete pauses until released, as a real delete takes a moment."""

    namespace = "podiumd"

    def __init__(self, values):
        self.values = dict(values)
        self.deleting = threading.Event()
        self.release = threading.Event()

    def get_optional(self, _kind, _name):
        if self.values is None:
            return None
        return {"data": {k: base64.b64encode(v.encode()).decode() for k, v in self.values.items()}}

    def delete(self, _kind, _name):
        self.values = None
        self.deleting.set()
        self.release.wait(5)

    def apply(self, manifest):
        self.values = dict(manifest["stringData"])


def test_a_read_during_remove_waits_for_the_recreated_secret():
    kube = SlowKube({"token": "t", "other": "o"})
    store = CredentialStore(kube)  # pyright: ignore[reportArgumentType]  # duck-typed Kube
    remover = threading.Thread(target=store.remove, args=("other",))
    remover.start()
    kube.deleting.wait(5)
    found = {}
    reader = threading.Thread(target=lambda: found.update(store.read()))
    reader.start()
    kube.release.set()
    remover.join(5)
    reader.join(5)
    assert found == {"token": "t"}
