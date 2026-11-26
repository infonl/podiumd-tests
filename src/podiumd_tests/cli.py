"""Run PodiumD environment tests and manage their profiles and bootstrap.

Exit codes: 0 pass, 1 test failures, 2 configuration or preflight error,
3 tier not allowed for the environment, 4 another agent holds the environment's lock.
estate-profile check and report: 1 action needed. estate-profile apply and restore: 2 invalid profile, refused
environment or lock held, 3 Keycloak admin access failed, 4 state file missing or unreadable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from podiumd_tests import config
from podiumd_tests import doctor
from podiumd_tests import estate_profile
from podiumd_tests import estate_settings
from podiumd_tests import hygiene
from podiumd_tests import lock
from podiumd_tests import release_rules
from podiumd_tests import results
from podiumd_tests import workloads
from podiumd_tests.bootstrap.runner import bootstrap
from podiumd_tests.bootstrap.runner import has_failure
from podiumd_tests.bootstrap.runner import outcome_report
from podiumd_tests.bootstrap.runner import refusal
from podiumd_tests.bootstrap.runner import unbootstrap
from podiumd_tests.bootstrap.steps import STEPS
from podiumd_tests.capabilities import CLUSTER
from podiumd_tests.ci import group
from podiumd_tests.ci import publish_summary
from podiumd_tests.components import COMPONENTS
from podiumd_tests.components import component_for_host
from podiumd_tests.environment import Environment
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.kube import Kube
from podiumd_tests.kube import KubeError
from podiumd_tests.process import ProcessError
from podiumd_tests.seed import volume
from podiumd_tests.sweep import sweep
from podiumd_tests.sweep import sweep_report
from podiumd_tests.tiers import TIERS
from podiumd_tests.wait import parse_duration

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from podiumd_tests.bootstrap.runner import Outcome
    from podiumd_tests.bootstrap.runner import Step

type _AddParser = Callable[..., argparse.ArgumentParser]

# Options a pipeline sets in the environment: PODIUMD_TESTS_<OPTION> (secrets have their own prefix).
ENV_OPTION_PREFIX = "PODIUMD_TESTS_"
EXIT_OK = 0
EXIT_TESTS_FAILED = 1
EXIT_CONFIG = 2
EXIT_NOT_ALLOWED = 3
EXIT_BUSY = 4
# estate-profile check and report: a profile needs an action, or a fact to decide.
EXIT_ACTION_NEEDED = 1
# estate-profile apply and restore, a contract with podiumd-infra's Release Gate workflow: 2 is EXIT_CONFIG.
EXIT_KEYCLOAK = 3
EXIT_STATE = 4
# pytest-xdist workers of a parallel tier at most: 8 need Open Zaak at 2 pods (the Maykin chart default) or 3 uWSGI
# processes; one pod of 2 processes overloads at 8, so such a profile sets pytest_workers 6. 1 runs serially.
MAX_WORKERS = 8
# Niceness of a run outside CI: the workstation stays usable while runs of several environments overlap.
WORKSTATION_NICE = 10


def lower_priority() -> None:
    """Lower this process's priority (its pytest workers inherit it), outside CI only."""
    if not os.environ.get("CI"):
        os.nice(WORKSTATION_NICE)


