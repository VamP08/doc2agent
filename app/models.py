"""Pydantic models shared across the app."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Param(BaseModel):
    name: str
    location: Literal["query", "path", "body", "header"] = "query"
    type: str = "string"
    required: bool = False
    description: str = ""


class Endpoint(BaseModel):
    method: str = "GET"
    path: str
    description: str = ""
    params: list[Param] = Field(default_factory=list)


class IngestRequest(BaseModel):
    url: str
    api_key: Optional[str] = None
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"


class IngestResponse(BaseModel):
    session_id: str
    base_url: str
    source: Literal["openapi", "llm"]
    endpoints: list[Endpoint]


class ChatRequest(BaseModel):
    session_id: str
    message: str
    auto_approve: bool = False


class ApprovalDecision(BaseModel):
    approve: bool


class ToolCallTrace(BaseModel):
    tool: str
    method: str
    url: str
    status: Optional[int] = None
    ok: bool = True
    summary: str = ""


class ChatResponse(BaseModel):
    reply: str
    trace: list[ToolCallTrace] = Field(default_factory=list)
