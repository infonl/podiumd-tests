"""HTTP sessions that reach the profile's URLs, also in host-header mode.

In host-header mode (minikube), requests to a profile host go to the IP of
the ingress service, with the original host in the Host header. Tests and
clients keep using the real URLs, e.g. http://zac.local/.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import override
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import requests

from requests.adapters import HTTPAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_TIMEOUT = 15


class HostHeaderAdapter(HTTPAdapter):
    """Sends requests for the given hosts to one IP, keeping the host in the Host header."""

    def __init__(self, hosts: set[str], ip: str) -> None:
        super().__init__()
        self._hosts = hosts
        self._ip = ip

    @override
    def send(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # HTTPAdapter.send signature
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> requests.Response:
        """Rewrite profile hosts to the ingress IP, then send."""
        parts = urlsplit(request.url or "")
        if parts.hostname in self._hosts:
            request.headers["Host"] = parts.netloc
            netloc = self._ip if parts.port is None else f"{self._ip}:{parts.port}"
            request.url = urlunsplit(parts._replace(netloc=netloc))
        return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)


class TimeoutSession(requests.Session):
    """A session with a default timeout, so no call can hang forever."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        super().__init__()
        self.default_timeout = timeout

    # Narrows the long keyword list of requests.Session.request, hence the pyright ignore.
    @override
    def request(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, method: str | bytes, url: str | bytes, *args: object, **kwargs: object
    ) -> requests.Response:
        """Send a request, with the default timeout unless one is given."""
        kwargs.setdefault("timeout", self.default_timeout)
        return super().request(method, url, *args, **kwargs)  # pyright: ignore[reportArgumentType]


def make_session(urls: Mapping[str, str], ingress_ip: str | None = None) -> requests.Session:
    """A session for the profile URLs; with ingress_ip, profile hosts are reached through that IP."""
    session = TimeoutSession()
    session.headers["User-Agent"] = "podiumd-tests"
    if ingress_ip:
        hosts = {urlsplit(u).hostname or "" for u in urls.values()}
        adapter = HostHeaderAdapter(hosts, ingress_ip)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    return session
