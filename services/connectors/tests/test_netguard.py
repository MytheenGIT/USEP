from __future__ import annotations

import pytest

from console_api.netguard import UnsafeUrlError, check_outbound_url


def _resolver(*addresses: str):
    async def resolve(host: str) -> list[str]:
        return list(addresses)

    return resolve


async def _check(url: str, resolver=None, allow_private=False, allowed=None) -> str:
    return await check_outbound_url(url, allow_private=allow_private, allowed_hosts=allowed or [], resolver=resolver or _resolver("93.184.216.34"))


async def test_public_https_host_is_accepted_and_cleaned() -> None:
    assert await _check("https://Acme.Atlassian.net/jira/software/projects/PAY") == "https://acme.atlassian.net"
    assert await _check("https://gitlab.example.com:8443/x") == "https://gitlab.example.com:8443"


@pytest.mark.parametrize("url", ["http://acme.atlassian.net", "ftp://x.com", "acme.atlassian.net", "https://", "https://user:pw@acme.atlassian.net"])
async def test_rejects_bad_scheme_credentials_or_empty_host(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        await _check(url)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.9", "169.254.169.254", "::1"])
async def test_blocks_private_ip_literals(ip: str) -> None:
    host = f"[{ip}]" if ":" in ip else ip
    with pytest.raises(UnsafeUrlError, match="private or internal"):
        await _check(f"https://{host}/")


async def test_blocks_host_that_resolves_to_private_address() -> None:
    with pytest.raises(UnsafeUrlError, match="private or internal"):
        await _check("https://jira.corp.example.com", resolver=_resolver("93.184.216.34", "10.1.2.3"))


async def test_unresolvable_host_is_refused() -> None:
    async def fail(host: str) -> list[str]:
        raise OSError("nope")

    with pytest.raises(UnsafeUrlError, match="could not be resolved"):
        await _check("https://nope.example.com", resolver=fail)


async def test_private_hosts_allowed_when_enabled() -> None:
    assert await _check("https://10.0.0.5:8443", allow_private=True) == "https://10.0.0.5:8443"


async def test_allow_list_restricts_hosts() -> None:
    assert await _check("https://gitlab.example.com", allowed=["gitlab.example.com"]) == "https://gitlab.example.com"
    with pytest.raises(UnsafeUrlError, match="allowed list"):
        await _check("https://evil.example.com", allowed=["gitlab.example.com"])
