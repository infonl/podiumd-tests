---
name: feedback-commits
description: "In podiumd-tests, commit without asking, as functionally atomic commits"
metadata:
  type: feedback
---

# Commits

In podiumd-tests the user allows commits without asking (2026-10-06): "do create functionally atomic commits whenever possible".

**Why:** the user wants a reviewable history, one functional change per commit, not one big dump per phase.

**How to apply:** commit after each functional unit (a fix, a feature, a test group, a doc update) with `run_python_checks` green. Keep unrelated fixes in their own commit. Do not push unless asked. Related: [[podiumd-tests-project]].
