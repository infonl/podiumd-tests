# podiumd-tests — consolidation plan

Version 6, 2026-10-05. It includes the user's answers to five rounds of questions (§9).

Goal: one Python/pytest suite, to become `github.com/infonl/podiumd-tests`. It replaces and merges four test sources:

| Code | Source | Language | Size | Role in the merge |
|---|---|---|---|---|
| TA | `icatt-menselijk-digitaal/podiumd-testautomation` | Playwright TS, bash, k6 | ~450 tests, a folder per release | main body: component, integration, UI, perf |
| MK | `infonl/podiumd-minikube/tests` | pytest | 13 files | infra and wiring checks, productaanvraag chain, minikube access mode |
| PI | `icatt-menselijk-digitaal/podiumd-infra/tests` | pytest | 14 files | the AKS port of MK. Also adds `test_zac_zaakafhandelparameters.py` and `test_4_8_5_upgrade.py` (image pins, securityContext; becomes a version-neutral "deployment hygiene" component test plus `known_issues`), and the Key Vault test-user recipe |
| EX | `scctwente/ExternalsPodiumD/smoke-tests` | Playwright TS | ~15 smoke specs | the TA smoke specs adapted to the gemeente environments. Also adds `lib/urls.ts` (host and alias helpers), the `generate-env.sh` logic (in-cluster JWT signing, PABC key from pod env), `seed-identities.sh` / `unseed-identities.sh` |

The overlap is large: the smoke specs exist in TA and EX, and the infra checks exist in MK and PI. `MIGRATION.md` keeps one row per source test (§10).

The suite targets minikube, the ICATT AKS environments (podiumd-infra) and the SSC Twente gemeente environments (ExternalsPodiumD).

Research notes:

- `docs/research/podiumd-testautomation.md`
- `docs/research/podiumd-minikube.md`
- `docs/research/qa-environments.md`

## 1. Findings that drive the design

1. **The TA version folders hold almost no real version logic.** What differs between them is environment hosts, Django models used in the seed scripts, a few specs for new chart features, and commented-out tests. Capability detection plus a small known-issues file can replace all of that.
2. **The three environment estates are wired differently.** None of this can be guessed, so it is configured per environment:

   | | minikube | podiumd-infra (A) | ExternalsPodiumD (B) |
   |---|---|---|---|
   | Hosts | `<app>.local` through the Traefik IP and a `Host` header | `<app>.<env>.pd.test-rig.nl` | `<stage>-<app>.<domain>` |
   | App aliases | — | KISS=`contact`, OI=`portaal`, OAB=`abc` | KISS=`contact`, OI=`mijn`, Grafana=`podiumd-logs` |
   | Ingress | Traefik | Traefik or APISIX | Gateway API (NGF) |
   | Kube context | minikube | `podiumd-<env>-aks` | `aks-blue-<stage>-<g>` |
   | Secrets | dev defaults | KV `podiumd-<env>-kv` | KV `kv-<stage>-<g>` (other tenant) |
   | Chart versions | local or any | 4.7.5 – 4.9.0 | 4.6.6 – 4.9.1 |
3. **Which components are deployed varies a lot per environment.** ZAC, KISS, ITA, OAB, OI, OMC and zaakbrug are each on or off depending on the environment. Keycloak comes in two flavours (operator vs legacy). Some names are changed with `fullnameOverride`.
4. **Nobody cleans up.** TA has a separate cleanup spec, because leftover zaken push new ones off `/mijn-zaken` page 1.
5. **Seeding relies on `kubectl exec … manage.py shell` everywhere.** That is acceptable here, because the suite runs from a console that has kubectl access (§9).
6. **Secrets are committed in plaintext in other repos**: podiumd-infra values files and certs, and ExternalsPodiumD env templates. The new suite must not read secrets from those files. It must not copy that pattern either. See §11a for what this means for the tests.

## 2. Requirements

| # | Requirement |
|---|---|
| R1 | Python 3.12+ and pytest only. Playwright-python for UI. Locust for perf (§6). No bash or TS in the test logic. External CLIs are limited to what the environments already need: `kubectl`, `helm` and `az`, called through `subprocess`. |
| R2 | Tests are self-contained. Fixtures seed, the test runs, finalizers clean up, and cleanup runs on failure too. |
| R3 | Tests are grouped `smoke`, `component`, `integration`, plus a separate `perf` (§3). |
| R4 | No folder per release. Use capability detection, compat adapters and `known_issues.yaml` (§5). |
| R5 | **Self-sufficient repo.** Everything the tests need lives here: the env bootstrap, mocks, the webhook receiver, mail sink manifests and test identities. The suite never depends on changes to the podiumd helm charts, podiumd-infra or ExternalsPodiumD. It only reads the deployed environment. |
| R6 | **Console-first.** `podiumd-tests run --env kees00 smoke` works from a laptop with kubectl and az set up. CI-ready from day one: no interactive prompts, everything set through config or env vars, exit codes, JUnit output. Pipeline wiring comes later (phase 7). |
| R7 | **Environment profiles.** One YAML per environment holds per-component base URLs, the kube context and namespace(s), the secret sources and any overrides. A `podiumd-tests env init` command generates a draft from the cluster's ingress and HTTPRoute objects. |
| R8 | **Secrets are never stored in the repo.** Order of resolution: env var, then in-cluster lookup (k8s secret, pod env, `manage.py shell` such as OZ `JWTSecret`), then Azure Key Vault (`az`). The exception is the well-known minikube dev defaults. |
| R9 | **Safe on shared environments.** Every created object is run-tagged (`ptest-<runid>`). Tests touch only their own data. Destructive and chaos tests are opt-in (`--destructive`). |
| R10 | **Parallel-safe** (`pytest-xdist`), with no ordering dependencies between tests. |
| R11 | **No fixed sleeps.** Use the `wait_until(predicate, timeout, interval)` helper. |
| R12 | **Deterministic skips.** A missing capability is a skip with a reason. A known breakage is a strict `xfail` with a ticket. Never comment out a test. |
| R13 | **Shared typed clients and auth.** ZGW JWT, Keycloak tokens, a browserless OIDC flow, the Django two-factor admin login, and a `browser_session` that returns cookies for API calls. |
| R14 | **Ingress-neutral assertions.** Follow redirects and assert on the final page or JSON. Never assert a 302 vs 303 status code. |
| R15 | **Traceability.** `@pytest.mark.tc("<draaiboek-id>")`, plus a coverage report. |
| R16 | **Fast, read-only smoke.** Under 2 minutes, and safe for any environment. |
| R17 | **Preflight (`podiumd-tests doctor --env X`).** A read-only check of everything a run needs, without running any test (§8b). It runs on its own, and as a short version at the start of every `run`, `bootstrap` and `perf`. Each failed check is one line, with a fix hint. Exit code 2. |
| R18 | **Each run records its environment.** Every run writes a `run.json` with the environment, chart version, detected component image tags, capabilities, the suite's git SHA and the selection used. This makes results comparable across versions without folders per version (§7). |
| R19 | **Code quality: the same checks as podiumd.** Use the checks and settings of `helm-charts/charts/podiumd/bin/run_python_checks` and its `pyproject.toml`, unchanged (§8a). |
| R20 | **Allowed scope per environment.** Each profile has an `allowed_tiers` setting, for example `[smoke]` for a gemeente environment that may only receive smoke tests, or `[smoke, core, full, perf]`. The CLI refuses `bootstrap`, `seed-volume` and every tier outside the list. It says why, and offers no override flag. Several ExternalsPodiumD environments are smoke-only; others run the full set. |
| R21 | **Pipeline-neutral execution (§7a).** There is no pipeline-specific code in the suite. |
| R22 | **Minimal toolset, reuse first.** Add no language, framework or library unless existing ones cannot do the job. Before writing new code, reuse the existing code: the stdlib, the libraries the source suites already use (`requests`, `PyYAML`, Playwright; ZGW JWTs are signed with the stdlib, as in MK, so no JWT library), and the MK, PI and EX helpers. A new dependency needs a one-line reason in `pyproject.toml`. That rules out, for example, `httpx` (use `requests`), `pydantic-settings` (use dataclasses plus `PyYAML`), `tenacity` (use a small `wait_until`), the `kubernetes` Python client (use the `kubectl` CLI; reasons in §8), `mypy` (use basedpyright, as in podiumd), pre-commit, and a separate HTML report plugin. |

