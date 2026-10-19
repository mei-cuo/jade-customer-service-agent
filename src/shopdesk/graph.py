"""Intent → query rewrite → hybrid retrieval → rerank → grounded answer/handoff."""

import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from .generation import validate_draft
from .tools import order_tool


class State(TypedDict, total=False):
    session_id: str
    request_id: str
    customer_id: str
    message: str
    memory: dict
    history: list[dict]
    intent: str
    plan: dict
    order_id: str
    order_result: dict
    candidates: list[dict]
    reranked: list[dict]
    answer: str
    status: str
    citations: list[dict]
    ticket: dict | None
    handoff_reason: str
    metrics: dict
    timeline: Annotated[list[dict], operator.add]


def build_graph(store, retriever, reranker, planner, generator, checkpointer=None):
    def identify(s):
        plan, order = planner.local_plan(s["message"], s["memory"])
        return {
            "intent": plan.intent,
            "order_id": order,
            "ticket": None,
            "candidates": [],
            "reranked": [],
            "citations": [],
        }

    def rewrite(s):
        plan, order = planner.plan(s["message"], s["memory"], s["history"])
        return {
            "plan": plan.model_dump(),
            "intent": plan.intent,
            "order_id": order,
            "handoff_reason": plan.handoff_reason,
        }

    def route(s):
        if s["intent"] in ("handoff", "complaint"):
            return "handoff"
        if s["intent"] == "smalltalk":
            return "smalltalk"
        if s["plan"]["needs_clarification"]:
            return "clarify"
        if s["intent"] == "shipping" and s["order_id"]:
            return "order"
        return "retrieve"

    def retrieve(s):
        docs = retriever.search(s["plan"]["rewritten_query"], s["plan"]["product_id"])
        return {"candidates": docs}

    def rank(s):
        ranked = reranker.rank(
            s["plan"]["rewritten_query"], s["candidates"], s["intent"], s["plan"]["product_id"]
        )
        # Gate using lexical support, independent of backend-specific score scales.
        return {"reranked": ranked}

    def after_rank(s):
        if (
            not s["reranked"]
            or max(d["overlap"] for d in s["reranked"]) < 0.16
            or s["intent"] == "unknown"
        ):
            return "handoff"
        return "generate"

    def generate(s):
        draft = generator.generate(s["message"], s["plan"], s["reranked"], s["memory"])
        if not validate_draft(draft, s["reranked"]):
            return {"status": "needs_handoff", "handoff_reason": "生成结果未通过来源引用检查"}
        documents = {d["id"]: d for d in s["reranked"]}
        citations = [
            {
                **{
                    k: documents[key][k]
                    for k in ("id", "doc_id", "title", "section", "version", "kind", "rerank_score")
                },
                "text": documents[key].get("parent_text", documents[key]["text"]),
            }
            for key in draft.citation_ids
        ]
        return {
            "answer": draft.answer,
            "status": "needs_handoff" if draft.needs_handoff else "answered",
            "citations": citations,
        }

    def handoff(s):
        reason = s.get("handoff_reason") or (
            "客户要求人工"
            if s["intent"] == "handoff"
            else "投诉升级"
            if s["intent"] == "complaint"
            else "当前知识未覆盖该问题"
        )
        summary = "\n".join(
            [
                f"当前商品：{s.get('plan', {}).get('product_id') or s['memory'].get('product_id', '待确认')}",
                "历史摘要：" + s["memory"].get("summary", ""),
                "已有答复："
                + next(
                    (
                        m["content"][-500:]
                        for m in reversed(s["history"])
                        if m["role"] == "assistant"
                    ),
                    "暂无",
                ),
                "客户问题：" + s["message"],
                "转接原因：" + reason,
            ]
        )
        ticket = store.ticket(s["session_id"], s["request_id"], reason, summary)
        return {
            "status": "handoff",
            "ticket": ticket,
            "answer": f"已为您创建人工转接工单 {ticket['id']}。问题与已有对话已整理给人工客服，您可以继续补充商品或订单信息。",
        }

    def clarify(s):
        return {
            "status": "clarify",
            "answer": "您说的是哪款商品？可以告诉我商品名称或型号，例如清圆 J01 平安扣、清和 B02 手镯。",
            "citations": [],
        }

    def smalltalk(s):
        return {
            "status": "answered",
            "answer": "您好，我可以帮您了解商品规格、物流和退换货。告诉我商品名称或具体问题即可。",
            "citations": [],
        }

    def lookup(s):
        result = order_tool(s["customer_id"]).invoke({"order_id": s["order_id"]})
        if not result["found"]:
            return {
                "status": "needs_handoff",
                "handoff_reason": "订单未匹配当前客户",
                "order_result": result,
            }
        return {
            "status": "answered",
            "answer": f"演示订单 {result['order_id']} 当前状态：{result['status']}。{result['delivery']}",
            "order_result": result,
            "citations": [
                {
                    "id": result["order_id"],
                    "doc_id": result["order_id"],
                    "title": "当前客户的演示订单",
                    "section": "物流状态",
                    "text": result["delivery"],
                    "version": 1,
                    "kind": "order",
                    "rerank_score": 1,
                }
            ],
        }

    def remember(s):
        product = s.get("plan", {}).get("product_id") or s["memory"].get("product_id", "")
        questions = [m["content"] for m in s["history"] if m["role"] == "user"][-3:] + [
            s["message"]
        ]
        memory = {
            **s["memory"],
            "product_id": product,
            "intent": s["intent"],
            "summary": "；".join(questions)[-600:],
        }
        if s.get("order_result", {}).get("found"):
            memory["order_id"] = s["order_id"]
        return {"memory": memory}

    def timed(name, fn):
        def node(state):
            start = time.perf_counter()
            value = fn(state)
            value["timeline"] = [
                {"node": name, "elapsed_ms": round((time.perf_counter() - start) * 1000, 2)}
            ]
            return value

        return node

    graph = StateGraph(State)
    for name, fn in [
        ("intent", identify),
        ("rewrite", rewrite),
        ("retrieve", retrieve),
        ("rerank", rank),
        ("generate", generate),
        ("handoff", handoff),
        ("clarify", clarify),
        ("smalltalk", smalltalk),
        ("order", lookup),
        ("memory", remember),
    ]:
        graph.add_node(name, timed(name, fn))
    graph.add_edge(START, "intent")
    graph.add_edge("intent", "rewrite")
    graph.add_conditional_edges(
        "rewrite", route, {k: k for k in ("handoff", "smalltalk", "clarify", "order", "retrieve")}
    )
    graph.add_edge("retrieve", "rerank")
    graph.add_conditional_edges(
        "rerank", after_rank, {"generate": "generate", "handoff": "handoff"}
    )
    for name in ("generate", "order"):
        graph.add_conditional_edges(
            name,
            lambda s: "handoff" if s["status"] == "needs_handoff" else "memory",
            {"handoff": "handoff", "memory": "memory"},
        )
    for name in ("handoff", "clarify", "smalltalk"):
        graph.add_edge(name, "memory")
    graph.add_edge("memory", END)
    return graph.compile(checkpointer=checkpointer)
