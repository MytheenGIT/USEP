"""Reading a Git repository over SSH with a private key the admin typed in.

An SSH key cannot call a REST API, so SSH access means ``git`` itself: clone the history, read the log. The key is
written to a private temporary folder (mode 0600) for the length of one command and deleted afterwards, never logged.
Host keys are checked strictly (``StrictHostKeyChecking=yes``) against the published keys of github.com and gitlab.com plus the
operator's known hosts: a host with no key is refused, because trusting whatever host answers would let anyone in the path see the key being offered.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

MAX_KEY_BYTES = 16_384
_BEGIN = ("-----BEGIN OPENSSH PRIVATE KEY-----", "-----BEGIN RSA PRIVATE KEY-----", "-----BEGIN EC PRIVATE KEY-----",
          "-----BEGIN DSA PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----")


class SshKeyError(ValueError):
    """The key or the SSH set-up cannot be used. The message is safe to show the admin and never holds the key."""


def validate_private_key(text: str) -> str:
    """The key with normalised line endings, or SshKeyError. Only unencrypted private keys are accepted."""
    key = text.replace("\r\n", "\n").strip()
    if not key:
        raise SshKeyError("Paste the private key")
    if len(key.encode()) > MAX_KEY_BYTES:
        raise SshKeyError("That is too large to be an SSH private key")
    lines = key.split("\n")
    if lines[0] not in _BEGIN or not lines[-1].startswith("-----END ") or not lines[-1].endswith("PRIVATE KEY-----"):
        raise SshKeyError("Paste the whole private key, from the -----BEGIN line to the -----END line (not the .pub file)")
    if any("ENCRYPTED" in line for line in lines[:3]):
        raise SshKeyError("Keys protected by a passphrase are not supported: use a key without one, kept for read access only")
    return key + "\n"


# The published SSH host keys of the two public platforms (ed25519). Their fingerprints are on the vendors' documentation pages:
# GitHub SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU, GitLab SHA256:eUXGGm1YGsMAS7vkcx6JOJdOGHPem5gQp4taiCfCLB8.
# They are public values, so every server can trust these two hosts without set-up. Any other host (a self-hosted GitLab or
# GitHub Enterprise) needs its key from the operator.
PUBLIC_HOST_KEYS = (
    "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n"
    "gitlab.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAfuCHKVTjquxvt6CM6tdG4SLp1Btn/nOeHHE5UOzRdf\n"
)


def load_known_hosts(content: str, file: str) -> str:
    """Hosts the server trusts: the operator's (setting or file) followed by the public platforms' published keys."""
    text = content.strip()
    if not text and file:
        try:
            text = Path(file).read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
    return (text + "\n" if text else "") + PUBLIC_HOST_KEYS


def ssh_host_for(key: str, base_url: str) -> str:
    """The SSH host of a platform: github.com for the public GitHub, else the host of the address the admin typed."""
    host = urlparse(base_url).hostname or ""
    return "github.com" if key == "github" and host == "api.github.com" else host


def require_host_key(known_hosts: str, host: str) -> None:
    """SshKeyError unless ``host`` has a key in ``known_hosts`` (hashed entries cannot be read, so they are left to ssh)."""
    for line in known_hosts.splitlines():
        field = line.split(None, 1)[0] if line.strip() and not line.startswith("#") else ""
        if field.startswith("|1|") or host.lower() in (h.strip("[]").split("]:")[0].lower() for h in field.split(",")):
            return
    raise SshKeyError(
        f"This server has no trusted host key for {host}. The operator must add it (USEP_INGESTION_SSH_KNOWN_HOSTS or _FILE); "
        "github.com and gitlab.com work without it"
    )


@asynccontextmanager
async def ssh_environment(key: str, known_hosts: str) -> AsyncIterator[dict[str, str]]:
    """Environment for one git command that authenticates with ``key`` and trusts only ``known_hosts``."""
    workdir = Path(tempfile.mkdtemp(prefix="usep-ssh-"))
    try:
        workdir.chmod(0o700)
        key_file, hosts_file = workdir / "id", workdir / "known_hosts"
        key_file.touch(mode=0o600)
        key_file.write_text(validate_private_key(key))
        hosts_file.write_text(known_hosts)
        ssh = (
            f"ssh -i {shlex.quote(str(key_file))} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes "
            f"-o UserKnownHostsFile={shlex.quote(str(hosts_file))} -o GlobalKnownHostsFile=/dev/null -o ConnectTimeout=15"
        )
        yield {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(workdir), "GIT_SSH_COMMAND": ssh,
            "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "ssh", "GIT_CONFIG_NOSYSTEM": "1",
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def run_git(args: list[str], env: dict[str, str], cwd: Path | None = None, timeout: float = 300.0) -> str:
    """Run git and return its output. The error text keeps git's own message but never the environment."""
    process = await asyncio.create_subprocess_exec(
        "git", *args, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f"git {args[0]} timed out after {int(timeout)} s") from None
    if process.returncode != 0:
        first = (err.decode(errors="replace").strip().splitlines() or ["failed"])[-1][:200]
        raise RuntimeError(f"git {args[0]} failed: {first}")
    return out.decode(errors="replace")
