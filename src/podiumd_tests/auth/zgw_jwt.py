"""ZGW API tokens: HS256 JWTs signed with the client's shared secret.

Ported from podiumd-minikube tests/test_productaanvraag_flow.py (_zgw_jwt);
stdlib only, so no JWT library is needed (PLAN.md R22).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def zgw_jwt(client_id: str, secret: str, *, issued_at: int | None = None) -> str:
    """HS256 ZGW token for a client id, signed with its shared secret."""
    header = {"typ": "JWT", "alg": "HS256", "client_identifier": client_id}
    payload = {
        "iss": client_id,
        "iat": int(time.time()) if issued_at is None else issued_at,
        "client_id": client_id,
        "user_id": client_id,
        "user_representation": client_id,
    }
    signing_input = _b64url(json.dumps(header).encode()) + b"." + _b64url(json.dumps(payload).encode())
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return (signing_input + b"." + _b64url(signature)).decode()
