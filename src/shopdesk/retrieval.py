"""Qdrant dense search + Chinese BM25 + reciprocal rank fusion."""

import hashlib
import json
import logging
import os
import re
import uuid

import jieba
from langsmith import traceable
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from .chunking import split_document
from .embeddings import CachedEmbeddings, create_embeddings

jieba.setLogLevel(logging.ERROR)
STOP = {
    "的",
    "了",
    "吗",
    "呢",
    "是",
    "这",
    "我",
    "你",
    "它",
    "这个",
    "那",
    "请问",
    "可以",
    "怎么",
    "什么",
    "一下",
    "一个",
    "是否",
    "请",
    "还有",
    "能",
    "有",
    "要",
    "和",
    "都",
    "就",
    "也",
    "在",
}


def terms(text):
    return [
        t.lower()
        for t in jieba.lcut(text)
        if re.search(r"[\w\u4e00-\u9fff]", t) and t.lower() not in STOP
    ]


def overlap_score(query, text):
    q = set(terms(query))
    t = set(terms(text))
    return len(q & t) / (len(q) or 1)


class Retriever:
    def __init__(self, settings, store):
        self.settings = settings
        self.store = store
        self.embedding = CachedEmbeddings(
            create_embeddings(settings.embedding), settings.runtime / "embeddings.sqlite"
        )
        self.client = (
            QdrantClient(url=settings.qdrant_url, api_key=os.getenv("QDRANT_API_KEY") or None)
            if settings.qdrant_url
            else QdrantClient(path=str(settings.runtime / "qdrant"))
        )
        self.collection = settings.collection
        self.manifest = settings.runtime / "index.json"

    def close(self):
        self.client.close()

    def revision(self, docs, strategy):
        return hashlib.sha256(
            json.dumps(
                {
                    "documents": [(d["id"], d["version"], d["content"]) for d in docs],
                    "chunker": "adaptive-v1.1",
                    "embedding": self.embedding.fingerprint,
                    "strategy": strategy,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()

    @traceable(name="knowledge.index")
    def rebuild(self, strategy="adaptive"):
        if strategy not in ("adaptive", "window"):
            raise ValueError("分块策略应为 adaptive 或 window")
        docs = self.store.knowledge(active_only=True)
        chunks = [c for d in docs for c in split_document(d, self.embedding, strategy)]
        exists = self.client.collection_exists(self.collection)
        old = []
        if exists:
            points, cursor = self.client.scroll(self.collection, limit=256)
            old.extend(str(p.id) for p in points)
            while cursor is not None:
                points, cursor = self.client.scroll(self.collection, offset=cursor, limit=256)
                old.extend(str(p.id) for p in points)
        if chunks:
            vectors = self.embedding.embed_documents([c["context"] for c in chunks])
            if exists and self.client.get_collection(
                self.collection
            ).config.params.vectors.size != len(vectors[0]):
                raise ValueError("向量维度改变，请设置新的 QDRANT_COLLECTION")
            if not exists:
                self.client.create_collection(
                    self.collection,
                    vectors_config=models.VectorParams(
                        size=len(vectors[0]), distance=models.Distance.COSINE
                    ),
                )
            points = [
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, c["id"])), vector=v, payload=c
                )
                for c, v in zip(chunks, vectors)
            ]
            for i in range(0, len(points), 128):
                self.client.upsert(self.collection, points[i : i + 128], wait=True)
            current = {str(p.id) for p in points}
        else:
            current = set()
        stale = [key for key in old if key not in current]
        if stale:
            self.client.delete(self.collection, models.PointIdsList(points=stale), wait=True)
        manifest = {
            "revision": self.revision(docs, strategy),
            "strategy": strategy,
            "chunks": len(chunks),
            "documents": len(docs),
            "fingerprint": self.embedding.fingerprint,
        }
        from .storage import write_json

        write_json(self.manifest, manifest)
        return manifest

    def ready(self):
        from .storage import read_json

        old = read_json(self.manifest) if self.manifest.exists() else {}
        strategy = old.get("strategy", "adaptive")
        if old.get("revision") != self.revision(self.store.knowledge(active_only=True), strategy):
            return self.rebuild(strategy)
        return old

    def chunks(self):
        if not self.client.collection_exists(self.collection):
            return []
        rows, cursor = self.client.scroll(self.collection, limit=256)
        while cursor is not None:
            more, cursor = self.client.scroll(self.collection, offset=cursor, limit=256)
            rows.extend(more)
        return [p.payload for p in rows]

    @traceable(name="rag.hybrid_retrieval")
    def search(self, query, product_id="", limit=10):
        self.ready()
        chunks = [c for c in self.chunks() if not product_id or c["product_id"] in ("", product_id)]
        if not chunks:
            return []
        corpus = [terms(c["context"]) or ["_"] for c in chunks]
        scores = BM25Okapi(corpus).get_scores(terms(query))
        lexical = sorted(range(len(chunks)), key=lambda i: float(scores[i]), reverse=True)[
            : limit * 2
        ]
        conditions = (
            [models.FieldCondition(key="product_id", match=models.MatchAny(any=["", product_id]))]
            if product_id
            else []
        )
        dense = self.client.query_points(
            self.collection,
            query=self.embedding.embed_query(query),
            query_filter=models.Filter(must=conditions) if conditions else None,
            limit=limit * 2,
        ).points
        by_id = {c["id"]: c for c in chunks}
        fused = {}
        bm = {}
        for rank, i in enumerate(lexical, 1):
            if scores[i] > 0:
                fused[chunks[i]["id"]] = 1 / (60 + rank)
            bm[chunks[i]["id"]] = float(scores[i])
        for rank, p in enumerate(dense, 1):
            key = p.payload["id"]
            fused[key] = fused.get(key, 0) + 1 / (60 + rank)
        return [
            {
                **by_id[key],
                "fusion_score": fused[key],
                "bm25_score": bm.get(key, 0),
                "overlap": overlap_score(query, by_id[key]["context"]),
            }
            for key in sorted(fused, key=fused.get, reverse=True)
            if key in by_id
        ][:limit]
