"""Fixtures of the perf tier."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module", name="perf_dir")
def fixture_perf_dir(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The run's perf/ directory, or a temporary one outside a CLI run."""
    junit = request.config.option.xmlpath
    directory = Path(junit).parent / "perf" if junit else tmp_path_factory.mktemp("perf")
    directory.mkdir(parents=True, exist_ok=True)
    return directory
