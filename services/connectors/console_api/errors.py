"""Typed errors: a code, a message and a trace ID. No stack traces, SQL or source content."""

from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse


class ConsoleError(Exception):
    def __init__(self, status: int, code: str, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields


async def console_error_handler(request: Request, exc: ConsoleError) -> JSONResponse:
    body: dict = {"code": exc.code, "message": exc.message, "trace_id": uuid.uuid4().hex}
    if exc.fields:
        body["fields"] = exc.fields
    return JSONResponse(status_code=exc.status, content=body)
