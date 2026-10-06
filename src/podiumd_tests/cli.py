"""The `podiumd-tests` command (PLAN.md §7a, §8b).

Exit codes: 0 pass, 1 test failures, 2 configuration or preflight error,
3 tier not allowed for the environment.
"""

from __future__ import annotations

import argparse
import json
import sys

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from podiumd_tests import doctor
from podiumd_tests.components import component_for_host
from podiumd_tests.config import ESTATES
from podiumd_tests.config import REPO_ROOT
from podiumd_tests.config import Profile
from podiumd_tests.config import ProfileError
from podiumd_tests.config import default_envs_dir
from podiumd_tests.config import list_profiles
from podiumd_tests.config import load_profile
from podiumd_tests.environment import Environment
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings
from podiumd_tests.kube import Kube
from podiumd_tests.kube import KubeError
from podiumd_tests.results import LocalDirSink
from podiumd_tests.results import RunInfo
from podiumd_tests.results import new_run_id
from podiumd_tests.results import now_iso
from podiumd_tests.results import parse_junit
from podiumd_tests.results import run_dir
from podiumd_tests.results import run_tag
from podiumd_tests.results import suite_commit
from podiumd_tests.results import write_run
from podiumd_tests.tiers import TIERS

EXIT_OK = 0
EXIT_TESTS_FAILED = 1
EXIT_CONFIG = 2
EXIT_NOT_ALLOWED = 3


def _load(args: argparse.Namespace) -> Profile:
    return load_profile(args.env, Path(args.envs_dir))


def cmd_env_list(args: argparse.Namespace) -> int:
    """List all profiles."""
    for name, path in list_profiles(Path(args.envs_dir)).items():
        print(f"{name:20} {path.relative_to(Path(args.envs_dir))}")
    return EXIT_OK


def cmd_env_show(args: argparse.Namespace) -> int:
    """Show one profile."""
    profile = _load(args)
    print(f"{profile.name} ({profile.estate}) context={profile.kube.context} namespace={profile.kube.namespace}")
    print(f"allowed tiers: {', '.join(profile.allowed_tiers)}")
    for component, url in sorted(profile.urls.items()):
        print(f"  {component:20} {url}")
    return EXIT_OK


def ingress_hosts(kube: Kube) -> list[str]:
    """Hosts of all Ingresses and HTTPRoutes in the cluster; a missing kind (no Gateway API) is skipped."""
    hosts: list[str] = []
    for kind in ("ingresses", "httproutes"):
        try:
            items = kube.items(kind, all_namespaces=True)
        except KubeError as exc:
            print(f"skipping {kind}: {exc}", file=sys.stderr)  # e.g. no Gateway API on this cluster
            continue
        for item in items:
            spec = section(item, "spec")
            # Ingress rules are objects with a host; HTTPRoute hostnames are plain strings.
            hosts += strings([r.get("host") for r in entries(spec.get("rules"))]) + strings(spec.get("hostnames"))
    return sorted(set(hosts))


