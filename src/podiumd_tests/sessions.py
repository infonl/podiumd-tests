"""HTTP sessions that reach the profile's URLs, also in host-header mode.

In host-header mode (minikube), requests to a profile host go to the IP of
the ingress service, with the original host in the Host header. Tests and
clients keep using the real URLs, e.g. http://zac.local/.
"""

from __future__ import annotations

from http.cookiejar import DefaultCookiePolicy
from typing import TYPE_CHECKING
from typing import cast
from typing import override
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import requests

from requests.adapters import HTTPAdapter

from podiumd_tests.responses import url_host

if TYPE_CHECKING:
    from collections.abc import Mapping

    from requests.adapters import _HostParams  # pyright: ignore[reportPrivateUsage]  # the stubs' own return types
    from requests.adapters import _PoolKwargs  # pyright: ignore[reportPrivateUsage]

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
        """Rewrite profile hosts to the ingress IP, send, and restore the URL.

        Restoring matters: requests resolves relative redirects against
        response.url, and tests assert on the final URL.
        """
        original = request.url or ""
        parts = urlsplit(original)
        if parts.hostname not in self._hosts:
            return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)
        request.headers["Host"] = parts.netloc
        netloc = self._ip if parts.port is None else f"{self._ip}:{parts.port}"
        request.url = urlunsplit(parts._replace(netloc=netloc))
        try:
            response = super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)
        finally:
            # Redirects copy this request; a stale Host header must not follow them to another host.
            request.url = original
            del request.headers["Host"]
        response.url = original
        return response

    @override
    def build_connection_pool_key_attributes(
        self,
        request: requests.PreparedRequest,
        verify: bool | str,
        cert: str | tuple[str, str] | None = None,
    ) -> tuple[_HostParams, _PoolKwargs]:
        """For https to the ingress IP: send the profile host as SNI and verify the certificate against it."""
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(request, verify, cert)
        host = request.headers.get("Host")
        if host and host_params["scheme"] == "https":
            name = urlsplit(f"//{host}").hostname
            # urllib3 pool keys the requests stubs leave out of _PoolKwargs.
            extra = cast("dict[str, object]", pool_kwargs)
            extra["server_hostname"] = name
            extra["assert_hostname"] = name
        return host_params, pool_kwargs


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


def make_session(
    urls: Mapping[str, str], ingress_ip: str | None = None, *, cookies: bool = True, verify: str | None = None
) -> requests.Session:
    """A session for the profile URLs; with ingress_ip, profile hosts are reached through that IP.

    verify: CA bundle file for https; None uses the system's CAs.

    cookies=False for token APIs: a Django session cookie picked up elsewhere (an admin
    login page) makes Open Klant fail token requests with HTTP 500.
    """
    session = TimeoutSession()
    session.headers["User-Agent"] = "podiumd-tests"
    if verify:
        session.verify = verify
    if not cookies:
        session.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))
    if ingress_ip:
        hosts = {url_host(u) for u in urls.values()}
        adapter = HostHeaderAdapter(hosts, ingress_ip)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    return session
