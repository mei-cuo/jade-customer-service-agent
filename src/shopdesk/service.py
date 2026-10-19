"""One application boundary for REST, SSE, CLI and benchmarks."""

import threading
import time
from contextlib import ExitStack

from langgraph.checkpoint.sqlite import SqliteSaver

from .generation import Generator
from .graph import build_graph
from .planning import Planner
from .rerank import Reranker
from .retrieval import Retriever
from .storage import write_json
from .store import Store


class Service:
    def __init__(self, settings):
        self.settings = settings
        if settings.mode not in ("local", "llm"):
            raise ValueError("SHOPDESK_MODE 应为 local 或 llm")
        self.store = Store(settings.runtime / "shopdesk-jade.sqlite")
        self.store.seed()
        self.lock = threading.RLock()
        self.planner = Planner(settings.mode)
        self.generator = Generator(self.planner)
        self.reranker = Reranker(settings.reranker)

    def index(self, strategy="adaptive"):
        with self.lock:
            index = Retriever(self.settings, self.store)
            try:
                return index.rebuild(strategy)
            finally:
                index.close()

    def chat(self, request, customer="demo-customer"):
        response = None
        for event in self.events(request, customer):
            if event["event"] == "answer":
                response = event["data"]
        return response

    def events(self, request, customer="demo-customer"):
        with self.lock:
            session = self.store.session(request.session_id, customer)
            previous = self.store.claim_turn(
                request.session_id, request.request_id, request.message
            )
            if previous is not None:
                yield {"event": "answer", "data": {**previous, "cached": True}}
                return
            start = time.perf_counter()
            try:
                with ExitStack() as stack:
                    retriever = Retriever(self.settings, self.store)
                    stack.callback(retriever.close)
                    saver = stack.enter_context(
                        SqliteSaver.from_conn_string(
                            str(self.settings.runtime / "checkpoints.sqlite")
                        )
                    )
                    graph = build_graph(
                        self.store, retriever, self.reranker, self.planner, self.generator, saver
                    )
                    config = {
                        "configurable": {
                            "thread_id": request.session_id + ":" + request.request_id
                        },
                        "recursion_limit": 25,
                        "tags": ["shopdesk", self.settings.mode],
                        "metadata": {
                            "session_id": request.session_id,
                            "request_id": request.request_id,
                        },
                    }
                    value = {
                        "session_id": request.session_id,
                        "request_id": request.request_id,
                        "customer_id": customer,
                        "message": request.message,
                        "memory": session["memory"],
                        "history": session["messages"][-12:],
                        "timeline": [],
                    }
                    for update in graph.stream(value, config, stream_mode="updates"):
                        for node, delta in update.items():
                            yield {
                                "event": "stage",
                                "data": {
                                    "node": node,
                                    "elapsed_ms": delta.get("timeline", [{}])[0].get(
                                        "elapsed_ms", 0
                                    ),
                                },
                            }
                    state = graph.get_state(config).values
                    response = {
                        "session_id": request.session_id,
                        "request_id": request.request_id,
                        "answer": state["answer"],
                        "status": state["status"],
                        "intent": state["intent"],
                        "rewritten_query": state.get("plan", {}).get(
                            "rewritten_query", request.message
                        ),
                        "product_id": state.get("plan", {}).get("product_id", ""),
                        "citations": state["citations"],
                        "ticket": state.get("ticket"),
                        "retrieval": [
                            {
                                "id": d["id"],
                                "title": d["title"],
                                "section": d["section"],
                                "fusion_score": d["fusion_score"],
                                "bm25_score": d["bm25_score"],
                                "overlap": d["overlap"],
                            }
                            for d in state.get("candidates", [])
                        ],
                        "reranked": [
                            {
                                "id": d["id"],
                                "doc_id": d["doc_id"],
                                "title": d["title"],
                                "section": d["section"],
                                "rerank_score": d["rerank_score"],
                                "reranker": d["reranker"],
                            }
                            for d in state.get("reranked", [])
                        ],
                        "timeline": state["timeline"],
                        "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                        "mode": self.settings.mode,
                    }
                    self.store.finish_turn(
                        request.session_id,
                        request.request_id,
                        request.message,
                        response,
                        state["memory"],
                    )
                    write_json(
                        self.settings.home
                        / "outputs"
                        / request.session_id
                        / (request.request_id + ".json"),
                        response,
                    )
                    yield {"event": "answer", "data": response}
            except BaseException:
                self.store.fail_turn(request.session_id, request.request_id)
                raise