def draft_profile(estate: str, context: str, namespace: str, hosts: list[str], scheme: str) -> dict[str, object]:
    """Draft profile contents from the hosts found in the cluster; smoke-only until reviewed."""
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
    target = (
        envs_dir / f"{args.name}.yaml" if args.estate == "minikube" else envs_dir / args.estate / f"{args.name}.yaml"
    )
    if target.exists() and not args.force:
        print(f"{target} exists; use --force to overwrite", file=sys.stderr)
        return EXIT_CONFIG
    hosts = ingress_hosts(Kube(args.context, args.namespace))
    draft = draft_profile(args.estate, args.context, args.namespace, hosts, args.scheme)
    header = "# Draft from `podiumd-tests env init`; review urls, add secrets and allowed_tiers.\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(header + yaml.safe_dump(draft, sort_keys=False), encoding="utf-8")
    unmapped = [h for h in hosts if component_for_host(h) is None]
    print(f"wrote {target} ({len(draft['urls'])} component URLs)")  # pyright: ignore[reportArgumentType]
    if unmapped:
        print("hosts not mapped to a component: " + ", ".join(unmapped))
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run the preflight checks and print them."""
    env = Environment(_load(args))
    checks = doctor.run_checks(env)
    print(doctor.format_checks(checks))
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(c) for c in checks], indent=2) + "\n", encoding="utf-8")
    return EXIT_CONFIG if doctor.failed(checks) else EXIT_OK


def _pytest_selection(
    profile: Profile, tier_name: str, run_id: str, junit: Path, args: argparse.Namespace
) -> list[str]:
    tier = TIERS[tier_name]
    paths = [str(REPO_ROOT / p) for p in tier.paths if (REPO_ROOT / p).is_dir()]
    selection = [*paths, "-m", tier.marker_expression, f"--podiumd-env={profile.name}", f"--junitxml={junit}"]
    selection.append(f"--podiumd-run-tag={run_tag(run_id)}")
    if args.keep_data:
        selection.append("--keep-data")
    return [*selection, *args.pytest_args]


def _preflight_ok(env: Environment, args: argparse.Namespace) -> bool:
    if args.skip_doctor:
        return True
    checks = doctor.run_checks(env)
    if doctor.failed(checks):
        print(doctor.format_checks([c for c in checks if c.status == "fail"]), file=sys.stderr)
        return False
    return True


def cmd_run(args: argparse.Namespace) -> int:
    """Run a tier against an environment and record the results."""
    profile = _load(args)
    if args.tier not in profile.allowed_tiers:
        allowed = ", ".join(profile.allowed_tiers)
        print(f"tier {args.tier!r} is not allowed for {profile.name} (allowed: {allowed})", file=sys.stderr)
        return EXIT_NOT_ALLOWED
    env = Environment(profile)
    if not _preflight_ok(env, args):
        return EXIT_CONFIG
    info = RunInfo(
        run_id=new_run_id(),
        env=profile.name,
        tier=args.tier,
        started=now_iso(),
        finished="",
        exit_code=0,
        selection=[],
        suite_commit=suite_commit(REPO_ROOT),
        chart_version=profile.chart_version,
        capabilities=sorted(env.capabilities.present),
    )
    sink = LocalDirSink(Path(args.results_dir))
    directory = run_dir(datetime.fromisoformat(info.started), profile.name, args.tier, info.run_id)
    junit = Path(sink.location(f"{directory}/junit.xml"))
    junit.parent.mkdir(parents=True, exist_ok=True)
    info.selection = _pytest_selection(profile, args.tier, info.run_id, junit, args)
    info.exit_code = int(pytest.main(info.selection))
    info.finished = now_iso()
    failures = []
    if junit.exists():
        info.counts, failures = parse_junit(junit.read_text(encoding="utf-8"))
    write_run(sink, directory, info, failures, env.redactor)
    print(f"results: {sink.location(directory)}")
    if info.exit_code in {pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED}:
        return EXIT_OK
    return EXIT_TESTS_FAILED if info.exit_code == pytest.ExitCode.TESTS_FAILED else EXIT_CONFIG


def build_parser() -> argparse.ArgumentParser:
    """The argument parser of `podiumd-tests`."""
    parser = argparse.ArgumentParser(prog="podiumd-tests", description=__doc__)
    parser.add_argument("--envs-dir", default=str(default_envs_dir()), help="directory with environment profiles")
    commands = parser.add_subparsers(dest="command", required=True)

    env = commands.add_parser("env", help="environment profiles").add_subparsers(dest="env_command", required=True)
    env.add_parser("list", help="list profiles").set_defaults(func=cmd_env_list)
    show = env.add_parser("show", help="show one profile")
    show.add_argument("env")
    show.set_defaults(func=cmd_env_show)
    init = env.add_parser("init", help="draft a profile from the cluster's ingresses and HTTPRoutes")
    init.add_argument("name")
    init.add_argument("--estate", choices=ESTATES, required=True)
    init.add_argument("--context", required=True)
    init.add_argument("--namespace", default="podiumd")
    init.add_argument("--scheme", choices=("https", "http"), default="https")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_env_init)

    doc = commands.add_parser("doctor", help="preflight checks for an environment")
    doc.add_argument("--env", required=True)
    doc.add_argument("--json", help="also write the checks to this JSON file")
    doc.set_defaults(func=cmd_doctor)

    run = commands.add_parser("run", help="run a tier against an environment")
    run.add_argument("--env", required=True)
    run.add_argument("--tier", choices=sorted(TIERS), default="smoke")
    run.add_argument("--results-dir", default=str(REPO_ROOT / "results"))
    run.add_argument("--keep-data", action="store_true", help="skip cleanup, for debugging")
    run.add_argument("--skip-doctor", action="store_true")
    run.add_argument("pytest_args", nargs=argparse.REMAINDER, help="extra pytest arguments after --")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point of the `podiumd-tests` console script."""
    args = build_parser().parse_args(argv)
    if getattr(args, "pytest_args", None) and args.pytest_args[0] == "--":
        args.pytest_args = args.pytest_args[1:]
    try:
        return int(args.func(args))
    except ProfileError as exc:
        print(f"profile error: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
