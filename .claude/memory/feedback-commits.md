---
name: feedback-commits
description: "In podiumd-tests, commit without asking, as functionally atomic commits gated on run_python_checks, and push each"
metadata:
  type: feedback
---

# Commits

In podiumd-tests the user allows commits without asking (2026-10-06): "do create functionally atomic commits whenever possible", and wants each pushed (2026-10-08).

**Why:** the user wants a reviewable history, one functional change per commit, not one big dump per phase.

**How to apply:** commit after each functional unit (a fix, a feature, a test group, a doc update) with `run_python_checks` green. Keep unrelated fixes in their own commit. Push to `origin` after every commit (user, 2026-10-08: "you can now push upstream. do this whenever you commit"); never force-push. Related: [[podiumd-tests-project]].

## Gate the commit on the checks

Chain with `&&`: `./run_python_checks >log 2>&1 && git add … && git commit … && git push`; never
`checks; echo exit=$?; git commit`. Never `--no-verify`.

**Why:** with `;` red checks were committed and pushed twice (3ec1111 on 2026-10-19, 3551675 on 2026-10-20); each
needed a follow-up commit, and a push cannot be undone (no force-push).

**How to apply:** the pre-commit hook `.githooks/pre-commit` (`git config core.hooksPath .githooks`, shared by the
clone's worktrees) runs the checks on every commit; still chain with `&&`. An agent worktree needs its own `.venv`, or
the hook refuses.
