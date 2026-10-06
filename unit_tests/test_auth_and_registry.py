"""Unit tests for ZGW tokens and the cleanup registry."""

import base64
import hashlib
import hmac
import json

import pytest

from podiumd_tests.auth.zgw_jwt import zgw_jwt
from podiumd_tests.seed.registry import CleanupError
from podiumd_tests.seed.registry import ResourceRegistry


def b64decode(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_zgw_jwt_is_a_valid_hs256_token():
    token = zgw_jwt("zac", "secret", issued_at=1700000000)
    header, payload, signature = token.split(".")
    expected = hmac.new(b"secret", f"{header}.{payload}".encode(), hashlib.sha256).digest()
    assert b64decode(signature) == expected
    assert json.loads(b64decode(header))["alg"] == "HS256"
    assert json.loads(b64decode(payload)) == {
        "iss": "zac",
        "iat": 1700000000,
        "client_id": "zac",
        "user_id": "zac",
        "user_representation": "zac",
    }


def test_registry_deletes_in_reverse_order():
    deleted = []
    registry = ResourceRegistry("ptest-abc123")
    registry.add("zaaktype", lambda: deleted.append("zaaktype"))
    registry.add("zaak", lambda: deleted.append("zaak"))
    assert registry.cleanup() == []
    assert deleted == ["zaak", "zaaktype"]
    assert len(registry) == 0


def test_registry_runs_every_deleter_and_reports_failures():
    deleted = []

    def boom():
        msg = "404"
        raise RuntimeError(msg)

    registry = ResourceRegistry("ptest-abc123")
    registry.add("first", lambda: deleted.append("first"))
    registry.add("broken", boom)
    with pytest.raises(CleanupError, match="broken: RuntimeError: 404"):
        registry.cleanup()
    assert deleted == ["first"]


def test_keep_data_skips_cleanup():
    registry = ResourceRegistry("ptest-abc123", keep=True)
    registry.add("zaak ZAAK-1", lambda: pytest.fail("must not delete"))
    assert registry.cleanup() == ["zaak ZAAK-1"]
    assert registry.tagged("catalogus") == "ptest-abc123-catalogus"
