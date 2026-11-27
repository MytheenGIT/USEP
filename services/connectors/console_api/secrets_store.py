"""Credentials typed into the console are held in memory only: never written to disk, logged or returned.

They live from submit until the configuration finishes processing, then are dropped. A restart loses them.
This is a stopgap: Vault references replace it once the credential design (proposed ADR-036) is accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Credentials:
    email: str = field(default="", repr=False)
    secret: str = field(default="", repr=False)  # token, or the password for ServiceNow
    ssh_key: str = field(default="", repr=False)  # a private SSH key, for GitHub and GitLab when no token is given


class SecretStore:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Credentials]] = {}

    def put(self, config_id: str, source: str, creds: Credentials) -> None:
        self._items.setdefault(config_id, {})[source] = creds

    def get(self, config_id: str, source: str) -> Credentials | None:
        return self._items.get(config_id, {}).get(source)

    def drop(self, config_id: str) -> None:
        self._items.pop(config_id, None)
