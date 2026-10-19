import pytest

from shopdesk.contracts import ChatRequest, TicketUpdate
from shopdesk.service import Service


def ask(service, session, message, key):
    return service.chat(ChatRequest(session_id=session, message=message, request_id=key))


def test_jade_facts_and_source(service, session):
    result = ask(service, session, "J01 平安扣的尺寸和重量？", "facts")
    assert result["status"] == "answered"
    assert "28 mm" in result["answer"] and "8.6 g" in result["answer"]
    assert result["citations"][0]["doc_id"] == "product-j01"
    assert [n["node"] for n in result["timeline"]] == [
        "intent",
        "rewrite",
        "retrieve",
        "rerank",
        "generate",
        "memory",
    ]


def test_followup_survives_service_restart(service, session):
    ask(service, session, "J01 平安扣多大？", "first")
    reopened = Service(service.settings)
    followup = ask(reopened, session, "那它拆封后还能退吗？", "followup")
    assert followup["product_id"] == "jade-j01"
    assert "清圆 J01" in followup["rewritten_query"]
    assert "未佩戴" in followup["answer"]
    fee = ask(reopened, session, "那退货运费谁出？", "fee")
    assert "买家承担" in fee["answer"]


def test_product_switch_updates_memory(service, session):
    ask(service, session, "J01 平安扣多少钱？", "first")
    result = ask(service, session, "换问 B02 手镯圈口多少？", "switch")
    assert result["product_id"] == "jade-b02" and "56 mm" in result["answer"]
    assert service.store.session(session, "demo-customer")["memory"]["product_id"] == "jade-b02"


def test_unclear_pronoun_asks_for_product(service, session):
    result = ask(service, session, "它的厚度多大？", "clarify")
    assert result["status"] == "clarify" and not result["citations"]


def test_request_idempotency_and_payload_conflict(service, session):
    first = ask(service, session, "J01 多少钱？", "same")
    second = ask(service, session, "J01 多少钱？", "same")
    assert second["cached"] and second["answer"] == first["answer"]
    assert len(service.store.session(session, "demo-customer")["messages"]) == 2
    with pytest.raises(ValueError):
        ask(service, session, "换个问题", "same")


def test_session_customer_scope(service, session):
    with pytest.raises(ValueError):
        service.chat(
            ChatRequest(session_id=session, message="查询商品", request_id="other"),
            "other-customer",
        )


def test_handoff_deduplicated_and_state_transitions(service, session):
    first = ask(service, session, "我要转人工客服", "human-1")
    second = ask(service, session, "我要看实物", "human-2")
    assert first["ticket"]["id"] == second["ticket"]["id"]
    assert len(service.store.tickets()) == 1
    key = first["ticket"]["id"]
    with pytest.raises(ValueError):
        service.store.update_ticket(key, TicketUpdate(status="resolved", resolution="done"))
    service.store.update_ticket(key, TicketUpdate(status="in_progress", assignee="operator"))
    with pytest.raises(ValueError):
        service.store.update_ticket(key, TicketUpdate(status="resolved"))
    assert (
        service.store.update_ticket(
            key, TicketUpdate(status="resolved", resolution="已提供自然光视频")
        )["status"]
        == "resolved"
    )


@pytest.mark.parametrize(
    "message",
    ["B02 我想看自然光视频", "我手腕16厘米，手镯合适吗", "帮 J01 估价保值", "检查这只手镯有没有裂"],
)
def test_item_judgement_goes_to_specialist(service, session, message):
    result = ask(service, session, message, "specialist")
    assert result["status"] == "handoff" and "需要人工" in result["ticket"]["reason"]


def test_order_tool_does_not_expose_another_customer(service, session):
    good = ask(service, session, "查询订单 ORD-1001 的物流", "mine")
    assert "已发货" in good["answer"]
    denied = ask(service, session, "查询订单 ORD-2002 的物流", "other")
    assert denied["status"] == "handoff" and "待发货" not in denied["answer"]


def test_feedback_updates_bad_cases(service, session):
    ask(service, session, "J01 多少钱？", "rated")
    service.store.feedback(session, "rated", -1, "圈口解释不清楚")
    assert len(service.store.metrics()["bad_cases"]) == 1
    service.store.feedback(session, "rated", 1, "已解决")
    assert not service.store.metrics()["bad_cases"]


def test_off_topic_after_product_does_not_borrow_entity(service, session):
    ask(service, session, "J01 多大？", "first")
    result = ask(service, session, "帮我写诗", "off-topic")
    assert result["intent"] == "unknown" and result["status"] == "handoff"
