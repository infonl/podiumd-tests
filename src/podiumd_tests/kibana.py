"""KISS's Kibana (ECK): its status API, called from inside its pod."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section

if TYPE_CHECKING:
    from podiumd_tests.kube import Kube

# ECK names Kibana's Deployment <name>-kb and its Service <name>-kb-http; the podiumd chart's name is kiss.
KIBANA = "kiss-kb"
PORT = 5601


def kibana_status_level(kube: Kube, password: str) -> str | None:
    """status.overall.level of Kibana's /api/status as user elastic; None when there is no Kibana Service.

    ECK serves HTTPS with a self-signed certificate unless spec.http.tls disables it; the Service's port name
    tells which. The password goes to curl over stdin, never in argv.
    """
    service = kube.get_optional("service", f"{KIBANA}-http")
    if service is None:
        return None
    ports = entries(section(service, "spec").get("ports"))
    scheme = "https" if any(p.get("name") == "https" for p in ports) else "http"
    url = f"{scheme}://localhost:{PORT}/api/status"
    body = kube.run(
        "exec", "-i", f"deploy/{KIBANA}", "--", "curl", "-sSk", "-K", "-", url, stdin=f'user = "elastic:{password}"\n'
    )
    return str(section(section(json.loads(body), "status"), "overall").get("level"))
