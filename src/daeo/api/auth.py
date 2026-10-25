"""API errors and token authentication."""

from __future__ import annotations

import hmac
from collections.abc import Callable

from fastapi import Request


class ApiError(Exception):
    """An error with a stable machine-readable code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def extract_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return request.headers.get("x-daeo-token") or None


def make_token_dependency(api_token: str, enabled: bool) -> Callable[[Request], None]:
    """Create a FastAPI dependency that verifies the engine token."""

    def require_token(request: Request) -> None:
        if not enabled:
            return
        provided = extract_token(request)
        if provided is None or not hmac.compare_digest(provided, api_token):
            raise ApiError(
                401,
                "unauthorized",
                "A valid API token is required. Send it as 'Authorization: Bearer <token>'.",
            )

    return require_token
