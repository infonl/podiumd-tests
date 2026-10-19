# Open requests for podiumd-minikube

## Unit test coverage in run_python_checks

podiumd-tests measures unit test coverage and fails `run_python_checks` below a threshold.
Add the same to podiumd-minikube:

- `pyproject.toml`: `pytest-cov` in the `dev` extra, and

  ```toml
  [tool.coverage.run]
  source = ["src/podiumd_minikube"]

  [tool.coverage.report]
  fail_under = 85
  ```

- `run_python_checks`: `step "pytest (unit_tests, with coverage)" python3 -m pytest -q --cov --cov-report=term-missing:skip-covered`
  (the threshold stays in `pyproject.toml`); add `.coverage` to `.gitignore`.
- Add unit tests until the threshold passes. Measured 2026-10-19: 63% (2237 statements, 829 missed, 128 tests).
