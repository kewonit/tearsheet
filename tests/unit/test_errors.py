import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from tearsheet.core.errors import ErrorCode, ToolFailure


def test_is_a_tool_error_so_the_sdk_passes_the_message_through():
    assert isinstance(ToolFailure(ErrorCode.NOT_FOUND, "x"), ToolError)


def test_message_is_compact_json_with_every_field():
    error = ToolFailure(ErrorCode.SESSION_EXPIRED, "Session ended", hint="Run: tearsheet login")
    assert json.loads(str(error)) == {
        "code": "SESSION_EXPIRED",
        "message": "Session ended",
        "retryable": False,
        "hint": "Run: tearsheet login",
    }
    assert ": " not in str(error).replace("Run: ", "")


def test_hint_is_left_out_when_absent():
    assert "hint" not in json.loads(str(ToolFailure(ErrorCode.NOT_FOUND, "x")))


@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        (ErrorCode.RATE_LIMITED, True),
        (ErrorCode.UPSTREAM_UNAVAILABLE, True),
        (ErrorCode.BLOCKED, False),
        (ErrorCode.SESSION_EXPIRED, False),
        (ErrorCode.INVALID_INPUT, False),
    ],
)
def test_retry_decision_follows_the_code(code, retryable):
    assert ToolFailure(code, "x").retryable is retryable
