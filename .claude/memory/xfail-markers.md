# xfail markers and XPASS

Rules for marking a test as a known defect (user, 2026-10-26).

**Why:** an xfail hides a failure; it is only allowed for a defect that is explained and registered, and must go once the defect is fixed.

**How to apply:**

## Who decides, where the id lives

- The user decides when a defect becomes a known issue; the agent applies these rules.
- Each id is registered in infonl/podiumd-known-issues: `issues/<component>-<n>-<slug>.md`, its `components/` file and a row in the README table. The id is the next free `<n>` for that component there.
- A fault in podiumd-minikube's configuration is fixed there, never registered or marked xfail.

## Adding

- Only a reproduced defect with an id and a write-up gets an xfail; never "flaky, unexplained". An unexplained failure is investigated (logs, rerun with `--runxfail`) first.
- `strict=True` (the default) for a defect that fails every run.
- `strict=False` only for a proven intermittent defect, with the measured frequency in a comment ("1 in 31 runs"), or for a defect an environment can hide (an edge that adds the header, an estate setting), with a comment naming it.
- Reason: `[id] fact, versions or conditions, upstream ticket` in one line, e.g. `[zac-2] ZAC 5.4.5 and 5.9.1 answer 500 to a zaak without startdatum (...); PZ-13090`. No ticket yet: "not yet reported upstream".
- When the fixed component version is known, the xfail applies only below it (`expect_ita_group_access_bug`).
- Add the marker in the same change as the write-up, and name the id in the commit message.

## XPASS

- A strict xfail that passes fails the run: the defect no longer shows.
- Verify the fix: rerun the test with `--runxfail` on the build that shows it, and name the change that fixed it: the PR and the published version that contains it, or the environment setting.
- Remove the marker, or set its fix version, only once the fix is in a published chart or component version: minikube runs unreleased fixes from local verify branches, and other environments (kees00, ExternalsPodiumD) still fail without the marker.
- Until then, an XPASS of a strict xfail on a build with the unreleased fix is accepted; record the run in podiumd-known-issues.
- Remove the marker in the same change that records the fix in podiumd-known-issues (status and Fix column, build and run id).
- An XPASS of a non-strict xfail is expected and needs no action by itself.

## Removing a non-strict xfail

- Once the fix is deployed: remove it after no failure under `--runxfail` in as many runs as the measured interval (1 in 31 runs: 31 runs) on builds with the fix.
- For an environment-dependent one: remove it once every environment the suite runs on has the fix.

Related: [[comments-and-help-texts]], [[feedback-commits]], [[coordination-podiumd-minikube]].
