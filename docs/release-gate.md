# Release gate

Before a PodiumD release goes to an estate (an environment that a customer or a hosting party runs), the release
gate answers two questions:

1. Does the estate have a setting that a known upgrade hazard needs? `estate-profile export` reads the estate's
   settings read-only into a profile; `estate-profile check` evaluates the known hazards on it.
2. Does the upgrade path work with those settings? The gate run installs the estate's current version on kees00,
   applies the profile's Keycloak settings there, upgrades to the candidate and judges the result.

`estate-profile report` runs export and check over many estates, so the hosting party learns before an upgrade what
each estate must do.

## Rules

- Never write to an estate. `export` and `report` only read; `apply` and `restore` refuse every environment outside
  the podiumd-infra and minikube estates, and smoke-only ones.
- Actions for an estate go to Kees, who passes them on. Nothing goes outside ourselves: no tickets, mails or comments
  to the estate's owner or hosting party.
- Estate profiles, their actions and estate environment profiles live only in the private repository
  podiumd-known-issues: one folder per environment, `estate-profiles/<env>/`, and the podiumd-tests profiles of the
  estates in `estate-envs/`. Never commit them to this repository.
- A gate run by hand books kees00 in the env ledger first (`settings.env_ledger` of the kees00 profile); the Release
  Gate workflow holds kees00 itself.

## Prerequisites

- podiumd-tests installed as in the [README](../README.md).
- A podiumd-tests profile for each environment: for kees00 `envs/podiumd-infra/kees00.yaml`; for an estate a
  smoke-only profile with `estate: externals` in `../podiumd-known-issues/estate-envs/`, passed with `--envs-dir`
  (draft one with `podiumd-tests env init`).
- A kubectl context per estate. Read-only access is enough: a read that RBAC forbids (Secrets, Keycloak resources,
  nodes, pod logs) becomes `unknown` with its reason.
- An AKS API server with authorized IP ranges answers only from those ranges: connect the VPN, then check with
  `ip route get <API server IP>` that the route goes through the VPN interface. When the VPN routes only some
  ranges, route every AKS API server of your subscriptions through it (as root; the routes go with the VPN):

  ```bash
  for s in $(az account list --query "[].id" -o tsv); do az aks list --subscription "$s" --query "[].fqdn" -o tsv; done \
      | while read -r f; do getent hosts "$f" | awk '{print $1}'; done | sort -u > /tmp/aks-ips
  sudo sh -c 'while read -r ip; do ip route replace "$ip/32" via <VPN gateway> dev <VPN interface>; done < /tmp/aks-ips'
  ```

- An estate in another Azure tenant: get its credentials into a separate kubeconfig and log in to that tenant.

  ```bash
  az login --tenant <tenant-id>
  az aks get-credentials --resource-group <group> --name <cluster> --file ~/.kube/<estate>.kubeconfig
  kubelogin convert-kubeconfig -l azurecli --tenant-id <tenant-id> --kubeconfig ~/.kube/<estate>.kubeconfig
  export KUBECONFIG=~/.kube/config:~/.kube/<estate>.kubeconfig
  ```

- Optional: the estate profile's `keycloak_admin_username` and `keycloak_admin_password` secrets. With them, export
  reads Keycloak's master realm; without them, it derives what the Keycloak log shows.

## Folder of an environment

`../podiumd-known-issues/estate-profiles/<env>/` holds:

| File | Written by | Read by |
| --- | --- | --- |
| `profile.yaml` | `estate-profile export` (or by hand) | `check`, `apply` |
| `actions.md` | `estate-profile check` | Kees |
| `infra.yaml` | by hand: the estate's deploy-step flags | the Release Gate workflow (settings layer over kees00's) |
| `podiumd-overlay.yaml` | by hand: the estate's chart values that differ from the defaults, without hosts or secrets | the Release Gate workflow (values layer over kees00's) |

`infra.yaml` sets every kees00-only workaround the estate does not run to `false` explicitly; a flag it leaves out
keeps kees00's value.

## Profile format

