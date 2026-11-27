"""Outbound URL guard. The admin now types the host the server will call with a token, so the URL is checked:
https only, no embedded credentials, and (unless allowed) no private, loopback or link-local addresses,
which blocks reaching internal services or the cloud metadata endpoint through a typed host.

On-prem Jira or GitLab on a private network: set USEP_INGESTION_ALLOW_PRIVATE_SOURCE_HOSTS=true.
USEP_INGESTION_ALLOWED_SOURCE_HOSTS (comma separated) restricts requests to exactly those hosts.
Residual risk: a host that changes its DNS answer between this check and the request (rebinding). An egress
firewall is the real control; this is defence in depth.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeUrlError(ValueError):
    """The URL must not be called. The message is safe to show the admin."""


def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


async def resolve_host(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


async def check_outbound_url(url: str, *, allow_private: bool, allowed_hosts: list[str], resolver=resolve_host) -> str:
    """Return the cleaned base URL (scheme and host only, no trailing slash) or raise UnsafeUrlError."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("Enter a full URL, for example https://example.com") from exc
    if parts.scheme != "https":
        raise UnsafeUrlError("Only https:// URLs are accepted")
    if parts.username or parts.password:
        raise UnsafeUrlError("Remove credentials from the URL; enter them in the credential fields")
    if not host:
        raise UnsafeUrlError("Enter a full URL, for example https://example.com")
    if allowed_hosts and host not in {h.lower() for h in allowed_hosts}:
        raise UnsafeUrlError(f"Host '{host}' is not on the server's allowed list")
    if not allow_private:
        try:
            addresses = [ipaddress.ip_address(host)] if _is_ip(host) else [ipaddress.ip_address(a) for a in await resolver(host)]
        except (OSError, ValueError) as exc:
            raise UnsafeUrlError(f"Host '{host}' could not be resolved") from exc
        if not addresses or any(_blocked(a) for a in addresses):
            raise UnsafeUrlError(f"Host '{host}' points at a private or internal address, which is blocked by the server")
    netloc = host if port in (None, 443) else f"{host}:{port}"
    return f"https://{netloc}"


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False
