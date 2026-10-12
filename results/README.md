# results

This directory holds test-run results, one subdirectory per run. See PLAN.md §7 for the reasoning.

```text
results/<YYYY-MM>/<YYYYMMDD-HHMMSS>_<env>_<tier>_<runid>/
  run.json      # environment, chart version, component versions, capabilities, suite commit, counts
  junit.xml     # every test with its outcome and message (JUnit XML)
  summary.md    # counts, failures, known defects and skip reasons
  report.html   # every test with outcome, duration, message and log (pytest-html); not committed
  perf/         # perf tier only
  artifacts/    # a screenshot of each failed browser test; never committed
```

## Reading the results

Start with `summary.md` (its counts match pytest's last line), or open `report.html` in a browser to filter and read every test.

| Outcome | Meaning | Action |
|---|---|---|
| Passed | The check holds. | None. |
| Failed | The check does not hold: a product defect, a configuration error or a test that is out of date. | Read the message in `summary.md`; the trace and screenshot of a browser test are in `artifacts/`. |
| Errors | The test could not run: a fixture or setup failed. | As Failed. |
| Skipped | The environment lacks what the test needs, e.g. "requires: omc (no URL in profile)" or a missing bootstrap step. | None, unless the environment should have it. |
| XFailed | A known product defect showed again; the reason names it. | None; report it upstream if not done. |
| XPassed | A known defect did not show this time. | A strict xfail that passes counts as Failed: the defect is fixed, so update the test. A non-strict one is a race that sometimes passes. |

How to view a run:

- `report.html`: a browser; one self-contained file with a filter per outcome and each test's message and log.
- `summary.md`: any Markdown viewer, e.g. GitHub, an IDE or `less`; a pipeline publishes it on the job page.
- `junit.xml`: an IDE's test viewer (PyCharm: Run > Import Tests from File) or a CI test report.
- `artifacts/<test>/`: the screenshot of a failed browser test. There are no Playwright traces: they record what a test types, test passwords included.
- `run.json`: the run's facts as JSON, for comparing runs.

`podiumd-tests` writes these files through a `ResultsSink`. The local directory sink is the only one for now, so the results can move to another repository or a static site later without code changes.

Run directories are in `.gitignore`: this repository is public. Commit a chosen run on purpose with `git add -f results/<YYYY-MM>/<run>`, for example a release baseline.

Never commit credentials. The suite redacts tokens and auth headers before it writes anything here.
