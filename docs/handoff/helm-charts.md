# Open requests for helm-charts

## Unit test coverage in charts/podiumd/bin/run_python_checks

podiumd-tests measures unit test coverage and fails `run_python_checks` below a threshold.
Add the same to `charts/podiumd/bin/`:

- `requirements.txt`: `pytest-cov`.
- `pyproject.toml`:

  ```toml
  [tool.coverage.run]
  source = ["."]
  omit = ["tests/*"]

  [tool.coverage.report]
  fail_under = 97
  ```

  `source = ["."]` also measures the extension-less scripts, which the tests load with `SourceFileLoader`.
- `run_python_checks`: `step "pytest (with coverage)" python3 -m pytest -q --cov --cov-report=term-missing:skip-covered`
  (the threshold stays in `pyproject.toml`); add `.coverage` to `.gitignore`.
- Measured 2026-10-19 on a pr-569 working tree with local changes: 98% (13680 statements, 340 missed;
  2798 passed, 3 failed). Lowest: `lib/component_docs/doc_updates.py` 60%, `lib/checks/dead_values.py` 89%.
