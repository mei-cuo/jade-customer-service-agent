import pytest

from shopdesk.contracts import AnswerDraft, ChatRequest
from shopdesk.generation import validate_draft
from shopdesk.planning import Planner
from shopdesk.rerank import Reranker


def test_unknown_citations_rejected():
    assert not validate_draft(
        AnswerDraft(answer="回答", citation_ids=["invented"]), [{"id": "real"}]
    )
    assert validate_draft(AnswerDraft(answer="回答", citation_ids=["real"]), [{"id": "real"}])


def test_invalid_rerank_api_index(monkeypatch):
    monkeypatch.setenv("RERANK_URL", "https://rerank.example.test/v1/rerank")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [{"index": 50, "relevance_score": 0.9}]}

    monkeypatch.setattr("shopdesk.rerank.httpx.post", lambda *a, **k: Response())
    with pytest.raises(ValueError):
        Reranker("http").rank("query", [{"context": "source"}], "product")


def test_llm_config_required():
    with pytest.raises(ValueError):
        Planner("llm").model()


def test_blank_message_rejected():
    with pytest.raises(ValueError):
        ChatRequest(session_id="x", request_id="y", message="   ")
