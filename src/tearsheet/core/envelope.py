"""The shape every tool result shares.

Agents get the same fields from every tool: what the data is about, how old
it is, its units, where it came from and whether it has been checked.
"""

import json
from datetime import UTC, date, datetime
from typing import Literal

from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, Field


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
    payload = envelope.model_dump(mode="json", exclude_none=True)
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
    )
