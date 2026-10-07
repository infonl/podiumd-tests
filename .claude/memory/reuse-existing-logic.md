---
name: reuse-existing-logic
description: "One concept, one place in podiumd-tests; check the shared helpers in src/podiumd_tests before writing new code"
metadata:
  type: feedback
---

# One concept, one place

Adapted (2026-10-06) from the user's rule for helm-charts `charts/podiumd/bin/`
(`dimpact-samenwerking/helm-charts/.claude/memory/reuse-existing-logic.md`).
Applies to all of podiumd-tests: `src/podiumd_tests/`, `tests/` and
`unit_tests/`. Code gets better when it gets smaller while keeping the same or
more functionality. A change that adds lines for behaviour that already exists
elsewhere is a regression, even when the tests pass.

**Why:** the user wants a small, consistent code base; this suite merges four
older suites that each had their own copy of the same helpers (PLAN.md R22).

**How to apply:**

## Before writing new code

1. Name the concept, not the function: "is a workload ready", "the realm of a
   login redirect", "a secret of the environment".
2. List the low-level helpers the new code would call (`Kube.items`,
   `metadata_name`, `urlsplit`, `SecretResolver.get`, ...) and grep every
   caller of each. A caller that already computes the same thing is the place
   to extend; do not write a second one.
3. Use the shared entry point when one exists:

   | Concept | Use |
   | --- | --- |
   | starting any external process (kubectl, az, git) | `process.run_checked` (errors are `ProcessError`) |
   | any kubectl call | `Kube` (`run`, `items`, `get_json`, `exec`, `exec_django_shell`, `secret_value`) |
   | objects of a kind in all the environment's namespaces | `Environment.items`, `Environment.workloads` |
   | a value printed by a Django shell snippet | `django_value` |
   | reading parsed JSON (kubectl, API bodies) | `json_data` (`section`, `entries`, `strings`) |
   | HTTP to profile URLs (also host-header mode) | `Environment.session()` / `make_session`; fixture `http` |
   | expected status, its message, 401/403, 5xx, hostname of a URL | `responses` (`expect_status`, `describe`, `REFUSED`, `is_server_error`, `url_host`) |
   | "a component root answers" (doctor and test) | `responses.get_root` + `is_server_error` |
   | a secret / an optional secret | `SecretResolver.get` / `configured`, `optional` (fixture `credentials`); never `os.environ` |
   | which secret sources need the cluster | `SecretSpec.needs_cluster` |
   | per-environment values that are no secret | `Profile.settings` |
   | canonical component names, host and deployment aliases | `COMPONENTS`, `component_for_host`, `deployed_components` |
   | what an environment can do | `Capabilities` and `@pytest.mark.requires(...)`; per-component params: `requiring` |
   | readiness of workloads, pods and Jobs | `workloads` (`unready_workloads`, `unhealthy_pods`, `failed_jobs`) |
   | Keycloak realm URLs, login redirect, tokens | `realm_url`, `discovery_url`, `keycloak_login_realm`, `password_grant` |
   | ZGW tokens and request headers | `zgw_jwt`, `zgw_headers` |
   | Grafana, Prometheus targets, Loki | `Grafana`, `grafana_auth`, `down_targets`, `target_count` |
   | Frank!Gateway no-route | `is_no_route` |
   | waiting for a condition | `wait_until` (never sleep) |
   | cleanup of created data / run tag | `ResourceRegistry` (fixture `registry`) / `results.run_tag` |
   | masking secrets in output | `Redactor` |
   | writing run results | `ResultsSink` / `write_run` |
   | repository root, tier names | `config.REPO_ROOT`, `tiers.TIERS` |
   | unit test fakes | fixtures `fake_runner`, `env_factory`, `fake_http`, `response_factory`, `profile_factory` |

   When porting a source test, first reuse the helpers of MK, PI, TA or EX
   (R22), ported once into `src/`.

## doctor and the tests

- When `doctor` and a test check the same thing (a deployment ready, a URL
  answering, a secret resolving), both call the same function in `src/`:
  doctor reports it, the test asserts it. Neither side gets its own copy.
- Fix a bug in the shared function, never in only doctor or only the test.

## While changing code

- Logic lives in `src/podiumd_tests/` with unit tests; test modules in
  `tests/` stay thin.
- A near-copy of existing code is merged in the same change, including copies
  that differ only in a detail.
- A split or move of code also merges the pieces that do the same thing;
  never leave a re-export facade.

## Before committing

- `./run_python_checks` passes, including jscpd (copied code) and vulture.
- New comments, docstrings and help texts are reviewed against [[comments-and-help-texts]].
- Review the diff for "where else is this computed?": for each new function,
  search for the same concept by its low-level helpers (step 2 above),
  preferably with a review subagent that has not seen the change being
  written.
- The commit message names the existing functions that were checked, and
  which one was extended or why none fit. Related: [[feedback-commits]].
