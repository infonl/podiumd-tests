---
name: feedback-handoff-docs
description: Handoff notes for other repos live in docs/handoff/ and are committed, so open work is visible
metadata:
  type: feedback
---

# Handoff docs for other repositories

Requests for the AI agent of another repo on this machine (e.g. podiumd-minikube) and drafts for other owners (`docs/handoff/notices/`) go in `docs/handoff/` and are committed.

**Why:** the user wants git to show which work is not done yet (2026-10-12); the other agent still reads the file directly.

**How to apply:** write handoff files to `docs/handoff/<repo>.md` with only open requests; commit each change; delete a file when nothing in it is open. Related: [[feedback-commits]], [[coordination-podiumd-minikube]].
