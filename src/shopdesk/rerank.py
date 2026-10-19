"""Inspectable local reranker and optional neural/HTTP reranker adapters."""

import math
import os

import httpx
from langsmith import traceable

from .retrieval import overlap_score
from .topics import topic_anchors


class Reranker:
    def __init__(self, backend="local"):
        self.backend = backend
        self.model = None

    @traceable(name="rag.rerank")
    def rank(self, query, documents, intent, product_id="", top_n=4):
        if not documents:
            return []
        if self.backend == "http":
            endpoint = os.getenv("RERANK_URL")
            if not endpoint:
                raise ValueError("请配置 RERANK_URL")
            response = httpx.post(
                endpoint,
                headers={"Authorization": "Bearer " + os.getenv("RERANK_API_KEY", "")},
                json={
                    "model": os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
                    "query": query,
                    "documents": [d["context"] for d in documents],
                    "top_n": len(documents),
                },
                timeout=60,
            )
            response.raise_for_status()
            results = response.json()["results"]
            scores = {item["index"]: float(item["relevance_score"]) for item in results}
            if any(
                type(i) is not int or not 0 <= i < len(documents) or not math.isfinite(s)
                for i, s in scores.items()
            ):
                raise ValueError("Rerank 返回非法索引或分数")
            ranked = [
                {**d, "rerank_score": scores[i], "reranker": "http"}
                for i, d in enumerate(documents)
                if i in scores
            ]
        elif self.backend == "cross_encoder":
            if self.model is None:
                from sentence_transformers import CrossEncoder

                self.model = CrossEncoder(
                    os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"), trust_remote_code=False
                )
            scores = self.model.predict([(query, d["context"]) for d in documents])
            ranked = [
                {**d, "rerank_score": float(score), "reranker": "cross_encoder"}
                for d, score in zip(documents, scores)
            ]
        elif self.backend == "local":
            ranked = []
            for d in documents:
                lexical = overlap_score(query, d["context"])
                title = overlap_score(query, d["title"] + " " + d["section"])
                kind_bonus = (
                    0.13
                    if (intent == "product" and d["kind"] == "product")
                    or (intent == "returns" and ("退" in d["title"] or "售后" in d["title"]))
                    else 0
                )
                entity = 0.12 if product_id and d["product_id"] == product_id else 0
                topics = topic_anchors(query)
                has_topic = any(
                    w.lower() in (d["section"] + " " + d.get("parent_text", d["text"])).lower()
                    for w in topics
                )
                topic_bonus = 0.24 if topics and has_topic else -0.32 if topics else 0
                exact_topics = [
                    w
                    for w in (
                        "圈口",
                        "内径",
                        "重量",
                        "尺寸",
                        "挂绳",
                        "礼盒",
                        "标价",
                        "清洁",
                        "定制",
                        "运费",
                        "发票",
                    )
                    if w in query.lower()
                ]
                exact_bonus = (
                    0.3
                    if exact_topics
                    and any(w in d.get("parent_text", d["text"]).lower() for w in exact_topics)
                    else -0.25
                    if exact_topics
                    else 0
                )
                score = max(
                    0,
                    min(
                        1,
                        0.52 * lexical
                        + 0.14 * title
                        + kind_bonus
                        + entity
                        + topic_bonus
                        + exact_bonus,
                    ),
                )
                ranked.append({**d, "rerank_score": score, "reranker": "local-features-v1"})
        else:
            raise ValueError("RERANK_BACKEND 应为 local、http 或 cross_encoder")
        ranked.sort(key=lambda d: d["rerank_score"], reverse=True)
        # Diverse documents retain complementary policy/FAQ sources.
        result = []
        count = {}
        for d in ranked:
            if count.get(d["doc_id"], 0) >= 2:
                continue
            count[d["doc_id"]] = count.get(d["doc_id"], 0) + 1
            result.append(d)
            if len(result) >= top_n:
                break
        return result