def default_workers(cpus: int | None) -> int:
    """Workers for this machine: half its CPUs, at most MAX_WORKERS; the browsers and a local cluster share them."""
    return max(1, min(MAX_WORKERS, (cpus or 2) // 2))


def _load(args: argparse.Namespace) -> config.Profile:
    return config.load_profile(args.env, Path(args.envs_dir))


def cmd_env_list(args: argparse.Namespace) -> int:
    """List all profiles."""
    for name, path in config.list_profiles(Path(args.envs_dir)).items():
        print(f"{name:20} {path.relative_to(Path(args.envs_dir))}")
    return EXIT_OK


def cmd_env_show(args: argparse.Namespace) -> int:
    """Show one profile."""
    profile = _load(args)
    print(f"{profile.name} ({profile.estate}) context={profile.kube.context} namespace={profile.kube.namespace}")
    print(f"allowed tiers: {', '.join(profile.allowed_tiers)}")
    for component, url in sorted(profile.urls.items()):
        print(f"  {component:20} {url}")
    print("secrets (a missing one skips its tests; PODIUMD_TESTS_SECRET_<NAME> overrides):")
    for name, spec in sorted(profile.secrets.items()):
        options = sorted(spec.options.items())
        where = " ".join(f"{option}={value}" for option, value in options)
        print(f"  {name:28} {spec.source} {where}".rstrip())
    return EXIT_OK


def ingress_hosts(kube: Kube) -> list[str]:
    """Hosts of all Ingresses and HTTPRoutes in the cluster; a kind the cluster lacks (no Gateway API) is skipped."""
    hosts: list[str] = []
    for kind in ("ingresses", "httproutes"):
        try:
            items = kube.items(kind, all_namespaces=True)
        except KubeError as exc:
            print(f"skipping {kind}: {exc}", file=sys.stderr)
            continue
        for item in items:
            spec = section(item, "spec")
            # Ingress rules are objects with a host; HTTPRoute hostnames are plain strings.
            rule_hosts = strings([rule.get("host") for rule in entries(spec.get("rules"))])
            hosts += rule_hosts + strings(spec.get("hostnames"))
    return sorted(set(hosts))


CONFIGURED_HOST = re.compile(r"https?://([a-z0-9-]+(?:\.[a-z0-9-]+){2,})")


def configured_hosts(kube: Kube) -> list[str]:
    """Hosts in the URLs that the namespace's Deployments and ConfigMaps configure.

    For clusters whose routes this user may not list (Azure RBAC without Gateway API rights).
    """
    found: set[str] = set()
    for kind in ("deployments", "configmaps"):
        for item in kube.items(kind):
            text = json.dumps([item.get("spec"), item.get("data")])
            found.update(CONFIGURED_HOST.findall(text))
    return sorted(host for host in found if ".svc" not in host)


def draft_profile(estate: str, context: str, namespace: str, hosts: list[str], scheme: str) -> dict[str, object]:
    """Draft profile from the cluster's hosts; smoke-only until reviewed."""
    urls: dict[str, str] = {}
    for host in hosts:
        component = component_for_host(host)
        if component and component not in urls:
            urls[component] = f"{scheme}://{host}"
    return {
        "estate": estate,
        "allowed_tiers": ["smoke"],
        "kube": {"context": context, "namespace": namespace},
        "urls": dict(sorted(urls.items())),
        "secrets": {},
    }


def cmd_env_init(args: argparse.Namespace) -> int:
    """Write a draft profile from the cluster's ingresses and HTTPRoutes."""
    envs_dir = Path(args.envs_dir)
    file_name = f"{args.name}.yaml"
    target = envs_dir / file_name if args.estate == "minikube" else envs_dir / args.estate / file_name
    if target.exists() and not args.force:
        print(f"{target} exists; use --force to overwrite", file=sys.stderr)
        return EXIT_CONFIG
    kube = Kube(args.context, args.namespace)
    hosts = ingress_hosts(kube)
    if not any(component_for_host(host) for host in hosts):
        hosts = configured_hosts(kube)
    draft = draft_profile(args.estate, args.context, args.namespace, hosts, args.scheme)
    header = "# Draft from `podiumd-tests env init`; review urls, add secrets and allowed_tiers.\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(header + yaml.safe_dump(draft, sort_keys=False), encoding="utf-8")
    unmapped = [host for host in hosts if component_for_host(host) is None]
    print(f"wrote {target} ({len(draft['urls'])} component URLs)")  # pyright: ignore[reportArgumentType]
    if unmapped:
        print(f"hosts not mapped to a component: {', '.join(unmapped)}")
    return EXIT_OK


def cmd_lock(args: argparse.Namespace) -> int:
    """Show who holds the environment's lock, or break a podiumd-tests hold."""
    env = Environment(_load(args))
    if args.action == "break":
        removed = lock.break_holds(env)
        print("\n".join(f"removed {hold}" for hold in removed) or "no podiumd-tests hold")
    else:
        print("\n".join(lock.holds(env)) or "no lock configured")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run the preflight checks and print them."""
    env = Environment(_load(args))
    checks = doctor.run_checks(env, infra=True)
    print(doctor.checklist(checks))
    if args.json:
        report = json.dumps([asdict(check) for check in checks], indent=2)
        Path(args.json).write_text(f"{report}\n", encoding="utf-8")
    return EXIT_CONFIG if doctor.has_failure(checks) else EXIT_OK


def cmd_standards(args: argparse.Namespace) -> int:
    """Print, or write to --output, the matrix of the environment's workloads against the hosting standards."""
    env = Environment(_load(args))
    found, objects = hygiene.hosting_scope(env)
    chart = workloads.chart_version(env) or "unknown"
    today = datetime.now(UTC).date().isoformat()
    title = f"PodiumD hosting standards on {env.profile.name}, {today} (podiumd chart {chart})"
    report = hygiene.standards_report(found, objects, title)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"written: {args.output}")
    else:
        print(report)
    return EXIT_OK


def _write_or_print(text: str, out: str | None) -> None:
    """Write text to the file out, or print it without one."""
    if out is None:
        print(text, end="")
        return
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(text, encoding="utf-8")
    print(f"written: {out}")


def _is_duration(text: str, option: str) -> bool:
    """Whether text is a duration; prints why not."""
    try:
        parse_duration(text)
    except ValueError as exc:
        print(f"{option}: {exc}", file=sys.stderr)
        return False
    return True


def cmd_estate_export(args: argparse.Namespace) -> int:
    """Write or print the environment's estate profile."""
    if not _is_duration(args.since, "--since"):
        return EXIT_CONFIG
    env = Environment(_load(args))
    _write_or_print(estate_profile.dump(estate_profile.export(env, args.since)), args.out)
    return EXIT_OK


def _target(text: str | None) -> tuple[int, ...] | None:
    """Return --target as a version; ProfileError when it is no dotted version."""
    if text is None:
        return None
    version = workloads.parse_version(text.removeprefix("v"))
    if version is None:
        msg = f"--target {text!r}: expected a chart version such as 4.11.0"
        raise config.ProfileError(msg)
    return version


def cmd_estate_check(args: argparse.Namespace) -> int:
    """Print the release rules' findings on a profile; 1 when one needs an action or a fact."""
    profile = estate_profile.load(Path(args.profile))
    findings = release_rules.evaluate(profile, _target(args.target))
    print(release_rules.report(profile, findings, args.target), end="")
    return EXIT_ACTION_NEEDED if release_rules.is_action_needed(findings) else EXIT_OK


def _estate_envs(args: argparse.Namespace) -> list[str]:
    """Return the profile names of --envs, or of every profile of --estate."""
    if args.envs:
        return [name.strip() for name in args.envs.split(",") if name.strip()]
    envs_dir = Path(args.envs_dir)
    return [
        name for name in config.list_profiles(envs_dir) if config.load_profile(name, envs_dir).estate == args.estate
    ]


def _estate_row(name: str, args: argparse.Namespace, out: Path) -> tuple[str, int]:
    """Export and check one environment into out/<name>/; return its README row and exit code."""
    try:
        profile = estate_profile.export(Environment(config.load_profile(name, Path(args.envs_dir))), args.since)
    except (config.ProfileError, ProcessError) as exc:
        return f"| {name} | unknown | error: {estate_profile.reason(exc)} |", EXIT_CONFIG
    findings = release_rules.evaluate(profile, _target(args.target))
    (out / name).mkdir(parents=True, exist_ok=True)
    (out / name / "profile.yaml").write_text(estate_profile.dump(profile), encoding="utf-8")
    (out / name / "actions.md").write_text(release_rules.report(profile, findings, args.target), encoding="utf-8")
    chart = section(profile, "chart").get("podiumd", "unknown")
    code = EXIT_ACTION_NEEDED if release_rules.is_action_needed(findings) else EXIT_OK
    return f"| {name} | {chart} | {release_rules.open_issues(findings)} |", code


def _settings_env(args: argparse.Namespace) -> Environment | None:
    """Return the environment apply and restore may change, or None after printing why not."""
    env = Environment(_load(args))
    reason = estate_settings.refusal(env.profile)
    if reason:
        print(f"refused: {reason}", file=sys.stderr)
        return None
    return env


def _change_settings(env: Environment, verb: str, change: Callable[[], list[str]]) -> int:
    """Run apply or restore under the environment's lock; return its exit code."""
    try:
        with lock.held(env, f"estate-profile {verb} {env.profile.name}"):
            done = change()
    except lock.LockBusyError as exc:
        print(f"busy: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except estate_settings.StateError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_STATE
    except estate_settings.KEYCLOAK_ERRORS as exc:
        print(f"Keycloak admin access failed on {env.profile.name}: {exc}", file=sys.stderr)
        return EXIT_KEYCLOAK
    print("\n".join(done))
    return EXIT_OK


def cmd_estate_apply(args: argparse.Namespace) -> int:
    """Set a profile's Keycloak settings on a test environment, recording them in --state."""
    profile = estate_profile.load(Path(args.profile))
    env = _settings_env(args)
    if env is None:
        return EXIT_CONFIG
    state = Path(args.state)
    if state.exists():
        print(f"refused: {state} exists; run `estate-profile restore` first", file=sys.stderr)
        return EXIT_CONFIG
    return _change_settings(env, "apply", lambda: estate_settings.apply(env, profile, state))


def cmd_estate_restore(args: argparse.Namespace) -> int:
    """Undo what apply recorded in --state."""
    env = _settings_env(args)
    if env is None:
        return EXIT_CONFIG
    return _change_settings(env, "restore", lambda: estate_settings.restore(env, Path(args.state)))


def cmd_estate_report(args: argparse.Namespace) -> int:
    """Export and check each environment into --out, with a README table; an environment that fails gets a row."""
    if not _is_duration(args.since, "--since"):
        return EXIT_CONFIG
    _target(args.target)
    out = Path(args.out)
    rows = [_estate_row(name, args, out) for name in _estate_envs(args)]
    today = datetime.now(UTC).date().isoformat()
    lines = [
        "# Estate profiles",
        "",
        f"`podiumd-tests estate-profile report` of {today}, target {args.target or 'any'}.",
        "",
        "| env | podiumd chart | actions needed |",
        "| --- | --- | --- |",
        *(row for row, _ in rows),
    ]
    _write_or_print("\n".join([*lines, ""]), str(out / "README.md"))
    return max((code for _, code in rows), default=EXIT_OK)


def _is_defined(node_id: str) -> bool:
    """Whether the node id's file defines its test function; pytest on xdist runs nothing for an unknown one."""
    name = node_id.rsplit("::", maxsplit=1)[-1].split("[", maxsplit=1)[0]
    source = (config.REPO_ROOT / node_id.split("::", maxsplit=1)[0]).read_text(encoding="utf-8")
    return re.search(rf"^\s*(?:async\s+)?def {re.escape(name)}\(", source, re.MULTILINE) is not None


def pytest_selection(
    profile: config.Profile, tier_name: str, run_id: str, junit: Path, args: argparse.Namespace
) -> list[str]:
    """Return the pytest arguments of a run: the tier's paths and markers, the run tag and the results files."""
    tier = TIERS[tier_name]
    paths = [str(config.REPO_ROOT / path) for path in tier.paths if (config.REPO_ROOT / path).is_dir()]
    positional = [arg for arg in args.pytest_args if not arg.startswith("-")]
    given = [arg for arg in positional if (config.REPO_ROOT / arg.split("::")[0]).exists()]
    outside = [
        arg for arg in given if not any((config.REPO_ROOT / arg).resolve().is_relative_to(path) for path in paths)
    ]
    if outside:
        msg = f"not in tier {tier_name}: {', '.join(outside)} (its paths: {', '.join(tier.paths)})"
        raise config.ProfileError(msg)
    unknown = [arg for arg in given if "::" in arg and not _is_defined(arg)]
    if unknown:
        msg = (
            f"no such test: {', '.join(unknown)} (a node id names a test function, without the report's @group suffix)"
        )
        raise config.ProfileError(msg)
    # Paths after -- narrow the tier; pytest would otherwise run them and the tier's paths.
    selection = [
        *([] if given else paths),
        "-m",
        tier.marker_expression,
        f"--podiumd-env={profile.name}",
        f"--podiumd-envs-dir={args.envs_dir}",
        f"--junitxml={junit}",
        f"--podiumd-progress={junit.parent / 'progress.log'}",
    ]
    selection.append(f"--podiumd-run-tag={results.run_tag(run_id)}")
    # A screenshot of each failed browser test in artifacts/<test-id>/. No Playwright traces:
    # they record what a test types, test passwords included (R8).
    selection += [f"--output={junit.parent / 'artifacts'}", "--screenshot=only-on-failure"]
    selection += [f"--html={junit.parent / 'report.html'}", "--self-contained-html"]
    if args.keep_data:
        selection.append("--keep-data")
    workers = int(profile.settings.get("pytest_workers", default_workers(os.cpu_count())))
    if tier.parallel and workers > 1:
        selection += ["-n", str(workers)]
    return [*selection, *args.pytest_args]


def _is_preflight_ok(env: Environment, args: argparse.Namespace, *, infra: bool = False) -> bool:
    if args.skip_doctor:
        return True
    checks = doctor.run_checks(env, infra=infra)
    if doctor.has_failure(checks):
        print(doctor.checklist([check for check in checks if check.status == "fail"]), file=sys.stderr)
        return False
    return True


def _bootstrap_env(args: argparse.Namespace) -> Environment | int:
    """Return the environment for bootstrap and unbootstrap, or the exit code that stops them."""
    profile = _load(args)
    env = Environment(profile)
    if not _is_preflight_ok(env, args):
        return EXIT_CONFIG
    reason = env.capabilities.skip_reason(CLUSTER)
    if reason:
        print(f"bootstrap needs kubectl access to {profile.name}: {reason}", file=sys.stderr)
        return EXIT_CONFIG
    return env


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Create the test-only credentials and wiring."""
    reason = refusal(_load(args))
    if reason:
        print(f"refused: {reason}", file=sys.stderr)
        return EXIT_NOT_ALLOWED
    return _apply_steps(args, "bootstrap", lambda env, steps: bootstrap(env, steps, rotate=args.rotate))


def cmd_unbootstrap(args: argparse.Namespace) -> int:
    """Remove everything bootstrap created."""
    return _apply_steps(args, "unbootstrap", unbootstrap)


def _apply_steps(
    args: argparse.Namespace, verb: str, action: Callable[[Environment, Sequence[Step]], list[Outcome]]
) -> int:
    """Run action on the selected steps while holding the environment's lock."""
    env = _bootstrap_env(args)
    if isinstance(env, int):
        return env
    steps = selected_steps(args.step)
    with lock.held(env, f"{verb} {env.profile.name}"), env.kube.shells_kept():
        outcomes = action(env, steps)
    print(outcome_report(outcomes))
    return EXIT_CONFIG if has_failure(outcomes) else EXIT_OK


def cmd_sweep(args: argparse.Namespace) -> int:
    """Delete what test runs left behind: run-tagged objects older than --older-than."""
    if not _is_duration(args.older_than, "--older-than"):
        return EXIT_CONFIG
    cutoff = datetime.now(UTC) - parse_duration(args.older_than)
    reason = refusal(_load(args))
    if reason:
        print(f"refused: {reason}", file=sys.stderr)
        return EXIT_NOT_ALLOWED
    env = Environment(_load(args))
    if not _is_preflight_ok(env, args):
        return EXIT_CONFIG
    if args.dry_run:
        swept = sweep(env, cutoff, dry_run=True)
    else:
        with lock.held(env, f"sweep {env.profile.name}"):
            swept = sweep(env, cutoff, dry_run=False)
    print(sweep_report(swept))
    return EXIT_CONFIG if any(swept_object.action == "failed" for swept_object in swept) else EXIT_OK


def _volume_env(args: argparse.Namespace) -> Environment | int:
    """Return the environment for seed-volume and unseed-volume, or the exit code that stops them."""
    profile = _load(args)
    if "perf" not in profile.allowed_tiers:
        print(f"refused: {profile.name} does not allow tier perf (allowed_tiers), so no volume data", file=sys.stderr)
        return EXIT_NOT_ALLOWED
    env = Environment(profile)
    return env if _is_preflight_ok(env, args) else EXIT_CONFIG


def cmd_seed_volume(args: argparse.Namespace) -> int:
    """Top the environment's volume data up to the scale's counts."""
    env = _volume_env(args)
    if isinstance(env, int):
        return env
    with (
        lock.held(env, f"seed-volume {env.profile.name}"),
        volume.faster(env, args.scale_cluster),
    ):
        print(volume.seed_report(volume.seed(env, args.scale, parallel=args.parallel)))
    return EXIT_OK


def cmd_unseed_volume(args: argparse.Namespace) -> int:
    """Delete all volume data."""
    env = _volume_env(args)
    if isinstance(env, int):
        return env
    with lock.held(env, f"unseed-volume {env.profile.name}"):
        print(volume.seed_report(volume.unseed(env)))
    return EXIT_OK


def selected_steps(names: list[str] | None) -> tuple[Step, ...]:
    """All steps, or only the named ones; ProfileError for an unknown name."""
    if not names:
        return STEPS
    unknown = sorted(set(names) - {step.name for step in STEPS})
    if unknown:
        msg = f"unknown bootstrap steps: {', '.join(unknown)} (known: {', '.join(step.name for step in STEPS)})"
        raise config.ProfileError(msg)
    return tuple(step for step in STEPS if step.name in names)


def _versions(env: Environment) -> dict[str, str]:
    """Return the deployed components' versions for run.json; none when the cluster is unreachable."""
    try:
        found = workloads.component_versions(env, sorted(COMPONENTS))
    except KubeError:
        return {}
    return {name: ".".join(map(str, version)) for name, version in found.items()}


def cmd_run(args: argparse.Namespace) -> int:
    """Run a tier against an environment and record the results; a chaos run ends with a smoke run."""
    code = _run_tier(args)
    if args.tier != "chaos" or code == EXIT_NOT_ALLOWED:
        return code
    # The smoke tier shows what a chaos test left broken: a component at 0 replicas, an unhealthy pod.
    smoke = _run_tier(argparse.Namespace(**{**vars(args), "tier": "smoke", "pytest_args": []}))
    return smoke if code == EXIT_OK else code


def _run_tier(args: argparse.Namespace) -> int:
    profile = _load(args)
    if args.tier not in profile.allowed_tiers:
        allowed = ", ".join(profile.allowed_tiers)
        print(f"tier {args.tier!r} is not allowed for {profile.name} (allowed: {allowed})", file=sys.stderr)
        return EXIT_NOT_ALLOWED
    env = Environment(profile)
    with group("doctor"):
        preflight = _is_preflight_ok(env, args, infra=args.tier != "smoke")
    if not preflight:
        return EXIT_CONFIG
    info = results.RunInfo(
        run_id=results.new_run_id(),
        env=profile.name,
        tier=args.tier,
        started=results.now_iso(),
        finished="",
        exit_code=0,
        selection=[],
        suite_commit=results.suite_commit(config.REPO_ROOT),
        chart_version=workloads.chart_version(env),
        build=workloads.deployed_build(env),
        capabilities=sorted(env.capabilities.present),
        versions=_versions(env),
    )
    sink = results.LocalDirSink(Path(args.results_dir))
    directory = results.run_dir(datetime.fromisoformat(info.started), profile.name, args.tier, info.run_id)
    junit = Path(sink.location(f"{directory}/junit.xml"))
    junit.parent.mkdir(parents=True, exist_ok=True)
    info.selection = pytest_selection(profile, args.tier, info.run_id, junit, args)
    # Smoke only reads; every other tier writes to the environment and takes its lock. Policy drops are
    # recorded by the tests that expect them (tests/component/platform/test_network_policy.py), not the run.
    before = _cluster_state(env)
    lower_priority()
    with (
        group(f"pytest {args.tier}"),
        nullcontext() if args.tier == "smoke" else lock.held(env, f"run {args.tier} {profile.name}"),
    ):
        info.exit_code = int(pytest.main(info.selection))
    info.finished = results.now_iso()
    details = results.Details()
    # pytest writes the failure texts as they are; mask secrets as write_run does.
    env.credentials.register_all()
    for written in (junit, junit.parent / "report.html"):
        if written.exists():
            written.write_text(env.redactor.redact(written.read_text(encoding="utf-8")), encoding="utf-8")
    if junit.exists():
        counts, details = results.parse_junit(junit.read_text(encoding="utf-8"))
        info.counts = counts
    after = _cluster_state(env)
    if before and after:
        details.disruptions = [disruption.text for disruption in workloads.disruptions(before, after)]
    results.write_run(sink, directory, info, details, env.redactor)
    publish_summary(Path(sink.location(f"{directory}/summary.md")))
    print(f"results: {sink.location(directory)}")
    if info.exit_code in {pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED}:
        return EXIT_OK
    return EXIT_TESTS_FAILED if info.exit_code == pytest.ExitCode.TESTS_FAILED else EXIT_CONFIG


def _cluster_state(env: Environment) -> workloads.ClusterState | None:
    if CLUSTER not in env.capabilities.present:
        return None
    try:
        return workloads.cluster_state(env)
    except KubeError:
        return None


def _from_env(option: str, default: str | None = None) -> str | None:
    """PODIUMD_TESTS_<OPTION> from the environment, for pipelines, else the default."""
    return os.environ.get(ENV_OPTION_PREFIX + option.upper().replace("-", "_"), default)


def _env_command(add_parser: _AddParser, name: str, help_text: str) -> argparse.ArgumentParser:
    """Return a subcommand with --env, required unless PODIUMD_TESTS_ENV is set."""
    parser = add_parser(name, help=help_text)
    default = _from_env("env")
    parser.add_argument("--env", required=default is None, default=default, help="profile name (or PODIUMD_TESTS_ENV)")
    return parser


def _add_profile_commands(add_parser: _AddParser) -> None:
    """Add the env list, show and init subcommands."""
    env = add_parser("env", help="environment profiles").add_subparsers(dest="env_command", required=True)
    env.add_parser("list", help="list profiles").set_defaults(func=cmd_env_list)
    show = env.add_parser("show", help="show one profile")
    show.add_argument("env", help="profile name")
    show.set_defaults(func=cmd_env_show)
    _add_env_init_command(env.add_parser)


def _add_env_init_command(add_parser: _AddParser) -> None:
    """Add the env init subcommand."""
    init = add_parser("init", help="draft a profile from the cluster's ingresses and HTTPRoutes")
    init.add_argument("name", help="profile name")
    init.add_argument("--estate", choices=config.ESTATES, required=True)
    init.add_argument("--context", required=True, help="kube context")
    init.add_argument("--namespace", default="podiumd", help="application namespace (default: podiumd)")
    init.add_argument("--scheme", choices=("https", "http"), default="https", help="URL scheme (default: https)")
    init.add_argument("--force", action="store_true", help="overwrite an existing profile")
    init.set_defaults(func=cmd_env_init)


def _add_doctor_command(add_parser: _AddParser) -> None:
    """Add the doctor subcommand."""
    doc = _env_command(add_parser, "doctor", "preflight checks for an environment")
    doc.add_argument("--json", help="also write the checks to this JSON file")
    doc.set_defaults(func=cmd_doctor)


def _add_standards_command(add_parser: _AddParser) -> None:
    """Add the standards subcommand."""
    standards = _env_command(add_parser, "standards", "report each workload against the PodiumD hosting standards")
    standards.add_argument("--output", help="Markdown file to write the report to (default: print it)")
    standards.set_defaults(func=cmd_standards)


def _add_lock_command(add_parser: _AddParser) -> None:
    """Add the lock subcommand."""
    locking = _env_command(add_parser, "lock", "show the environment's lock holders, or break a podiumd-tests hold")
    locking.add_argument("action", choices=("status", "break"), nargs="?", default="status")
    locking.set_defaults(func=cmd_lock)


def _add_bootstrap_commands(add_parser: _AddParser) -> None:
    """Add the bootstrap and unbootstrap subcommands."""
    boot = _env_command(add_parser, "bootstrap", "create test-only credentials and wiring, named ptest-bootstrap-*")
    boot.add_argument("--rotate", action="store_true", help="recreate every step with new credentials")
    boot.add_argument("--skip-doctor", action="store_true")
    boot.add_argument("--step", action="append", help="only this step (repeatable; default: all)")
    boot.set_defaults(func=cmd_bootstrap)

    unboot = _env_command(add_parser, "unbootstrap", "remove everything bootstrap created")
    unboot.add_argument("--skip-doctor", action="store_true")
    unboot.add_argument("--step", action="append", help="only this step (repeatable; default: all)")
    unboot.set_defaults(func=cmd_unbootstrap)


def _add_volume_commands(add_parser: _AddParser) -> None:
    """Add the seed-volume and unseed-volume subcommands."""
    vol = _env_command(add_parser, "seed-volume", "top up the perf tier's volume data, tagged ptest-volume")
    vol.add_argument("--scale", choices=["smoke", "perf"], default="smoke", help="counts to reach (default: smoke)")
    vol.add_argument("--parallel", type=int, default=8, help="concurrent creates (default 8)")
    vol.add_argument(
        "--scale-cluster", type=int, default=0, help="run Open Zaak, Open Klant and workers at N replicas meanwhile"
    )
    vol.add_argument("--skip-doctor", action="store_true")
    vol.set_defaults(func=cmd_seed_volume)

    unvol = _env_command(add_parser, "unseed-volume", "delete all volume data")
    unvol.add_argument("--skip-doctor", action="store_true")
    unvol.set_defaults(func=cmd_unseed_volume)


def _add_sweep_command(add_parser: _AddParser) -> None:
    """Add the sweep subcommand."""
    swp = _env_command(add_parser, "sweep", "delete run-tagged objects that test runs left behind")
    swp.add_argument(
        "--older-than", default="24h", help="only runs that started before this age: 30m, 24h, 7d (default: 24h)"
    )
    swp.add_argument("--dry-run", action="store_true", help="list what would be deleted")
    swp.add_argument("--skip-doctor", action="store_true")
    swp.set_defaults(func=cmd_sweep)


def _add_run_command(add_parser: _AddParser) -> None:
    """Add the run subcommand."""
    run = _env_command(add_parser, "run", "run a tier against an environment")
    run.add_argument(
        "--tier", choices=sorted(TIERS), default=_from_env("tier", "smoke"), help="tier to run (default: smoke)"
    )
    run.add_argument(
        "--results-dir",
        default=_from_env("results-dir", str(config.REPO_ROOT / "results")),
        help="results directory (default: results/)",
    )
    run.add_argument("--keep-data", action="store_true", help="skip cleanup of created resources")
    run.add_argument("--skip-doctor", action="store_true")
    run.add_argument("pytest_args", nargs=argparse.REMAINDER, help="extra pytest arguments after --")
    run.set_defaults(func=cmd_run)


def _add_estate_profile_commands(add_parser: _AddParser) -> None:
    """Add the estate-profile subcommands."""
    estate = add_parser("estate-profile", help="the settings of an environment that decide how an upgrade goes")
    commands = estate.add_subparsers(dest="estate_command", required=True).add_parser
    export = _env_command(commands, "export", "read an environment's estate profile; read-only")
    export.add_argument("--out", help="YAML file to write (default: print it)")
    _add_since(export)
    export.set_defaults(func=cmd_estate_export)
    check = commands("check", help="list the actions a profile needs before an upgrade; exit 1 when any")
    check.add_argument("--profile", required=True, help="estate profile YAML file")
    _add_target(check)
    check.set_defaults(func=cmd_estate_check)
    _add_estate_report_command(commands)
    _add_estate_settings_commands(commands)


def _add_estate_settings_commands(add_parser: _AddParser) -> None:
    """Add the estate-profile apply and restore subcommands."""
    state_help = "JSON file that records what apply changed, secrets included"
    apply = _env_command(add_parser, "apply", "set a profile's Keycloak master settings on a test environment")
    apply.add_argument("--profile", required=True, help="estate profile YAML file")
    apply.add_argument("--state", required=True, help=f"{state_help}; must not exist")
    apply.set_defaults(func=cmd_estate_apply)
    restore = _env_command(add_parser, "restore", "undo what apply recorded and delete the state file")
    restore.add_argument("--state", required=True, help=state_help)
    restore.set_defaults(func=cmd_estate_restore)


def _add_since(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--since", default="24h", help="window of the Keycloak log signals (default: 24h)")


def _add_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", help="podiumd chart version to upgrade to (default: any)")


def _add_estate_report_command(add_parser: _AddParser) -> None:
    """Add the estate-profile report subcommand."""
    report = add_parser("report", help="export and check many environments into one folder; read-only")
    chosen = report.add_mutually_exclusive_group(required=True)
    chosen.add_argument("--envs", help="profile names, comma-separated")
    chosen.add_argument("--estate", choices=config.ESTATES, help="every profile of this estate")
    report.add_argument("--out", required=True, help="folder for <env>/profile.yaml, <env>/actions.md and README.md")
    _add_since(report)
    _add_target(report)
    report.set_defaults(func=cmd_estate_report)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of `podiumd-tests`."""
    parser = argparse.ArgumentParser(
        prog="podiumd-tests",
        description=__doc__,
        epilog="--env, --tier, --results-dir and --envs-dir can also come from PODIUMD_TESTS_<OPTION>.",
    )
    parser.add_argument(
        "--envs-dir",
        default=_from_env("envs-dir", str(config.default_envs_dir())),
        help="profile directory (default: envs/)",
    )
    add_parser = parser.add_subparsers(dest="command", required=True).add_parser
    for add_commands in (
        _add_profile_commands,
        _add_doctor_command,
        _add_standards_command,
        _add_lock_command,
        _add_bootstrap_commands,
        _add_volume_commands,
        _add_sweep_command,
        _add_run_command,
        _add_estate_profile_commands,
    ):
        add_commands(add_parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point of the `podiumd-tests` console script."""
    args = build_parser().parse_args(argv)
    if getattr(args, "pytest_args", None) and args.pytest_args[0] == "--":
        args.pytest_args = args.pytest_args[1:]
    try:
        return int(args.func(args))
    except config.ProfileError as exc:
        print(f"profile error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except ProcessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except lock.LockBusyError as exc:
        print(f"busy: {exc}", file=sys.stderr)
        return EXIT_BUSY


if __name__ == "__main__":
    sys.exit(main())
