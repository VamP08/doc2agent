"""SSRF guardrails: refuse to fetch or call private / internal network addresses.

Doc2Agent fetches user-supplied URLs and lets an agent fire real HTTP
requests, so we validate every hostname before any request leaves the box.
"""
import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}

# The one deliberate exception: the app's own host, so the bundled AeroTrack
# demo API (/demo) can be ingested and called. Registered at ingest time only
# when the requested URL's host matches the Host header AND targets /demo.
TRUSTED_NETLOCS: set[str] = set()


class UnsafeURLError(ValueError):
    pass


def trust_own_netloc(netloc: str) -> None:
    TRUSTED_NETLOCS.add(netloc.lower())


def assert_public_url(url: str) -> None:
    """Raise UnsafeURLError unless the URL resolves only to public IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Only http/https URLs are allowed, got '{parsed.scheme}'.")
    if parsed.netloc.lower() in TRUSTED_NETLOCS:
        return
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no hostname.")
    if host.lower() in BLOCKED_HOSTS:
        raise UnsafeURLError(f"Host '{host}' is blocked.")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{host}': {exc}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeURLError(
                f"Host '{host}' resolves to non-public address {ip}; refusing to connect."
            )
