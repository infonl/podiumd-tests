---
name: remove-unused
description: Remove unused code, test seeding, fixtures, settings and docs as soon as they turn out unused
metadata:
  type: feedback
---

# Remove what is unused

Anything that nothing uses is removed, not kept "just in case": code, test seeding (bootstrap steps, seeded objects such as prepared accounts), fixtures, helpers, profile settings, constants, comments and doc sections (user, 2026-10-07).

**Why:** the user said "dead code, or dead test seeding should be removed" after an Open Inwoner account that bootstrap prepared for eHerkenning turned out never to be used; unused seeding still costs setup time, cleanup and reading.

**How to apply:**

- When a check, test run or investigation shows something is never used, remove it in the same change and say so in the commit message.
- Test seeding counts too: seed only what a test needs and that the platform does not create itself; verify on a live environment when unsure (e.g. does the login use the prepared object, or create its own?).
- vulture covers code; for seeding, settings and docs, check by hand which test or step reads them.
- Copying a reference script (TA, ExternalsPodiumD) is no reason to keep a part that is unused here.

Related: [[reuse-existing-logic]], [[comments-and-help-texts]].