## 3. Grouping

TA's README sets out these tiers: smoke, interaction, maintenance, regression, full and perf. TA's `debug/` folder sits outside every tier. The new suite separates two things that the TA tiers mix:

- **scope:** what a test touches. These are the groups below, kept as folders and markers.
- **selection:** what you run. These are tier presets.

**Scope groups:**

| Group | Question | Data | Budget | Examples |
|---|---|---|---|---|
| `smoke` | Is it up and wired? | none, read-only | < 2 min total | pods Ready; ingress reachable; health endpoints (KISS BFF, PABC, OMC, FG outway); OIDC discovery; ZGW JWT accepted; Prometheus targets up; Keycloak login page |
| `component` | Does one component's API or config behave? | own seed and cleanup | seconds per test | OZ VA filtering, audit trail, status lifecycle, pagination, validation, documents; OK2 partijen; PABC; Keycloak realm, PKCE and admin-login config |
| `integration` | Do components work together? | own seed and cleanup | 10–120 s per test | OZ→ON→webhook; OF submission→OZ zaak; productaanvraag Objecten→ON→ZAC→OZ; ITA→OK2→portaal; OMC→notify mock; ZAC→FG→OZ; Mailpit |
| `perf` | Are response times acceptable? | volume seed (once per env) | minutes | Locust ports of the k6 scripts; p95 thresholds |

The `component` group was added because about 60% of TA's "regression" tests exercise a single ZGW API. Those tests are cheaper to run and easier to debug than chains across components.

Cross-cutting markers:

- `core`: a key user flow (see below).
- `ui`
- `cluster`: needs kubectl exec.
- `destructive`
- `slow`
- `requires(<capability>)`
- `tc(<id>)`

**How the TA tiers map to the new suite** (`podiumd-tests run --tier <name>`):

| TA tier | TA meaning | New equivalent |
|---|---|---|
| smoke | Apps up and login works | tier `smoke` = group `smoke` |
| interaction | Core user flows (27 files / 56 tests) | tier `core` = `smoke` plus every test marked `core`, across `component` and `integration`. It is a marker, not a folder, because a core flow can be a single-component test or a chain. |
| regression | Everything else | no separate tier. These tests become `component` or `integration` tests without the `core` marker. |
| full | smoke + interaction + regression | tier `full` = all groups except `perf` and `destructive` |
| maintenance | Cleanup specs that mutate data, run separately | **not tests any more.** They become CLI commands: `sweep`, `unbootstrap`, `unseed-volume`. Self-cleaning tests remove the reason for them (TA needed `cleanup-test-zaken` because zaken piled up). |
| perf | k6, p95 thresholds | tier `perf` = group `perf` (§6) |
| (debug) | Exploratory, outside every tier | not ported. Use `--keep-data` and `-k` locally instead. |

Destructive and chaos tests (TA R89, R124, R144) are their own opt-in tier `chaos`. They never run as part of `full`.

## 4. Seeding model

Everything lives in this repo (R5). There are two layers, because some resources cannot be created through an API.

**A. Environment bootstrap: `podiumd-tests bootstrap --env X`.** Idempotent, run once per environment, reversible. Refused for smoke-only profiles (R20).

Decided 2026-10-06, after mapping which source tests need which configuration (`docs/research/platform-wiring.md`): about half of the TA specs need platform wiring that a normal PodiumD deployment does not have, so bootstrap applies it, in two layers.

- **A1. Test-only objects**, all named `ptest-bootstrap-*`, always applied:
  - OZ: an Applicatie and JWT secret for the suite's ZGW client, a test catalogus, and autorisaties limited to that catalogus (`CatalogusAutorisatie`), not `heeft_alle_autorisaties` (§11a);
  - ON: an Applicatie and JWT secret for the suite;
  - OK2 and Objecten tokens;
  - Keycloak test users (KCC medewerker, admin, inwoners, bedrijf) with roles the realm already has.
