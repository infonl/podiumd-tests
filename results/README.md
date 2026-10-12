# results

This directory holds test-run results, one subdirectory per run. See PLAN.md §7 for the reasoning.

```text
results/<YYYY-MM>/<YYYYMMDD-HHMMSS>_<env>_<tier>_<runid>/
  run.json      # environment, chart version, component image tags, capabilities, suite SHA, counts
  junit.xml
  summary.md
  perf/         # perf tier only
  artifacts/    # traces and screenshots on failure; never committed
```

`podiumd-tests` writes these files through a `ResultsSink`. The local directory sink is the only one for now, so the results can move to another repository or a static site later without code changes.

Run directories are in `.gitignore`: this repository is public. Commit a chosen run on purpose with `git add -f results/<YYYY-MM>/<run>`, for example a release baseline.

Never commit credentials. The suite redacts tokens and auth headers before it writes anything here.
