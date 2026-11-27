"""The USEP error hierarchy.

Every exception raised by usep's own code (as opposed to a vendor SDK's native
exceptions, which adapters catch and translate) derives from `UsepError`. Keep
exception messages free of secret values at every layer: a message may name a
field, a key, a reason code or an exception type, never a credential, token or
matched sensitive value (ground rule, section 1; LLD CC-05).
"""

from __future__ import annotations

import traceback


def frames_only(exc: BaseException) -> str:
    """The stack frames of `exc` without its message, which may echo secrets or source content."""
    return "".join(traceback.format_tb(exc.__traceback__))


class UsepError(Exception):
    """Base class for every USEP application error."""


class ConfigError(UsepError):
    """Configuration or secrets failed validation, or could not be resolved.

    Raised by `usep.core.config` (ontology/bundle.py and gate.py already depend on
    this exact name and import path) and by the secret-resolution adapters in a
    later PR. Messages name the offending field or reference only, never a value.
    """


class DomainError(UsepError):
    """Base class for errors raised by domain logic (state machines, cursors, ...)."""


class InvalidStateTransitionError(DomainError):
    """A connector state transition was attempted that the state machine does not allow."""


class CursorConflictError(DomainError):
    """An optimistic version check on a cursor save failed; the caller should retry the batch."""


class RawStorageError(DomainError):
    """The stored state of a raw object contradicts what the writer needs (for example a row
    with no wrapped data key)."""


class PaginationError(UsepError):
    """A pagination helper detected a repeated cursor or exceeded its page budget."""


class TransientError(UsepError):
    """An HTTP call failed in a way that is expected to succeed on retry (timeout, 429, 5xx).

    Raised by `usep.ingestion.runtime.http` when classifying a response or a
    connection-level failure; caught by `usep.ingestion.runtime.retry.call_with_retry`.
    """
