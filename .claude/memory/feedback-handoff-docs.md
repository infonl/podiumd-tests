---
name: feedback-handoff-docs
description: Handoff notes for agents of other local repos are not committed in podiumd-tests
metadata:
  type: feedback
---

# Handoff docs for other repositories

Instructions for the AI agent of another repo on this machine (e.g. podiumd-minikube) go in `docs/handoff/` as plain files and are not committed; `docs/handoff/` is in `.git/info/exclude`.

**Why:** the user said "no need to commit this, the minikube project is on the same machine" (2026-10-07); the other agent reads the file directly.

**How to apply:** write handoff files to `docs/handoff/<repo>.md`, give the user the absolute path, never `git add` them. Related: [[feedback-commits]].
