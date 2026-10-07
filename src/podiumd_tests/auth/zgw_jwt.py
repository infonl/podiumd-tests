"""ZGW API tokens: HS256 JWTs signed with the client's shared secret.

Ported from podiumd-minikube tests/test_productaanvraag_flow.py (_zgw_jwt).
Stdlib only: no JWT library dependency (PLAN.md R22).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


# Every ZGW API request carries these; the CRS headers are mandatory for the geo-aware APIs.
ZGW_HEADERS = {"Accept-Crs": "EPSG:4326", "Content-Crs": "EPSG:4326", "Accept": "application/json"}


def zgw_headers(token: str) -> dict[str, str]:
    """Request headers for a ZGW API call with a token from zgw_jwt()."""
    return {**ZGW_HEADERS, "Authorization": f"Bearer {token}"}


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
