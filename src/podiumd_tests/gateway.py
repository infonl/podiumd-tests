"""Frank!Gateway (APISIX) responses."""

from __future__ import annotations

import re

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

if TYPE_CHECKING:
    import requests


def is_no_route(response: requests.Response) -> bool:
    """True for APISIX's own 404 about a missing route: the request reached no upstream.

    A 404 from the upstream itself (e.g. an unknown KVK number) is not "no route".
    """
    if response.status_code != HTTPStatus.NOT_FOUND:
        return False
    try:
        body: object = response.json()
    except ValueError:
        return False
    message = cast("dict[str, object]", body).get("error_msg") if isinstance(body, dict) else None
    return isinstance(message, str) and re.search("route", message, re.IGNORECASE) is not None
