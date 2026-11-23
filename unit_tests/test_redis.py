"""Unit tests for the Redis HA helpers."""

import json

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests import redis
from podiumd_tests import workloads
from podiumd_tests.capabilities import Capabilities

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject


type _Call = tuple[tuple[object, ...], dict[str, object]]


class FakeKube:
    def __init__(self, out):
        self.out: str = out
        self.calls: list[_Call] = []

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.out


class FakeEnv:
    def __init__(self, objects, out=""):
        self.objects: dict[str, list[JsonObject]] = objects
        self.kube: FakeKube = FakeKube(out)

    def items(self, kind):
        return self.objects.get(kind, [])


def pod(name, labels, probe_command, uid=""):
    container = {"name": "redis-ha", "readinessProbe": {"exec": {"command": probe_command}}}
    metadata = {"name": name, "namespace": "ns", "labels": labels, "uid": uid}
    return {"metadata": metadata, "spec": {"containers": [container]}}


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
    assert redis.is_master_role_checked(master)
    assert not redis.is_master_role_checked(other)
    assert workloads.ready_endpoints(env, "redis-ha-master") == ["redis-ha-0"]
    assert redis.reported_role(env, master) == "slave"
    args, kwargs = fake.kube.calls[0]
    assert args[:4] == ("exec", "pod/redis-ha-0", "-c", "redis-ha")
    assert kwargs == {"namespace": "ns"}


def test_master_pod_is_the_reporting_master_behind_the_service():
    master = pod("redis-ha-1", {"app": "redis-ha", "redis-role": "master"}, ["true"], uid="u1")
    endpoints = {
        "metadata": {"name": "redis-ha-master"},
        "subsets": [{"addresses": [{"targetRef": {"name": "redis-ha-1"}}]}],
    }
    env = cast("Environment", FakeEnv({"pods": [master], "endpoints": [endpoints]}, out="role:master\r\n"))
    assert redis.master_pod(env) == master
    assert redis.master_pod(env, replaced_uid="u1") is None
    assert redis.master_pod(env, replaced_uid="u0") == master
    slave = cast("Environment", FakeEnv({"pods": [master], "endpoints": [endpoints]}, out="role:slave\r\n"))
    assert redis.master_pod(slave) is None
    assert redis.master_pod(cast("Environment", FakeEnv({"pods": [master]}))) is None


def deployment(name, *containers):
    return {"metadata": {"name": name}, "spec": {"template": {"spec": {"containers": list(containers)}}}}


def test_redis_deployments_and_components_read_the_master_service_from_a_config_map(env_factory, fake_runner):
    from_map = {"envFrom": [{"configMapRef": {"name": "openzaak"}}]}
    from_key = {"env": [{"name": "BROKER", "valueFrom": {"configMapKeyRef": {"name": "celery", "key": "url"}}}]}
    deployments = [
        deployment("openzaak", from_map),
        deployment("openzaak-worker", from_key),
        deployment("zac", {"envFrom": [{"configMapRef": {"name": "zac"}}]}),
        deployment("kiss", {"env": [{"name": "X", "value": "redis-ha-master"}]}),
    ]
    config_maps = [
        {"metadata": {"name": "openzaak"}, "data": {"CACHE_DEFAULT": "redis-ha-master:6379/4"}},
        {"metadata": {"name": "celery"}, "data": {"url": "redis://redis-ha-master:6379/5"}},
        {"metadata": {"name": "zac"}, "data": {"SOLR_URL": "http://solr"}},
    ]
    fake_runner.answers = {
        "get deployments": (0, json.dumps({"items": deployments})),
        "get configmaps": (0, json.dumps({"items": config_maps})),
    }
    env = env_factory()
    env.__dict__["capabilities"] = Capabilities(frozenset(("openzaak", "zac")), {})
    users = redis.redis_deployments(env)
    assert users == ["openzaak", "openzaak-worker"]
    assert redis.redis_components(env, users) == ["openzaak"]


def endpoints_for(*names):
    addresses = [{"targetRef": {"name": name}} for name in names]
    return {"metadata": {"name": "redis-ha-master"}, "subsets": [{"addresses": addresses}]}


def test_master_problem_names_two_endpoints_or_a_replica_behind_the_service():
    one = pod("redis-ha-0", {"app": "redis-ha"}, ["true"])
    two = pod("redis-ha-1", {"app": "redis-ha"}, ["true"])

    def problem(names, out):
        return redis.master_problem(
            cast("Environment", FakeEnv({"pods": [one, two], "endpoints": [endpoints_for(*names)]}, out))
        )

    assert (
        problem(["redis-ha-0", "redis-ha-1"], "role:master")
        == "redis-ha-master has 2 ready endpoints: redis-ha-0, redis-ha-1"
    )
    assert problem(["redis-ha-0"], "role:slave") == "redis-ha-master points at redis-ha-0, which reports role:slave"
    assert problem(["redis-ha-0"], "role:master") is None
    assert problem([], "") is None


def test_wait_for_takeover_returns_the_new_master_and_the_problems_seen():
    master = pod("redis-ha-1", {"app": "redis-ha"}, ["true"], uid="new")
    env = cast("Environment", FakeEnv({"pods": [master], "endpoints": [endpoints_for("redis-ha-1")]}, "role:master"))
    takeover = redis.wait_for_takeover(env, "old", 5)
    assert takeover.master == master
    assert takeover.problems == []


def test_app_connections_skip_the_replication_link_and_the_pod_itself():
    replica = pod("redis-ha-1", {"app": "redis-ha"}, ["true"])
    replica["status"] = {"podIP": "10.0.0.5"}
    clients = (
        "id=1 addr=10.0.0.4:6379 laddr=10.0.0.5:51000 flags=M db=0 cmd=ping\n"
        "id=2 addr=10.0.0.5:40000 flags=N db=0 cmd=client|list\n"
        "id=3 addr=127.0.0.1:41000 flags=N db=0 cmd=info\n"
        "id=4 addr=10.0.1.9:52000 flags=N db=9 cmd=get\n"
    )
    env = cast("Environment", FakeEnv({}, clients))
    assert redis.app_connections(env, replica) == ["10.0.1.9:52000"]
    env = cast("Environment", FakeEnv({"pods": [replica]}, f"role:slave\n{clients}"))
    assert redis.replica_app_connections(env) == {"redis-ha-1": ["10.0.1.9:52000"]}


def test_sentinel_pods_are_the_sentinel_statefulsets_pods():
    sentinel = pod("redis-ha-sentinel-0", {"app": "redis-ha-sentinel"}, ["true"])
    env = cast("Environment", FakeEnv({"pods": [sentinel, pod("redis-ha-0", {"app": "redis-ha"}, ["true"])]}))
    assert redis.sentinel_pods(env) == [sentinel]
