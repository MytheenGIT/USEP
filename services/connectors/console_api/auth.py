"""Admin sign-in with in-memory sessions (PoC: single admin, ADR-030).

Fail closed: if admin credentials are not configured, sign-in is refused. Tokens are random,
held in memory only and expire; a restart signs everyone out. Real SSO/OIDC replaces this later.
"""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass

from fastapi import Request

from console_api.errors import ConsoleError


@dataclass(frozen=True)
class Session:
    token: str
    username: str
    expires_at: float


class SessionStore:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, Session] = {}

    def create(self, username: str) -> Session:
        session = Session(secrets.token_urlsafe(32), username, time.monotonic() + self._ttl)
        self._sessions[session.token] = session
        return session

    def get(self, token: str) -> Session | None:
        session = self._sessions.get(token)
        if session is None:
            return None
        if session.expires_at < time.monotonic():
            self._sessions.pop(token, None)
            return None
        return session

    def revoke(self, token: str) -> None:
        self._sessions.pop(token, None)


class LoginThrottle:
    """Blocks a client after repeated failures, so the admin password cannot be guessed online."""

    def __init__(self, max_failures: int = 5, window_seconds: float = 300) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        now = time.monotonic()
        recent = [t for t in self._failures.get(key, []) if now - t < self._window]
        self._failures[key] = recent
        return recent

    def check(self, key: str) -> None:
        if len(self._recent(key)) >= self._max:
            raise ConsoleError(429, "too_many_attempts", "Too many failed sign-in attempts. Try again in a few minutes.")

    def fail(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def credentials_match(expected_user: str, expected_password: str, user: str, password: str) -> bool:
    """Constant-time comparison; refuses when no credentials are configured."""
    if not expected_user or not expected_password:
        return False
    user_ok = hmac.compare_digest(expected_user.encode(), user.encode())
    pass_ok = hmac.compare_digest(expected_password.encode(), password.encode())
    return user_ok and pass_ok


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def require_session(request: Request) -> Session:
    token = bearer_token(request)
    session = request.app.state.sessions.get(token) if token else None
    if session is None:
        raise ConsoleError(401, "unauthenticated", "Not signed in")
    request.state.actor = session.username  # for the access audit
    return session
