"""Unit tests for the Redis HA helpers."""

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests import redis

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment


class FakeKube:
    def __init__(self, out):
        self.out, self.calls = out, []

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.out


class FakeEnv:
    def __init__(self, objects, out=""):
        self.objects, self.kube = objects, FakeKube(out)

    def items(self, kind):
        return self.objects.get(kind, [])


def pod(name, labels, probe_command):
    container = {"name": "redis-ha", "readinessProbe": {"exec": {"command": probe_command}}}
    return {"metadata": {"name": name, "namespace": "ns", "labels": labels}, "spec": {"containers": [container]}}


def test_role_endpoints_and_master_check():
    master = pod("redis-ha-0", {"app": "redis-ha", "redis-role": "master"}, ["sh", "-c", "grep -q role:master"])
    other = pod("x", {"app": "other"}, ["true"])
    endpoints = {
        "metadata": {"name": "redis-ha-master"},
        "subsets": [{"addresses": [{"targetRef": {"name": "redis-ha-0"}}]}],
    }
    fake = FakeEnv({"pods": [master, other], "endpoints": [endpoints]}, out="# Replication\r\nrole:slave\r\n")
    env = cast("Environment", fake)
    assert redis.redis_pods(env) == [master]
    assert redis.checks_master_role(master)
    assert not redis.checks_master_role(other)
    assert redis.ready_endpoints(env, "redis-ha-master") == ["redis-ha-0"]
    assert redis.reported_role(env, master) == "slave"
    args, kwargs = fake.kube.calls[0]
    assert args[:4] == ("exec", "pod/redis-ha-0", "-c", "redis-ha") and kwargs == {"namespace": "ns"}
