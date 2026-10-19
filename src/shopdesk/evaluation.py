"""Reproducible baseline/full-chain benchmark and automatic bad-case taxonomy."""

import json
import statistics
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from .config import ASSETS, Settings
from .contracts import ChatRequest
from .retrieval import Retriever
from .service import Service


def evaluate():
    cases = json.loads((ASSETS / "data/benchmark.json").read_text(encoding="utf8"))
    measured = []
    baseline = []
    with TemporaryDirectory(prefix="shopdesk-bench-") as temp:
        full = Service(Settings(Path(temp) / "full"))
        base = Service(Settings(Path(temp) / "baseline"))
        full.index("adaptive")
        base.index("window")
        base_index = Retriever(base.settings, base.store)
        try:
            for case in cases:
                session = full.store.new_session("demo-customer")["id"]
                for index, expected in enumerate(case["turns"]):
                    response = full.chat(
                        ChatRequest(
                            session_id=session,
                            request_id=f"{case['id']}-{index}",
                            message=expected["message"],
                        )
                    )
                    retrieved = {d["doc_id"] for d in response["reranked"][:3]}
                    relevant = expected["sources"]
                    hit = all(fact in response["answer"] for fact in expected["facts"])
                    recall = (
                        len(retrieved & set(relevant)) / len(set(relevant)) if relevant else None
                    )
                    failures = []
                    if not hit:
                        failures.append("answer_fact_missing")
                    if response["intent"] != expected["intent"]:
                        failures.append("intent_mismatch")
                    if response["status"] != expected["status"]:
                        failures.append("route_mismatch")
                    if relevant and not recall:
                        failures.append("retrieval_miss")
                    measured.append(
                        {
                            "case_id": case["id"],
                            "turn": index + 1,
                            "message": expected["message"],
                            "answer": response["answer"],
                            "intent_correct": response["intent"] == expected["intent"],
                            "route_correct": response["status"] == expected["status"],
                            "answer_fact_hit": hit,
                            "recall_at_3": recall,
                            "entity_correct": response["product_id"]
                            == expected.get("product", response["product_id"]),
                            "elapsed_ms": response["elapsed_ms"],
                            "failures": failures,
                        }
                    )
                    if relevant:
                        started = time.perf_counter()
                        documents = base_index.search(expected["message"], limit=3)
                        # Raw-query window baseline: same lexical+dense index, no rewrite/rerank.
                        text = "\n".join(d["text"] for d in documents)
                        baseline.append(
                            {
                                "hit": all(f in text for f in expected["facts"]),
                                "recall": len({d["doc_id"] for d in documents} & set(relevant))
                                / len(set(relevant)),
                                "elapsed_ms": (time.perf_counter() - started) * 1000,
                            }
                        )
        finally:
            base_index.close()
    relevant = [m for m in measured if m["recall_at_3"] is not None]
    return {
        "dataset": "shopdesk-jade-fictional-v1",
        "mode": "local-hash-embedding/local-rerank",
        "full": {
            "answer_fact_hit": sum(m["answer_fact_hit"] for m in measured) / len(measured),
            "intent_accuracy": sum(m["intent_correct"] for m in measured) / len(measured),
            "route_accuracy": sum(m["route_correct"] for m in measured) / len(measured),
            "entity_accuracy": sum(m["entity_correct"] for m in measured) / len(measured),
            "retrieval_recall_at_3": sum(m["recall_at_3"] for m in relevant) / len(relevant),
            "p50_latency_ms": statistics.median(m["elapsed_ms"] for m in measured),
            "p95_latency_ms": sorted(m["elapsed_ms"] for m in measured)[
                min(len(measured) - 1, int(len(measured) * 0.95))
            ],
        },
        "baseline": {
            "description": "window chunks + raw query + hybrid retrieval; retrieval-only answer context coverage",
            "answer_context_fact_hit": sum(m["hit"] for m in baseline) / len(baseline),
            "retrieval_recall_at_3": sum(m["recall"] for m in baseline) / len(baseline),
            "p50_retrieval_ms": statistics.median(m["elapsed_ms"] for m in baseline),
        },
        "cases": measured,
        "bad_cases": [m for m in measured if m["failures"]],
    }