- **A2. Platform wiring**, the configuration TA's `seed-omgeving.sh` applies (W1–W12 in the research note), applied only when the profile sets `bootstrap.wiring: true`. Default: on for minikube and podiumd-infra, off for ExternalsPodiumD until the environment owner agrees. Without it, the tests that need it skip with a reason, and `doctor` reports what is missing. Order by the number of tests that need it: W1 (DigiD/eHerkenning through Keycloak), W5/W6/W8 (OI CMS pages, OK2 link, contact flow), W9/W10 (OF forms and registration), W3 (ON kanalen), then W7, W11, W12.
- **Only what a test uses:** a step is added together with the first test that needs it, and removed when no test does (`.claude/memory/remove-unused.md`).
- **Rules:**
  - Before a step changes an existing object, it stores the old state in the Secret `podiumd-tests-credentials`; `unbootstrap` restores it. Objects a step created are deleted. Built-ins (such as OI's own `oidc-digid` client) are never deleted.
  - Bootstrap never changes the secrets of the platform's own clients (`open-formulieren`, `open-inwoner`, `zac`, …). Tests use `ptest-bootstrap-*` clients; the restricted Open Formulieren autorisaties of the VA tests go to a separate `ptest-bootstrap-of` client.
  - Credentials it creates live only in the Secret `podiumd-tests-credentials`, written over stdin; `SecretResolver` reads it as its last source.
- Uses public or admin APIs where they exist. Otherwise `kubectl exec manage.py shell` runs Python snippets kept in `src/podiumd_tests/bootstrap/snippets/`, with compat branches for model changes such as the OI `OIDCProvider` migration.
- The test infra from `infra/` (webhook-receiver, notifynl-mock, Mailpit) comes with phase 4, where the integration tests need it. Each piece is a directory of plain manifests that a bootstrap step (`infra-*`) applies with `kubectl apply` and labels `app.kubernetes.io/managed-by=podiumd-tests`; no Helm chart, so no `helm` is needed for it.
- A session fixture `bootstrap_ok` checks the state. If it is missing, it fails fast with "run `podiumd-tests bootstrap --env X`". `--auto-bootstrap` applies it instead.
- This replaces TA `seed-omgeving.sh`, ExternalsPodiumD `seed-identities.sh` and the MK deploy-time Jobs, as far as the tests depend on them.

**B. Test data: per test or per module, through API factories.**

- Factories: `make_catalogus`, `make_zaaktype(publish=True)`, `make_zaak`, `make_document`, `make_partij`, `make_object`, `make_keycloak_user`, `make_form` …
- Each factory registers a deleter in a `ResourceRegistry` fixture, which deletes in reverse order (LIFO) on teardown, even when the test fails. `--keep-data` keeps the data for debugging.
- Scope:
  - Expensive objects are created once per session and run-tagged. Examples: the catalogus with a unique `domein`, and a published zaaktype.
  - Zaken, documents and partijen are created per test.
- Some things cannot be deleted through the API, such as published zaaktypen and audit trails. They stay tagged. `podiumd-tests sweep --older-than 24h` deletes, through the APIs, every run-tagged object whose run started before the cutoff; the run id carries its start minute, so no object timestamp is needed.

**C. Volume seed for perf: `podiumd-tests seed-volume --scale smoke|perf`.**

- A port of TA `seed-test-data` (`src/podiumd_tests/seed/volume.py`), with a matching `unseed-volume`. Built 2026-10-08.
- Kinds and TA's counts (smoke / perf): Keycloak users 5 / 100, zaken 3 / 50 000 (own zaaktype `ptest-volume`), partijen 5 / 2 000, Objecten objects 10 / 1 000 (own objecttype `ptest-volume`), Open Klant internetaken 5 / 100. A profile setting `seed_volume_<kind>` replaces a perf count (minikube seeds less).
- Everything carries `ptest-volume`, no run tag, so sweep leaves it. A rerun tops up to the target. Creating goes through the APIs with the suite's own clients; counting and deleting through Django snippets.
- `--parallel N` (default 8) and `--scale-cluster N` (Open Zaak, Open Klant and their workers at N replicas meanwhile). TA's `--no-notify` is not ported: Open Zaak refuses every write without a Notificaties service. TA's inwoner and kiss modules seeded nothing; its catalogus module is the bootstrap test zaaktype.

## 5. Version independence

1. **Capabilities, not versions.** The session fixture `caps` combines three sources:
   - the profile (which components are deployed, and their URLs);
   - probes (the API root and `API-version` headers, OIDC discovery, objecten classic vs merged layout, Frank!Gateway vs api-proxy, Keycloak flavour);
   - the cluster (deployments, pods, image tags).

   Tests declare `@requires("oab", "frankgateway")`.
2. **Compat adapters, one place per divergence.** For example `compat/objecten.py` and `compat/keycloak.py`. Tests contain no version branches.
3. **`known_issues.yaml` is the only release-aware file.** Each entry holds a test id, a PodiumD version range (`>=4.8.4,<4.9.1`), a reason and a ticket. It becomes a strict xfail. The chart version comes from the profile or from `helm list` / annotations.
4. New chart features are gated on a capability, never on a version number.
5. UI tests select by role or test-id, or use regexes that match both NL and EN labels.

## 6. Perf

**What exists in TA:** `tests/perf/` holds three k6 scripts of 242 lines in total.

- `api-perf.js`: read-only GETs on OZ zaken and zaaktypen, OK2 partijen and BRP, with a p95 < 1500 ms threshold.
- `fg-compare.js`: the same calls directly and through Frank!Gateway, to measure the gateway's overhead.
- `lib.js`: auth helpers.

Two shell wrappers, `run-perf.sh` and `run-fg-compare.sh`, run them. Either way, porting is about a day of work.

**The choice:**

| | k6 (keep) | Locust (port to Python) |
|---|---|---|
| Language | JavaScript scripts, run by a Go binary | Python, the same as the rest of the suite |
| Code reuse | Cannot use the suite's Python clients, auth (ZGW JWT, Keycloak), config profiles or secret resolution. These must be duplicated in JS (TA's `lib.js` does this today). | Reuses `clients/`, `auth/`, profiles and secrets directly. One place to fix when auth changes. |
| Load generation | Very efficient: thousands of virtual users per core | Less efficient per core (gevent). Fine for the current scale (10–50 users); scales out with workers if needed. |
| Thresholds | Built in (`thresholds: {http_req_duration: ['p(95)<1500']}`); k6 exits non-zero when one fails | Not built in. The pytest wrapper reads Locust's stats and asserts the thresholds from `perf.yaml`. |
| Install | An extra binary (k6) on the console and the runner | `pip`, part of the suite's dependencies |
| Reporting | JSON summary; needs conversion into `run.json`/JUnit | Stats CSV/HTML; the wrapper turns them into JUnit test cases, one per endpoint threshold |

**Decision (2026-10-05): Locust.** The k6 scripts are ported to Python.

- Perf runs against the same environments, with the same credentials and profiles, as the other tiers.
- The load levels are modest.
- Reusing the clients and auth matters more than raw load efficiency.

Revisit this only if perf ever needs heavy load (hundreds of users or more).

**How it runs:**

- `podiumd-tests run --env X --tier perf -- --perf-users 10 --perf-duration 60s` runs Locust headless (defaults 5 users, 30 s), as a subprocess: Locust monkey-patches the standard library on import.
- The wrapper in `tests/perf/` (marker `perf`, excluded from `full`) asserts the p95 and error-rate thresholds per endpoint from `perf.yaml`.
- It also compares each endpoint's p95 with the median of the environment's earlier runs with the same settings (at least 3), so a slowdown shows also where absolute numbers mean little, such as minikube.
- Locust's stats and the run's settings go to the run's `perf/` subdirectory.
- The Frank!Gateway compare (TA `fg-compare.js`) waits for an environment with both a gateway and a direct route to Open Zaak.

## 7. Results

Decision: start simple. Results go in the `results/` subdirectory of this repository, one subdirectory per test run. They can be moved to a separate repository or a static site later. To keep that move trivial, all result writing goes through one `ResultsSink` interface, and only `LocalDirSink` exists at first.

