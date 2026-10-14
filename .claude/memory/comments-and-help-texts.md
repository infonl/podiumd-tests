---
name: comments-and-help-texts
description: "Comments, docstrings, help texts and messages in podiumd-tests are minimal and precise"
metadata:
  type: feedback
---

# Comments and help texts

Write comments, docstrings, `--help` texts, skip reasons and error messages minimal and precise.

**Why:** the user wants text that is cheap to read and stays true; long or vague text rots and hides the one fact that matters.

**How to apply:**

- Say only what the code cannot: the why, a constraint, a non-obvious fact ("TokenAuth.token allows 40 characters"). Never restate what the code does.
- One sentence where one sentence does; no history, no "now/new/changed", no references to this session.
- Docstrings: one line stating what it returns or does. Add a second paragraph only for a real constraint or edge case.
- Help texts: what the option does and its default, in under one line; no examples unless the syntax is unclear.
- Errors and skip reasons: the fact, the object and the fix in one line ("bootstrap missing on kees00 (openzaak-client): run `podiumd-tests bootstrap --env kees00`").
- Exact terms: name the real object, field, command or limit; no "some", "various", "etc.", hedges or filler.
- Same term for the same thing everywhere (one word, one meaning).
- Never reference PLAN.md outside the agent files (CLAUDE.md, `.claude/`): it is for the AI agent only, not for people (user, 2026-10-14). Docs, code, comments and profiles state the fact themselves.
- Before committing, reread each new comment and help text and cut every word that does not change the meaning.

Related: [[reuse-existing-logic]], [[feedback-commits]].
