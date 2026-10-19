from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Intent = Literal["product", "shipping", "returns", "complaint", "handoff", "smalltalk", "unknown"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeInput(StrictModel):
    title: str = Field(min_length=2, max_length=160)
    kind: Literal["product", "faq", "sop"]
    product_id: str = ""
    content: str = Field(min_length=10, max_length=80000)
    active: bool = True

    @field_validator("title", "content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()


class ChatRequest(StrictModel):
    session_id: str
    message: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(min_length=1, max_length=80)

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("消息不能为空")
        return value.strip()


class QueryPlan(StrictModel):
    intent: Intent
    rewritten_query: str
    product_id: str = ""
    needs_clarification: bool = False
    handoff_reason: str = ""


class AnswerDraft(StrictModel):
    answer: str = Field(min_length=1, max_length=4000)
    citation_ids: list[str]
    needs_handoff: bool = False


class TicketUpdate(StrictModel):
    status: Literal["open", "in_progress", "resolved"]
    assignee: str = ""
    resolution: str = ""


class RerankItem(StrictModel):
    index: int = Field(ge=0)
    score: float = Field(ge=0, le=1)
