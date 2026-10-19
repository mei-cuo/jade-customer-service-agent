"""Cited answer synthesis, with local extractive and live LLM implementations."""

import json
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage

from .config import ASSETS
from .contracts import AnswerDraft
from .retrieval import overlap_score
from .topics import topic_anchors


class Generator:
    def __init__(self, planner):
        self.planner = planner

    def generate(self, message, plan, documents, memory):
        if self.planner.mode == "local":
            passages = []
            ids = []
            topics = topic_anchors(message)
            for doc in documents:
                if len(passages) >= 2:
                    break
                if doc["doc_id"] in {d for d, _, _ in passages}:
                    continue
                body = doc.get("parent_text", doc["text"])
                if topics and not any(
                    t.lower() in (doc["section"] + " " + body).lower() for t in topics
                ):
                    continue
                if (
                    passages
                    and doc["reranker"].startswith("local")
                    and doc["rerank_score"] < documents[0]["rerank_score"] * 0.65
                ):
                    continue
                sentences = [
                    s.strip()
                    for s in re.split(r"(?<=[。！？])|\n", body)
                    if s.strip() and not re.match(r"^Q[：:]", s.strip())
                ]
                if not sentences:
                    continue
                scored = sorted(
                    enumerate(sentences), key=lambda p: overlap_score(message, p[1]), reverse=True
                )
                chosen = sorted({i for i, _ in scored[:3]})
                content = (
                    "".join(sentences[i] for i in chosen).removeprefix("A：").removeprefix("A:")
                )
                passages.append((doc["doc_id"], content, doc["id"]))
                ids.append(doc["id"])
            answer = "\n\n".join(
                content + f" [{i}]" for i, (_, content, _) in enumerate(passages, 1)
            )
            return AnswerDraft(
                answer=answer or "请补充商品名称或具体问题，我会继续帮您核对。", citation_ids=ids
            )
        prompt = (ASSETS / "prompts/answer.md").read_text(encoding="utf8")
        return (
            self.planner.model()
            .with_structured_output(
                AnswerDraft, method=os.getenv("STRUCTURED_METHOD", "function_calling")
            )
            .invoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(
                        content=json.dumps(
                            {
                                "message": message,
                                "plan": plan,
                                "memory": memory,
                                "sources": documents,
                            },
                            ensure_ascii=False,
                        )
                    ),
                ]
            )
        )


def validate_draft(draft, documents):
    allowed = {d["id"] for d in documents}
    return (
        bool(draft.answer.strip())
        and bool(draft.citation_ids)
        and len(set(draft.citation_ids)) == len(draft.citation_ids)
        and set(draft.citation_ids) <= allowed
    )