```text
results/
  index.md                               # generated: latest run per env, env × chart version × tier matrix
  <YYYY-MM>/                             # one partition level per month
    <YYYYMMDD-HHMMSS>_<env>_<tier>_<runid>/
      run.json        # env, chart version, detected component image tags, capabilities,
                      # suite git SHA, tier and marker selection, counts, duration
      junit.xml
      summary.md      # human-readable: pass/fail/skip/xfail per group, failures with a one-line cause
      perf/           # Locust stats CSV + HTML (perf tier only)
      artifacts/<test-id>/   # Playwright trace, screenshot, HTTP log of one failed test — gitignored by default
```

Example: `results/2026-10/20261005-143012_ontw-icat_smoke_a1b2c3/`.

Layout rules:

- **Name of the run directory:** `_` separates the fields, because environment names contain `-` (for example `ontw-icat`). The timestamp comes first, so a plain `ls` sorts chronologically. The `runid` (6 hex characters) prevents collisions when two runs start in the same second.
- **One partition level by month, and no more.** A busy month with several environments and tiers can hold hundreds of runs, and a directory that grows forever is awkward in git and in a file browser. Months keep listings short and make pruning simple (delete `2026-03/`). A level per environment is not needed, because the environment is in the directory name, and `ls results/*/*_kees00_*` or the generated index filters on it. A level per environment would also split one day's cross-environment runs over many directories.
- **No subdirectories per group inside a run.** `junit.xml` and `summary.md` already split the results by group, so per-group directories would only spread files around. The only subdirectories are `perf/` and `artifacts/<test-id>/`, where one directory per failed test keeps its trace, screenshot and log together.
- **Timestamps:** UTC, and recorded in `run.json` as ISO 8601.

- **Committed:** `run.json`, `junit.xml`, `summary.md` and `index.md`. They are small, diffable text.
- **Not committed by default:** `artifacts/` is large and binary. There is no HTML report: `summary.md` reads well on GitHub, and Playwright traces open in `playwright show-trace` (R22). Turn them on with `--commit-artifacts`, or move them to Git LFS later.
- **No secrets in results.** The HTTP logging layer redacts the `Authorization` and `Cookie` headers and the token fields, and `run.json` never contains credentials. A unit test guards this.
- `podiumd-tests results index` rebuilds `index.md`. `podiumd-tests results prune --keep 20` limits growth.
- `run.json` turns the results into a compatibility record ("4.9.1 on ontw-icat: 212 pass, 3 xfail"). That partly replaces what TA's VERSION-NOTES.md does today.

Later, other `ResultsSink` implementations can publish to a separate results repository, GitHub Pages or an Azure Blob static site.