A profile is YAML without secrets, host names, URLs or user names. Every value can be `unknown`; its section's
`reasons` then says why. `reasons` also says where a value came from when it was not read directly (the Keycloak
log, the keycloak-operator's version).

| Section | Fields |
| --- | --- |
| `estate`, `env` | podiumd-tests estate and profile name |
| `exported_at` | time of the export, UTC |
| `source` | `kubectl`, `keycloak-admin` (master realm read through the admin API) or `manual` (written by hand) |
| `chart` | `podiumd`: chart version; `components`: chart name and version from the workloads' `helm.sh/chart` labels |
| `cluster` | `kubernetes` version, `nodes` count, `node_pools`, `cni` |
| `keycloak` | `version`, `replicas` of the operator's StatefulSet |
| `keycloak_master` | `direct_grant_otp`: `required`, `conditional`, `disabled`; `operator_client`: `present`, `absent`; `required_actions` of master's admin users (counts); `otp_policy` |
| `signals` | over `since`: `operator_client_not_found` (CLIENT_LOGIN_ERROR client_not_found of keycloak-operator), `otp_flow_errors` (AuthenticationFlowException in direct-grant-validate-otp), `keycloak_jobs_failed`, `keycloak_jobs_hanging` (running over 30 minutes) |

A hand-written profile needs `estate`, `source: manual` and the `keycloak_master` fields it knows.

## Exit codes

| Command | 0 | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- | --- |
| `export` | written | | profile or cluster error | | |
| `check` | no action | action needed or unknown | invalid profile or target | | |
| `report` | no action | action needed or unknown | an environment failed | | |
| `apply` | applied | | invalid profile, refused environment, state file exists, lock held | Keycloak admin access failed | |
| `restore` | restored | | refused environment, lock held | Keycloak admin access failed | state file missing, unreadable or of another environment |

## A. One estate: export and check

```bash
P=../podiumd-known-issues/estate-profiles/<env>
podiumd-tests --envs-dir ../podiumd-known-issues/estate-envs estate-profile export --env <env> --since 24h \
    --out $P/profile.yaml
podiumd-tests estate-profile check --profile $P/profile.yaml --target <candidate> > $P/actions.md
```

Export without `--out` prints the profile. `--since` sets the window of the log signals; take one that covers the
estate's last deploy.

## B. Many estates: the report for the hosting party

```bash
podiumd-tests --envs-dir ../podiumd-known-issues/estate-envs estate-profile report --estate externals \
    --target <candidate> --out ../podiumd-known-issues/estate-profiles
```

`--envs <env>,<env>` takes named profiles instead of every profile of an estate. The folder gets
`<env>/profile.yaml`, `<env>/actions.md` and `README.md` with one row per environment: chart version and the known
issues that need an action or a fact. An environment that cannot be read gets a row with the error; the others go
on.

## C. The gate on kees00: the Release Gate workflow

Run the workflow Release Gate of podiumd-infra with these inputs:

| Input | Value |
| --- | --- |
| `from-version` | the podiumd version the estate runs now (the profile's `chart.podiumd`) |
| `estate` | the environment whose folder it applies, `estate-profiles/<env>/` |
| `candidate` | the podiumd chart version to release |

The workflow holds kees00's Lease `podiumd-tests-lock` as `podiumd-infra <run URL> Release Gate <estate>` and sets
`PODIUMD_TESTS_HELD_BY` to that, so the podiumd-tests commands in it check that lease instead of taking their own.
It runs:

1. install `from-version` on kees00;
2. `podiumd-tests estate-profile apply --env kees00 --profile <profile> --state <state file>`;
3. upgrade to `candidate`;
4. the verdict: `podiumd-tests run --env kees00 --tier smoke --skip-doctor -- tests/smoke/test_cluster.py`;
5. `podiumd-tests estate-profile restore --env kees00 --state <state file>`;
6. bootstrap, doctor and the smoke tier: informative, they do not change the verdict.

## D. The gate on kees00 by hand

When the workflow is unavailable:

1. Book kees00 as disruptive in the env ledger.
2. Deploy podiumd `from-version` to kees00 as podiumd-infra does.
3. Apply the estate's settings; the command takes kees00's lock itself.

   ```bash
   podiumd-tests estate-profile apply --env kees00 --profile <profile> --state ~/gate-<estate>.json
   ```

4. Upgrade kees00 to `candidate` as podiumd-infra does, and wait until the deploy ends or times out.
5. Judge: exit 0 passes.

   ```bash
   podiumd-tests run --env kees00 --tier smoke --skip-doctor -- tests/smoke/test_cluster.py
   ```

6. Restore, also after a failed apply or upgrade:

   ```bash
   podiumd-tests estate-profile restore --env kees00 --state ~/gate-<estate>.json
   ```

7. Informative: `podiumd-tests bootstrap --env kees00`, `podiumd-tests doctor --env kees00`,
   `podiumd-tests run --env kees00 --tier smoke`.
8. Close the booking.

The state file holds client secrets of kees00; delete it when restore cannot run (restore deletes it on success).

## Reading the results

- `check` and `report`: per finding a status. `action needed`: send the action and the estate to Kees. `unknown`:
  the profile lacks a fact; get read access (Keycloak admin, pod logs) and export again, or ask Kees to ask the
  estate's owner. `ok`: nothing to do.
- The gate: the verdict's exit code, and on failure the Jobs and pods that `test_cluster.py` names. A failing gate
  on a profile whose check says `action needed` reproduces that hazard; the action is the way around it until a fixed
  chart version is released.
- Results of an estate go into its folder in podiumd-known-issues: the profile that passed the gate, `actions.md`,
  and the gate run's link in the commit message.

## Drift

To see whether an estate changed since its gate: export again and compare with the profile that passed.

```bash
podiumd-tests --envs-dir ../podiumd-known-issues/estate-envs estate-profile export --env <env> --out /tmp/<env>.yaml
diff ../podiumd-known-issues/estate-profiles/<env>/profile.yaml /tmp/<env>.yaml
```

`exported_at` and the signal counts always differ. A change in `chart`, `keycloak` or `keycloak_master` needs a new
check, and a new gate run when a hazard's input changed.
