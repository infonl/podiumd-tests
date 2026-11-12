"""HTTP sessions that reach the profile's URLs, also in host-header mode.

In host-header mode (minikube), requests to a profile host go to the IP of
the ingress service, with the original host in the Host header. Tests and
clients keep using the real URLs, e.g. https://zac.local/.
"""

from __future__ import annotations

import socket
import ssl

from contextlib import contextmanager
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
    from collections.abc import Generator
    from collections.abc import Mapping

    from requests.adapters import _HostParams  # pyright: ignore[reportPrivateUsage]  # the stubs' own return types
    from requests.adapters import _PoolKwargs  # pyright: ignore[reportPrivateUsage]

DEFAULT_TIMEOUT = 15


class HostHeaderAdapter(HTTPAdapter):
    """Sends requests for the given hosts to one IP, keeping the host in the Host header."""

    def __init__(self, hosts: set[str], ip: str) -> None:
        super().__init__()
        self._hosts: set[str] = hosts
        self._ip: str = ip

    @override
    def send(
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
            _restore(request, original)
        response.url = original
        return response

    @override
    def build_connection_pool_key_attributes(  # noqa: WPS118  # requests' HTTPAdapter method
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
            # urllib3 pool keys the requests stubs leave out of _PoolKwargs; it is type-check-only, so not extendable.
            extra = cast("dict[str, object]", pool_kwargs)  # pyright: ignore[reportInvalidCast]
            extra["server_hostname"] = name
            extra["assert_hostname"] = name
        return host_params, pool_kwargs


def _restore(request: requests.PreparedRequest, url: str) -> None:
    """Put the request's URL back and drop its Host header.

    Redirects copy this request; a stale Host header must not follow them to another host.
    """
    request.url = url
    request.headers.pop("Host")


class TimeoutSession(requests.Session):
    """A session with a default timeout, so no call can hang forever."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        super().__init__()
        self.default_timeout: float = timeout

    @override
    def request(self, method: str | bytes, url: str | bytes, *args: object, **kwargs: object) -> requests.Response:
        """Send a request, with the default timeout unless one is given."""
        kwargs.setdefault("timeout", self.default_timeout)
        return super().request(method, url, *args, **kwargs)  # pyright: ignore[reportArgumentType]


def make_session(
    urls: Mapping[str, str],
    ingress_ip: str | None = None,
    *,
    cookies: bool = True,
    verify: str | None = None,
) -> requests.Session:
    """Return a session for the profile URLs; with ingress_ip, profile hosts are reached through that IP.

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
        hosts = {url_host(url) for url in urls.values()}
        adapter = HostHeaderAdapter(hosts, ingress_ip)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    return session


@contextmanager
def _tls(url: str, ingress_ip: str | None, ca_file: str | None) -> Generator[ssl.SSLSocket]:
    """Yield a TLS connection to the host of an https URL, verified for that host; through ingress_ip if given."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    context = ssl.create_default_context(cafile=ca_file)
    with (
        socket.create_connection((ingress_ip or host, parts.port or 443), DEFAULT_TIMEOUT) as connection,
        context.wrap_socket(connection, server_hostname=host) as tls,
    ):
        yield tls


def peer_certificate(url: str, ingress_ip: str | None = None, ca_file: str | None = None) -> dict[str, object]:
    """Return the certificate the host of an https URL presents, verified for that host; through ingress_ip if given."""
    with _tls(url, ingress_ip, ca_file) as tls:
        return cast("dict[str, object]", tls.getpeercert())


def announced_body_status(
    url: str, size: int, ingress_ip: str | None = None, ca_file: str | None = None, *, wait: float = 5
) -> int | None:
    """Return the status of a POST to an https URL that announces size bytes and sends 1 KiB; None without answer.

    nginx answers 413 to a Content-Length above client_max_body_size before reading the body; a proxy that buffers
    the body first gives no answer within wait, and hides the limits behind it.
    """
    parts = urlsplit(url)
    head = (
        f"POST {parts.path or '/'} HTTP/1.1\r\nHost: {parts.netloc}\r\nContent-Length: {size}\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    )
    with _tls(url, ingress_ip, ca_file) as tls:
        tls.sendall(head.encode() + b"x" * 1024)
        tls.settimeout(wait)
        try:
            answer = tls.recv(64)
        except TimeoutError:
            return None
    return int(answer.split(b" ", 2)[1])
