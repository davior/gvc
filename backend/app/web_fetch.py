"""Fetching a web page a user hands the assistant, without becoming an open proxy.

The URL is typed by whoever is using the app, so where it points is untrusted. Every
hop is checked against private address space *after DNS resolution* (a name resolving
to 127.0.0.1 or 169.254.169.254 is refused exactly like the literal), and redirects are
followed by hand so no hop skips the check. A port-scan of the container's network by
way of "attach this URL" is the thing being prevented.

Ported from gecko-notes' `web_fetch.py`, made synchronous (GVC's routers are) and cut
down: one browser-like User-Agent rather than Notes' two retried profiles, because the
assistant reads text, and a page that refuses an ordinary browser header is better
reported than fought with. `app.safe_url` is the other guard in this app; it is for a
setting saved once, is https-only, and lets a name that won't resolve through. That is
right for a provider's base URL and wrong for a fetch made right now.

Left open, as in Notes: the TOCTOU gap between resolving here and httpx resolving again
to connect (DNS rebinding). Closing it means pinning the connection to the checked
address while keeping SNI, which httpx doesn't expose cleanly.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from app import outbound

TIMEOUT = 20.0
MAX_REDIRECTS = 5

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,"
              "application/pdf;q=0.8,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}


class FetchError(Exception):
    """A fetch failed in a way worth showing the user as it is."""

    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class Fetched:
    url: str
    content_type: str
    charset: Optional[str]
    body: bytes


def _resolve(host: str, port: int) -> List[str]:
    """Every address `host` answers with. A seam for tests, which have no DNS."""
    return [info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def require_public_url(url: str) -> str:
    """The URL, if it is http(s) and every address it resolves to is public."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise FetchError("invalid_url", "The address must start with http:// or https://", 400)
    host = (parts.hostname or "").lower()
    if not host:
        raise FetchError("invalid_url", "That address has no hostname", 400)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise FetchError("invalid_url", "That address has an invalid port", 400) from exc
    try:
        # A literal needs no lookup, and is checked even where resolving is faked.
        addresses = [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        addresses = None
    try:
        addresses = addresses or _resolve(host, port)
    except (socket.gaierror, UnicodeError) as exc:
        raise FetchError("dns_failed", f"Could not find {host}", 400) from exc
    if not addresses:
        raise FetchError("dns_failed", f"Could not find {host}", 400)
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            continue
        # is_global is False for loopback, link-local (cloud metadata), RFC 1918, CGNAT
        # and unique-local v6: the whole set, in one check that stays right for v6.
        if not ip.is_global:
            raise FetchError("ssrf_blocked", "That address points to a private or internal "
                             "network", 400)
    return parts.geturl()


def _content_type(response: httpx.Response) -> Tuple[str, Optional[str]]:
    raw = response.headers.get("content-type", "")
    kind, _, params = raw.partition(";")
    charset = None
    for param in params.split(";"):
        name, _, value = param.strip().partition("=")
        if name.lower() == "charset" and value:
            charset = value.strip("\"' ")
    return kind.strip().lower(), charset


def fetch(url: str, *, max_bytes: int, accept: Tuple[str, ...]) -> Fetched:
    """GET `url`, following up to MAX_REDIRECTS hops, each checked, reading at most
    `max_bytes`. A content type outside `accept` is refused before the body is read."""
    current = require_public_url(url)
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False, headers=_HEADERS,
                      transport=outbound.TRANSPORT) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with client.stream("GET", current) as response:
                    if response.is_redirect and response.headers.get("location"):
                        current = require_public_url(
                            str(httpx.URL(current).join(response.headers["location"])))
                        continue
                    if response.status_code in (401, 403, 429):
                        raise FetchError("blocked", f"The site refused the request (HTTP "
                                         f"{response.status_code}). It may need a login, or "
                                         "block automated readers.")
                    if response.status_code >= 400:
                        raise FetchError("http_error",
                                         f"That address answered HTTP {response.status_code}")
                    kind, charset = _content_type(response)
                    if kind and not kind.startswith(accept):
                        raise FetchError("unsupported_type",
                                         f"That address is {kind}, which can't be read as "
                                         "text", 415)
                    chunks: List[bytes] = []
                    received = 0
                    for chunk in response.iter_bytes():
                        received += len(chunk)
                        if received > max_bytes:
                            raise FetchError("too_large", "That page is larger than "
                                             f"{max_bytes // (1024 * 1024)} MB", 413)
                        chunks.append(chunk)
                    return Fetched(url=current, content_type=kind, charset=charset,
                                   body=b"".join(chunks))
            except httpx.TimeoutException as exc:
                raise FetchError("fetch_failed", "That address took too long to answer") from exc
            except httpx.HTTPError as exc:
                raise FetchError("fetch_failed",
                                 f"Could not reach that address ({type(exc).__name__})") from exc
    raise FetchError("too_many_redirects", "That address redirected too many times", 400)