A history per test case (one test's results across runs) is not stored separately. `results index` can generate it from the `junit.xml` files when it is wanted.

## 7a. Running from a pipeline later

The pipelines are not decided yet. They will likely be GitHub Actions inside podiumd-infra, and Azure DevOps for SSC Twente. The suite therefore assumes nothing about the runner:

- **One entry point:** `podiumd-tests <command>`, a console script declared in `pyproject.toml`. Set it up with `git clone`, then `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/playwright install chromium`. A pipeline does the same, or runs `pip install git+https://github.com/infonl/podiumd-tests`. The `Dockerfile` builds an image with the suite, Chromium (Playwright), kubectl, kubelogin, az and git (no helm: the suite never calls it), for pipelines and for runs from a machine with access, such as SCC Twente's.
- **Configuration:** environment settings live in the profile. A pipeline sets `--env`, `--tier`, `--results-dir` and `--envs-dir` as flags or as `PODIUMD_TESTS_ENV`, `PODIUMD_TESTS_TIER`, `PODIUMD_TESTS_RESULTS_DIR` and `PODIUMD_TESTS_ENVS_DIR`; a flag wins. There are no prompts.
- **Credentials come from the runner.** The suite uses whatever `KUBECONFIG` and context, and whatever `az` login, the runner provides. It never runs a login flow itself. In GitHub Actions that is `azure/login` with OIDC; in Azure DevOps it is an `AzureCLI@2` task or a service connection.
- **Secrets as environment variables:** any secret in the resolution chain can be overridden with `PODIUMD_TESTS_SECRET_<NAME>`. A pipeline can inject secrets from Actions secrets or a DevOps variable group without touching Key Vault.
- **Exit codes:**
  - 0: pass
  - 1: test failures
  - 2: configuration or preflight error
  - 3: environment not allowed (R20)
  - 4: the environment is locked by another run
- **Outputs:**
  - `--results-dir` (default `results/`);
  - `junit.xml`, which both platforms render natively;
  - `summary.md`, ready for `$GITHUB_STEP_SUMMARY` or a DevOps build summary.
- **Stable logs:** `run` folds `doctor` and pytest into collapsible sections (`::group::` on GitHub Actions, `##[group]` on Azure DevOps, nothing elsewhere) and publishes `summary.md` as the step summary (`$GITHUB_STEP_SUMMARY`) or build summary (`##vso[task.uploadsummary]`) (`podiumd_tests/ci.py`).
- **Locking:** every writing command (bootstrap, unbootstrap, sweep, seed-volume, unseed-volume, a run of any tier but smoke) takes a Lease `podiumd-tests-lock` in the environment's namespace when it has cluster access, so console and pipeline runs see each other. The Lease names its holder (user@host and what) and expires after `settings.lock_lease_seconds` (default 3 h); `doctor` reports it. A profile's `settings.lock_file` adds a local lock file shared with other agents on the same machine.

**What phase 7 built (2026-10-08).** The platforms are not decided yet, so the suite ships the pieces each one needs:

- `.github/workflows/checks.yml`: the suite's own code checks on every push and pull request.
- `.github/workflows/run.yml`: a reusable workflow that another repository calls with an environment, a tier and its Azure OIDC identity. It installs the suite, gets the AKS credentials under the profile's kube context (with kubelogin), bootstraps for all tiers but smoke, runs the tier and keeps the results as an artifact. Meant for podiumd-infra's GitHub Actions; a private AKS API needs a self-hosted runner (`runs-on`). Not yet run end to end: that needs podiumd-infra's identity.
- `Dockerfile`: the suite with all its tools, for runs from a machine with access where no pipeline can be created (SCC Twente), and for an Azure DevOps template later.

## 8. Repo layout

The layout is a standard `src/` Python package, chosen for this project:

```text
podiumd-tests/
  pyproject.toml            # the only config file: dependencies, console script, tool settings, pytest markers
  run_python_checks         # adapted from podiumd bin/run_python_checks (§8a)
  README.md  PLAN.md  MIGRATION.md
  docs/research/  docs/decisions/
  envs/                     # environment profiles (non-secret)
    minikube.yaml
    podiumd-infra/<env>.yaml          # kees00, jim01, ...
    externals/<stage>-<g>.yaml        # ontw-icat, ontw-dimp, ...
  known_issues.yaml  perf.yaml
  infra/<piece>/             # webhook-receiver, notifynl-mock, mailpit, alertmanager route: manifests per piece
  results/                  # one directory per run (§7)
  src/podiumd_tests/
    cli.py                  # console script `podiumd-tests`
    doctor.py               # preflight checks (§8b)
    config.py  credentials.py   # profile + secret resolution chain (env → cluster → Key Vault)
    components.py  capabilities.py  environment.py  tiers.py
    process.py  kube.py  sessions.py  wait.py  results.py   # module names avoid shadowing the stdlib (secrets, http)
    pytest_plugin.py        # fixtures (caps, registry, clients, browser_session), markers, known_issues → xfail
    auth/    zgw_jwt.py keycloak.py oidc_flow.py django_admin.py browser_session.py
    clients/ openzaak opennotificaties openklant objecten objecttypen zac kiss ita pabc
             openformulieren openinwoner oab omc frankgateway mailpit webhook_receiver grafana
    compat/  bootstrap/ (+ snippets/)  seed/ (registry + factories)  perf/ (locustfiles)
  tests/                    # environment tests; need a live environment
    conftest.py             # `pytest_plugins = ["podiumd_tests.pytest_plugin"]`
    smoke/  component/<component>/  integration/<chain>/  perf/
  unit_tests/               # offline tests of src/ (no environment)
```

Why this layout:

- **An installable package with a `src/` layout.** One `pip install -e '.[dev]'` gives the `podiumd-tests` command and importable code. No `sys.path` tweaks are needed, so ruff E402 exceptions are not needed either.
- **One config file.** `pyproject.toml` holds the runtime dependencies (`[project.dependencies]`), the check tools (`[project.optional-dependencies] dev`), the console script, all tool settings and the pytest config. There are no `requirements*.txt` files.
- **Fixtures live in `src/` as a pytest plugin, not in a large `conftest.py`.** They are then typed, linted under the strict rules and unit-tested like the rest of the code.
- **Environment tests and unit tests are separate top-level directories.** `testpaths = ["unit_tests"]`, so a plain `pytest` never touches an environment by accident. Environment tests run through `podiumd-tests run`, which passes the right paths, profile and markers.

**Why the `kubectl` CLI and not the `kubernetes` Python client:**

1. **Reuse.** All four source suites already use `kubectl` (`kubectl get -o json`, `kubectl exec … manage.py shell`, `kubectl cp`). Their helpers and Django snippets port directly.
2. **Same behaviour as the user's console.** `kubectl` handles every kubeconfig auth method used here: AKS with Entra ID through `kubelogin`, minikube certificates, and the `az aks get-credentials` contexts. "Works in my terminal" then means "works in the tests". When a check fails, the exact `kubectl` command it ran is logged, so it can be pasted and rerun.
3. **`exec` and `cp` are simple with the CLI.** The Python client's `stream()` WebSocket API for exec is awkward and has no `cp` at all, and those two are what bootstrap relies on most.
4. **Typing.** The `kubernetes` client has no usable type information, which clashes with basedpyright `strict`. `kubectl -o json` parsed into TypedDicts is checkable.
5. **kubectl is needed anyway,** on the console and in the pipelines. The Python client would add a large dependency without removing that need.

**The cost:** a process start per call (about 0.1–0.3 s), and parsing text and JSON output. That is acceptable for the call volume of preflight, bootstrap and the `cluster` tests. `kube.py` hides this behind a small typed wrapper (`get`, `exec_python`, `cp`, `rollout_status`), so switching to the client later would only touch that one module.

## 8a. Code quality checks

`run_python_checks` is a copy of `dimpact-samenwerking/helm-charts/charts/podiumd/bin/run_python_checks`, modified for this layout. It runs the same checks with the same settings, fastest first, and stops at the first failure:

1. `ruff check`
2. `shellcheck`
3. `ruff format --check`
4. `jscpd` (weak mode, `--min-lines 4 --min-tokens 35`, the same ignore pattern)
5. `pymarkdown` (`-d md013,md014`, `plugins.md024.siblings_only`)
6. `vulture` (with the generated TypedDict whitelist)
7. `bandit -c pyproject.toml`
8. `pylint src`, then `pylint tests unit_tests` with the same `TESTS_PYLINT_DISABLE` list
9. `basedpyright` (`typeCheckingMode = "strict"`, relaxed under the test directories)
10. `pytest` on `unit_tests`

**Copied from podiumd `bin/pyproject.toml` as-is:**

- `[tool.ruff]` with line-length 120, the full `select` list and the `ignore` list;
- `[tool.ruff.lint.isort]`, `flake8-bandit`, `[tool.ruff.format]`;
- `[tool.pylint.*]`, `[tool.isort]`, `[tool.bandit]`, `[tool.basedpyright]` (strict).

**Adapted to this layout:**

- The targets become `src`, `tests` and `unit_tests` instead of `lib`, the extensionless scripts and `tests`.
- The `"tests/**"` per-file-ignores and the relaxed basedpyright environment apply to both `tests` and `unit_tests`.
- The E402 script list and the vulture `ignore_names` are dropped. They name podiumd's own scripts, and the `src/` layout needs no `sys.path` patches.
- The podiumd-specific `lib.settings` lookup for pymarkdown is replaced by the same rule settings, written into the script.
- pymarkdown scans all `*.md` files in the repo.
- `[tool.pytest.ini_options]` is added (markers, `testpaths`).

The dev dependencies are podiumd's `bin/requirements.txt` list (ruff, pymarkdownlnt, pylint, vulture, isort, pytest, bandit, basedpyright, jscpd), declared as the `dev` extra. shellcheck is a system tool, needed only for `run_python_checks` itself.

## 8b. `doctor`: the preflight check

`podiumd-tests doctor --env <name>` answers one question: "Can a run against this environment work right now, and if not, why?" It is read-only, takes seconds and runs no tests. The name follows `brew doctor` and `flutter doctor`; `preflight` would also do.

It checks, in order, and stops a branch at the first failure:

| Check | Example failure and hint |
|---|---|
| Local tools: `kubectl`, `helm`, `az` (if the profile uses Key Vault), the Playwright browser | `kubectl not found on PATH` |
| Profile: it exists, its schema is valid, URLs are well-formed, `allowed_tiers` is set | `envs/externals/ontw-icat.yaml: missing urls.openzaak` |
| Kube context: it exists, the API server is reachable, credentials are valid | `context podiumd-kees00-aks: API unreachable. Cluster stopped? (scheduled shutdown)` |
| Namespace(s) exist, and the expected deployments are Ready | `namespace podiumd: deployment openzaak 0/1 ready` |
| URLs: DNS, TLS and HTTP per component in the profile | `https://ita.kees00.pd.test-rig.nl: TLS certificate expired` |
| Secrets: every secret in the profile resolves (values are never printed) | `secret ok2_token: not in env, cluster or Key Vault podiumd-kees00-kv` |
| Capabilities: what was detected, for information | `oab: absent → 14 tests will skip` |
| Bootstrap state, for tiers beyond smoke | `ptest-* credentials missing → run podiumd-tests bootstrap --env kees00` |
| Lock: no other run holds the environment lock | `locked by run 20261005-1402_kees00_full_9f3e1a (pipeline)` |

The output is a checklist in the terminal, plus `doctor.json` for pipelines. Exit code 0 means everything is OK. Exit code 2 means at least one blocking check failed. The pipelines' first step is `podiumd-tests doctor`, so a stopped cluster or an expired secret shows up as one clear error instead of hundreds of failing tests.

## 9. Decisions (2026-10-05)

| Question | Decision |
|---|---|
| Target environments | minikube; podiumd-infra AKS environments; ExternalsPodiumD gemeente environments |
| Where it runs | Console first, with kubectl and URLs for the environment. A pipeline comes later. Cluster access is allowed. |
| Bootstrap location | In this repo, not in the podiumd helm charts and not spread over other projects |
| Perf | In scope (TA tier `perf`). The k6 scripts are ported to Python Locust (§6) |
| Toolset | Minimal; reuse existing code and libraries first (R22) |
| Code checks | podiumd `bin/run_python_checks`, copied and adapted to this layout, with the same tool settings (§8a). It is not kept in sync with upstream. |
| Layout | `src/` package laid out for this project; it does not follow podiumd `bin/` (§8) |
| Results | `results/<YYYY-MM>/<timestamp>_<env>_<tier>_<runid>/` in this repo; may move elsewhere later (§7) |
| Language | Code, identifiers, comments and docs in English, keeping Dutch domain terms (zaak, zaaktype, partij). Everything users see stays Dutch: UI labels the tests assert on, and the test data texts. Test names and `summary.md` are in English. |
| ExternalsPodiumD tier mapping | Not decided yet. Default `allowed_tiers: [smoke]` |
| Session output | Kept in this directory (`PLAN.md`, `docs/`) |
| Sources | TA, MK, PI and EX (header table) |
| Tiers | `smoke`, `core`, `full`, `perf`, `chaos`. TA "maintenance" becomes CLI commands (§3) |
| ExternalsPodiumD scope | Mixed: some environments are smoke-only, many run the full set. Set per profile with `allowed_tiers` (R20) |
| Repo hosting | A GitHub project under `infonl` |
| Pipelines | Later: GitHub Actions in podiumd-infra, likely Azure DevOps for SSC Twente. The implementation is open, so the code is kept pipeline-neutral (§7a) |

## 10. Migration phases

Status 2026-10-06: phase 0 is built, and `doctor` is green on minikube. kees00 is shut down; `doctor` reports that within about 6 s. Phase 1 is built: tier `smoke` runs in under 10 s on minikube and on ontw-dimp (HTTP only: no cluster access from here, so the cluster tests skip). Browser logins and checks that need seeded data or test identities are deferred to phases 2, 3 and 5; see `MIGRATION.md`. Phase 2a (A1, test-only bootstrap) is built: `bootstrap`/`unbootstrap` with an Open Zaak client and test catalogus, an Open Notificaties client, Open Klant and Objecttypen tokens and five Keycloak test users; a minikube round trip leaves nothing behind, and smoke-only profiles are refused. Phase 2b (A2) covers kanalen, the test zaaktype, the Open Formulieren form and client rights, Open Klant notifications and actor, and Open Archiefbeheer users; Open Inwoner and ITA/KISS wiring wait for podiumd-minikube (`docs/handoff/podiumd-minikube.md`, not committed). Phase 3 is built: 121 component tests (Open Klant, Open Zaak, Open Notificaties, Keycloak, PABC, KISS, platform checks) pass in parallel on minikube and leave nothing behind; 4 strict xfails record product defects. BRP and KvK tests wait for their ingress (handoff section 6). Phase 4 has started (2026-10-07): the webhook receiver of `infra/` and the chains Open Zaak → Open Notificaties → subscriber (TA 19, 53b/d), Open Formulieren submission → Open Zaak zaak (TA 76), klantcontact ↔ zaak (TA 18) and klacht → bezwaar (TA 63) pass on minikube. The productaanvraag chain (Objecten → Open Notificaties → ZAC → Open Zaak) and the Mailpit test pass too; a smoke test checks that minikube and QA send mail only to SMTP servers inside the cluster. podiumd-tests reaches https URLs through Traefik with the cluster's CA bundle (`access.ca_bundle`). Phase 5 has started (2026-10-07): browser logins to ZAC, PABC (management API), KISS and ITA as the KCC user, and Open Inwoner DigiD/eHerkenning through Keycloak's mock (wiring W1); ITA internetaken (claim, answer, forward) and BRP/KvK through the api-proxy are ported. Since then: Open Archiefbeheer vernietigingslijsten (role users, own zaken only), Open Formulieren with DigiD (TA 183), the OMC chain (strict xfail: OMC 1.17.19 rejects Open Notificaties' `source`; OMC is off on minikube), and the Open Inwoner portal on wiring W4 (API group), W5 (CMS pages) and W6/W8 (Open Klant 2 and the contact flow): anonymous pages, profile, Mijn zaken for DigiD and eHerkenning, documents, Mijn vragen. minikube's edge is NGINX Gateway Fabric. After minikube's full rebuild (2026-10-08), bootstrap from an empty cluster and tier full pass: 233 passed, 4 strict xfails. Since then: document upload and questions from a zaak (TA 111, 162, 164; bootstrap `openinwoner-zaaktype-config` configures only the test zaaktype) and Mijn zaken on a phone (TA 61). Then: the refusal of an infected upload (TA 123) on podiumd-minikube's opt-in ClamAV through wiring `openinwoner-virus-scan`, and Open Archiefbeheer's destruction and short procedure (TA 170, 171; tier chaos, the destruction a strict xfail on Open Zaak 1.29.3's 500 on the zaak DELETE). KvK searches run against KvK's test API through the api-proxy on every estate (podiumd-minikube routes there too since 2026-10-08), and a strict xfail pins that KISS cannot read ITA's logboek (reference configuration). Tier full on minikube (2026-10-08): 247 passed, 5 strict xfails. Phases 4 and 5 are not done: 56 source tests in `MIGRATION.md` are still todo.

| Phase | Deliverable | Sources | Done when |
|---|---|---|---|
| 0. Skeleton | `pyproject.toml`, `run_python_checks`, CLI, profiles and the secrets chain, `kube`/`http`/`auth`/`wait`, resource registry, capabilities, results writer, `doctor`, `env init`, `MIGRATION.md` triage list | MK/PI conftest helpers; EX `lib/urls.ts` and `generate-env.sh` logic | `run_python_checks` passes; `doctor` is green on minikube, one podiumd-infra environment and one ExternalsPodiumD environment |
| 1. Smoke | Smoke health matrix driven by capabilities; tier `smoke` | MK/PI `test_pods`, `test_reachability`, `test_metrics`, `test_monitoring_logging`; TA/EX smoke 00, 01, 04, 05, 06, 66, 72, 79, 81, 82, 92, 99, 113, 155, 192 | smoke passes or skips with a reason on the three estates, in under 2 min; the results land in `results/` |
| 2. Bootstrap | `bootstrap`/`unbootstrap`/`sweep`, Django snippets, `infra/` chart, `bootstrap_ok`, `allowed_tiers` enforcement | TA `seed-omgeving.sh` and its sub-scripts; EX `seed-identities.sh`; MK Jobs and SQL | bootstrap → unbootstrap leaves no `ptest-*` behind; a smoke-only profile refuses bootstrap |
| 3. Component | Factories plus cleanup; OZ (largest), OK2, ON, PABC, Keycloak config | TA interaction and regression; MK/PI `test_pkce`, `test_django_admin_login`, `test_database`, `test_zac_zaakafhandelparameters`, `test_4_8_5_upgrade` | runs under `-n auto`; a second run leaves no data behind; `core` markers are set |
| 4. Integration | Chains across components | MK/PI productaanvraag, mailpit, zgw-service reachability; TA notifications, OF→OZ, ITA, OMC, R193 | each chain is self-contained and cleans up; tier `full` runs end to end on one environment |
| 5. UI | Portaal DigiD/eHerkenning, KISS, ZAC, OI uploads, OAB, eSuite | TA UI specs; MK/PI `test_browser` | traces on failure; Dutch labels asserted through role or regex |
| 6. Perf | Locust ports, `seed-volume`/`unseed-volume`, thresholds in `perf.yaml`, tier `perf` | TA `tests/perf`, `seed-test-data` | p95 and error-rate results in `results/…/perf/` and `run.json` |
| 7. Pipelines | Pipeline definitions once the platform is chosen: GitHub Actions in podiumd-infra, likely Azure DevOps for SSC Twente | TA workflows; ExternalsPodiumD pipelines | a pipeline runs `doctor` plus a tier non-interactively, and its exit codes and JUnit show in the pipeline |
| 8. Decommission | Coverage report against the draaiboek, duplicates removed, old suites frozen | TA `test-catalog/` | every source test in `MIGRATION.md` is marked port, merge or drop; the old suites are read-only |

Porting rule: triage each source test as **port**, **merge** (into a parametrized test) or **drop** (dead, Hetzner/KIND, duplicate). Record each decision in `MIGRATION.md`. The four sources overlap a lot: the smoke specs exist three times, and the MK tests twice.

## 11. Risks

- Published zaaktypen and audit trails cannot be deleted. Session scope plus the sweeper limits the buildup.
- The ITA, OAB and PABC cookie OIDC flows need a browser to get a session. Handle this with the shared `browser_session` fixture.
- For each SSC Twente environment, its owner must confirm which tiers it may run. That is recorded as `allowed_tiers` in the profile. The default for a new profile is `[smoke]`.
- Committing results to this repository makes it grow over time. Mitigate with `results prune`, by committing text only, and by moving the results out later through `ResultsSink`.
- A and B use different Azure tenants, so Key Vault access needs the right `az` login per environment. In-cluster lookup is preferred.
- Clusters get shut down on a schedule; `doctor` detects it.
- Snippets for the Django shell break when models change. Keep them minimal, and cover them in compat.

## 11a. Committed secrets, and what they mean for these tests

**What was found** (2026-10-05, key names checked, values not read). Both repos are private.

| Where | What | Severity |
|---|---|---|
| podiumd-infra `values/<env>/podiumd.yaml` | Real service credentials of the QA environments: tokenauth tokens, ZGW JWT secrets | high for those environments |
| podiumd-infra `cyso/emk-sa-kubeconfig.yaml` | Service-account `token` plus `server`, which gives cluster API access if the Cyso cluster still exists | high |
| podiumd-infra `Notify/notify-secrets-*.yaml`, `NotifyEnvsSensitive.md` | `OMC_AUTH_JWT_SECRET`, `KTO_AUTH_JWT_SECRET` … | medium: could send mail or SMS through OMC |
| podiumd-infra `credentials.properties` | `zaken-api.jwt` username and password | medium |
| podiumd-infra `ispn.pfx` | Infinispan keystore, which may hold a private key | medium |
| podiumd-infra `server-cert-1.pem` | Public certificate only (Centric, no private key) | none |
| ExternalsPodiumD `smoke-tests/env-templates/*.env` | Passwords of the test identities (DigiD/eHerkenning mock, KCC, testadmin) | low to medium |
| Local clone `ExternalsPodiumD/.git/config` | An Azure DevOps **PAT embedded in the `origin` URL**. It is not committed, but it is in plain text on disk, and it showed up in this session's tool output. | high: rotate it |

**What it means for this suite:**

- **Seeded test data is not the risk.** The data is synthetic, run-tagged and deleted after each test, so leaking it does little harm.
- **The leaked credentials are the risk.** They are the environments' own service credentials, not test data. Anyone with read access to those repos can use them to read, change or delete *all* data in those environments, including other teams' test data and any seeded BSN data. They can also act as ZAC or OF towards Open Zaak, and send notifications through OMC. Self-cleaning tests do not reduce that risk.
- **It does affect how far the results can be trusted.** On an environment whose credentials are public, an unexpected change can come from someone else. Run tags (R9) and asserting only on our own objects contain this.
- **The rules that follow for this suite:**
  1. Never read secrets from those repos. Resolve them in the cluster, from Key Vault, or from environment variables (R8).
  2. Bootstrap creates **separate `ptest-*` credentials** per environment, with random values. They are stored only in a k8s Secret `podiumd-tests-credentials` in the target namespace, and rotated by `bootstrap --rotate`. `unbootstrap` revokes them. If the tests leak, the blast radius is limited to our own credentials, and they can be revoked without touching the platform credentials.
  3. Give the test credentials the minimum scope: test catalogus, test zaaktypen, `ptest` kanalen. Do not grant `heeft_alle_autorisaties` unless a test truly needs it.
  4. The test identities (Keycloak or OI users) are created by bootstrap with random passwords, not taken from committed `.env` templates.
  5. Results redact headers and tokens (§7), and a unit test guards the redaction. ruff `S105`/`S106` and bandit flag hardcoded passwords in code. A dedicated secret scanner such as gitleaks is not added (R22); reconsider it when the pipelines come.

**Recommended outside this project:** report these findings to the owners of podiumd-infra (ICATT) and ExternalsPodiumD (SSC Twente).

- Rotate the found credentials.
- Remove them from git, and from git history.
- Revoke the Cyso SA token.
- Replace the PAT in your local remote URL with a credential helper (`git remote set-url origin https://dev.azure.com/...` plus Git Credential Manager).

## 12. Open questions

1. Which ExternalsPodiumD environments are smoke-only and which run the full set? Not known yet. Until it is decided, every new profile defaults to `allowed_tiers: [smoke]`.

## 13. Open work

Updated 2026-10-08. The detail lives where it is kept up to date: blocked ports as `todo` rows in `MIGRATION.md` (`grep '| todo |' MIGRATION.md`), product bugs as strict xfails whose reason names the bug (a fix makes the test fail, so it gets noticed).

**Blocked ports (waiting for an environment):**

| Tests | Waits for |
|---|---|
| TA 80, 81, 82, 115, 116, the OMC part of 154; MK `test_omc.py` (`/Events/Version` with a JWT) | an OMC that handles Open Notificaties' notifications (1.17.19 answers 206 to each); then turn it on in minikube |
| TA smoke 155, regression 156 | a profile with an `esuite` URL and credentials (eSuite is outside PodiumD) |
| TA `perf/fg-compare.js` | an environment with both a Frank!Gateway route and a direct route to Open Zaak |

**Findings to report upstream** (each a strict xfail; reasons say "not yet reported upstream"):

| Product | Finding | Test |
|---|---|---|
| Open Zaak 1.29.3 | DELETE of a zaak with a resultaat answers 500 although it deletes it | `test_closed_zaak_delete_answers_204` |
| Open Zaak 1.29.3 | `_zoek` ignores an unknown filter and returns all zaken | `test_zoek_refuses_an_unknown_filter` |
| Open Zaak 1.29.3 | audittrails need `heeft_alle_autorisaties` | `test_document_audittrail_with_catalogus_rights` |
| Open Archiefbeheer | a destruction never finishes because of the Open Zaak 500 | `test_destruction_deletes_the_zaak_and_leaves_a_report` |
| Open Archiefbeheer 2.0.0 | `process_review_response` is queued inside the request's transaction (no `on_commit`): a quick worker finds no ReviewResponse and the list stays `changes_requested` | non-strict xfail `RESPONSE_RACE` on four review-response tests |
| Open Archiefbeheer 2.0.0 | the reviewer, while the list is assigned to it, can rename the list | `test_only_the_record_manager_changes_the_list[reviewer]` |
| Open Archiefbeheer 2.0.0 | a review response cannot empty the archiefactiedatum, so "keep forever" cannot be taken over | `test_keeping_forever_empties_the_archiefactiedatum` |
| Open Notificaties | an unreachable callback URL answers 500 instead of 400 | `test_abonnement_with_an_unreachable_callback_is_refused` |
| Open Inwoner | `deactivated_on` does not stop a DigiD login | `test_disabled_account_cannot_log_in[deactivated]` |
| Open Inwoner 2.4.3 | with `fetch_eherkenning_zaken_with_openzaak_120_params` Mijn zaken lists a company's zaak by `nietNatuurlijkPersoon.vestigingsNummer`, but its detail accepts only a `vestiging` rol and answers 404 | `WHO` in `test_portaal_zaken.py` (zaak status, infected upload) |
| Open Formulieren 3.5.5 | an anonymous submission of a form without name fields registers an initiator rol without `betrokkeneIdentificatie`, which Open Zaak 1.29.3 refuses (400): the zaak and PDF exist, the registration fails; Open Formulieren's public status still reports success | `test_anonymous_submission_without_a_name_registers` |
| OMC 1.17.19 | 206 to every notification ('source' property), so no mail | `tests/integration/test_omc.py` |
| Open Inwoner | no "did you mean" on a search without hits, as the draaiboek asks (OI-097); only the autocomplete is fuzzy | `test_no_results_suggest_what_was_meant` |
| mozilla-django-oidc | an unconfigured admin login answers 500 (`ImproperlyConfigured`) instead of refusing | none: every estate configures it |

**Configuration finding for the estates:** KISS's Objecten token has no rights on Activiteitenlog, so KISS shows none of ITA's activities (`test_kiss_reads_itas_logboek`, the same in ExternalsPodiumD, podiumd-infra and minikube).

**Pipelines (§7a):**

- `.github/workflows/run.yml` has not run end to end: podiumd-infra adds the calling workflow with its Azure OIDC identity (and a self-hosted runner if the AKS API is private).
- SCC Twente: runs from a machine with access, with the container image; an Azure DevOps template only once pipeline rights exist.
- The container image is built locally; publishing it (e.g. to GHCR) when a pipeline needs it.

**Perf:** the trend check needs 3 earlier runs with the same users, duration and volume data per environment before it judges; minikube has them only for runs without volume data so far.

**Phase 8 (decommission):**

- Done: every source test has a decision in MIGRATION.md, and `docs/draaiboek-coverage.md` (`python -m podiumd_tests.draaiboek`) maps the draaiboek's 546 cases, through TA's specs and the tests' own `@pytest.mark.tc` markers (R15): of 417 automatable (A) cases, 317 covered, 4 blocked, none dropped; every case TA covered is covered here.
- Backlog beyond the migration: 96 A and 33 B cases have no test. Most are in Formulier, ABC, ZAC (zaak handling in its UI) and Continuïteit (user-facing messages during an outage, DigiD/eHerkenning down). The Portaal cases left cannot be tested on PodiumD: eSuite (OI-022, 024, 030, 032, 047, 049, 067) and its `openstaande-inzendingen` endpoint (OI-052, 053), DigiD machtigen, which Open Inwoner 2.4.3 does not support (OI-016, 070), notifying through the source system, which needs OMC (OI-043, 044), and OI-100 (no case). The Formulier cases left: payments need an Ogone/Worldline test account (OF-021–030, 054–063); OF-066 and OF-069 do not say what to check; OF-072 is eSuite, OF-074 a gemeente's TSA.
- podiumd-minikube: done (its commit 514e6bd). Its tests now cover only its own code (memory, OpenBao, ClamAV, Elasticsearch, edge, realm sync, HTTPRoutes, its outway routes); its application checks moved here, and its post-deploy check is `podiumd-tests run --env minikube --tier smoke`.
- Freezing TA (icatt podiumd-testautomation), PI (podiumd-infra `tests/`) and EX (ExternalsPodiumD smoke tests) is for their owners; draft notices are in `docs/handoff/notices/` (not in git).
