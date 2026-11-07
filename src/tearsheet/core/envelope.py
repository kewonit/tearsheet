"""The shape every tool result shares.

Agents get the same fields from every tool: what the data is about, how old
it is, its units, where it came from and whether it has been checked.
"""

import json
from datetime import UTC, date, datetime
from typing import Literal

from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, Field

from tearsheet.core.errors import ErrorCode, ToolFailure

# About 20,000 tokens, under the 25,000 Claude Code allows per tool result.
MAX_RESULT_CHARS = 80_000


class Entity(BaseModel):
    name: str
    nse: str | None = None
    bse: str | None = None


class Units(BaseModel):
    currency: Literal["INR"] = "INR"
    scale: Literal["crore"] = "crore"


class Source(BaseModel):
    provider: str
    url: str | None = None
    document: str | None = None


class Verification(BaseModel):
    status: Literal["matched", "mismatch", "unchecked"] = "unchecked"
    detail: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


class Envelope[T](BaseModel):
    data: T
    entity: Entity | None = None
    as_of: date | None = None
    retrieved_at: datetime = Field(default_factory=_now)
    units: Units | None = None
    sources: list[Source] = Field(default_factory=list)
    verification: Verification = Field(default_factory=Verification)
    warnings: list[str] = Field(default_factory=list)
    next_cursor: str | None = None


def to_result(envelope: Envelope) -> CallToolResult:
    """Build a tool result with compact text.

    The SDK's default text block is indented JSON, which costs tokens on every
    call. The text repeats the structured data for clients that only read text.
    """
    # Only empty top-level fields are dropped. A blank inside the data says a
    # figure is missing, and removing it would break the declared schema.
    payload = {
        key: value for key, value in envelope.model_dump(mode="json").items() if value is not None
    }
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        raise ToolFailure(
            ErrorCode.INVALID_INPUT,
            "That result is too large to return in one go.",
            hint="Ask for fewer periods, concise detail or a smaller limit.",
        )
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
    )
