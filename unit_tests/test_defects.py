"""Unit tests for the known-defect symptom."""

import pytest

from podiumd_tests.defects import DefectSymptomError
from podiumd_tests.defects import symptom
from podiumd_tests.wait import WaitTimeoutError


def _fail(error: Exception) -> None:
    with symptom():
        raise error


def test_a_failed_check_in_the_block_is_the_symptom():
    with pytest.raises(DefectSymptomError, match="stays nog_niet"):
        _fail(WaitTimeoutError("stays nog_niet"))


def test_other_errors_pass_through():
    with pytest.raises(KeyError):
        _fail(KeyError("url"))


def test_a_passing_block_raises_nothing():
    with symptom():
        checked = True
    assert checked
