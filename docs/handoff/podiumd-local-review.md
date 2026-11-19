# Handoff to podiumd-local-review

Open items for the podiumd-local-review session. Delete an item when it is done; delete the file when nothing is open.

## env-ledger: a stable interface for podiumd-tests (podiumd-tests, 2026-11-19)

podiumd-tests' CLI books the environment itself while it holds its lock (`bootstrap`, `unbootstrap`, `sweep`,
`seed-volume`, every tier except smoke; podiumd-tests f07babf, `src/podiumd_tests/lock.py`). It runs
`.claude/skills/env-ledger/env-ledger.py` as a subprocess and keeps no ledger logic of its own:

1. `book ENV --what "run full kees00" --for 60m --disruptive --agent podiumd-tests`, booking ID from the last
   stdout line; exit code not 0 means refused, stdout and stderr go into podiumd-tests' error message.
2. `start ENV ID --agent podiumd-tests`.
3. `heartbeat ENV ID --agent podiumd-tests` every 5 min, with `--extend 60m` when less than 30 min remain.
4. `done ENV ID --agent podiumd-tests` when the hold ends, also on SIGTERM.

ENV is the podiumd-tests profile name (`minikube`, `kees00`).

podiumd-tests uses `book` and then `start` instead of `book --start`, because `book --start` reports podiumd-tests'
own lock file and lease (taken just before) as `LOCK` lines and refuses. As a result the ledger does not check the
locks for these bookings; podiumd-tests' own lock code does.

Requests:

1. **Ignore the caller's own locks.** An option such as `book --start --holder-prefix "podiumd-tests kvv@chopin pid
   4242"` (or `--ignore-lock-holder TEXT`) that skips `LOCK` lines whose holder starts with TEXT. podiumd-tests
   would then make one `book --start` call, and the ledger would again report locks held by other agents.
2. **Machine-readable output.** `--json` on `book`, `start`, `heartbeat`, `done` and `check`: one JSON object on
   stdout, e.g. `{"booking": "kees00-1119-0900-ab12", "conflicts": [...], "shared": [...], "locks": [...]}`, and
   a documented exit code for "refused because of a conflict" that differs from other errors (kubectl unreachable,
   bad arguments). podiumd-tests now takes the last stdout line as the ID and treats every non-zero exit code as a
   conflict.
3. **Keep the command line stable**, or tell the podiumd-tests session before changing it: the verb order `VERB ENV [ID]`, `--agent`, `--for`, `--extend` and
   `--disruptive` are what podiumd-tests calls.

When 1 and 2 are released, podiumd-tests switches to `book --start --json` with the holder option and removes the
separate `start` call.
