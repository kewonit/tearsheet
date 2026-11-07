"""Failures a tool reports to an agent.

The MCP SDK hides the message of any exception that isn't a ToolError, so
agents would only see "Error executing tool X". Every expected failure uses
ToolFailure so the agent gets a code, a retry decision and a next step.
"""

import json
from enum import StrEnum

from mcp.server.mcpserver.exceptions import ToolError


class ErrorCode(StrEnum):
    SESSION_EXPIRED = "SESSION_EXPIRED"
    BLOCKED = "BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_CHANGED = "UPSTREAM_CHANGED"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    SETUP_REQUIRED = "SETUP_REQUIRED"
    PLAN_REQUIRED = "PLAN_REQUIRED"


# BLOCKED is deliberately not retryable: tearsheet stops rather than working
# around an upstream refusal. See docs/DATA-USE.md.
_RETRYABLE = {ErrorCode.RATE_LIMITED, ErrorCode.UPSTREAM_UNAVAILABLE}


class ToolFailure(ToolError):
    """An expected failure, serialised as compact JSON for the agent to read."""

    def __init__(self, code: ErrorCode, message: str, *, hint: str | None = None) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        self.retryable = code in _RETRYABLE
        super().__init__(json.dumps(self.to_dict(), separators=(",", ":")))

    def to_dict(self) -> dict[str, str | bool]:
        body: dict[str, str | bool] = {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.hint:
            body["hint"] = self.hint
        return body
