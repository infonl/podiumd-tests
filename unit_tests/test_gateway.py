"""Unit tests for Frank!Gateway response checks."""

import pytest

from podiumd_tests.gateway import is_no_route


@pytest.mark.parametrize(
    ("status", "json_body", "body", "expected"),
    [
        (404, {"error_msg": "404 Route Not Found"}, b"", True),
        (404, {"error_msg": "kvk number unknown"}, b"", False),
        (404, None, b"<html>not found</html>", False),
        (404, ["route"], b"", False),
        (405, {"error_msg": "route"}, b"", False),
    ],
)
def test_is_no_route(response_factory, status, json_body, body, expected):
    assert is_no_route(response_factory(status=status, json_body=json_body, body=body)) is expected
