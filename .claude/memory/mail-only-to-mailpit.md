# Mail only where Mailpit catches it

A test that makes an application send mail runs only where all mail goes to Mailpit, i.e. where the environment has
the capability `mailpit` (minikube, kees00/QA) (user, 2026-11-11: "otherwise they will really be send into the wide
world").

**Why:** on an environment with a real SMTP server, a test's mail would leave the platform.

**How to apply:**

- The test or its module has `@pytest.mark.requires(..., "mailpit")` whenever its action sends mail (ZAC mail and
  taken, ITA forward and reminder, Open Formulieren confirmations, ...), not only when it reads the mail.
- Every address a test gives a person, afdeling, groep or mail field is `@example.invalid` (RFC 2606: never
  delivered), via `mailpit.own_address`, `ita.mailbox` or `user_email`; never `example.com` or a real domain.
- Running a mailing job once (a CronJob that is off on an environment) is done only where Mailpit catches the mail.

Related: [[reuse-existing-logic]].
