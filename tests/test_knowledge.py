import pytest

from shopdesk.chunking import split_document, windows
from shopdesk.contracts import KnowledgeInput
from shopdesk.embeddings import HashEmbeddings
from shopdesk.retrieval import Retriever


def test_content_aware_chunks_keep_faq_pairs(service):
    faq = next(d for d in service.store.knowledge() if d["id"] == "faq-return")
    parts = split_document(faq, HashEmbeddings())
    assert len(parts) == 2 and all("Q：" in p["text"] and "A：" in p["text"] for p in parts)
    product = next(d for d in service.store.knowledge() if d["id"] == "product-j01")
    parts = split_document(product, HashEmbeddings())
    assert all(p["parent_text"] for p in parts)
    assert parts == split_document(product, HashEmbeddings())


def test_window_overlap():
    parts = windows("0123456789abcdefghij", 10, 3)
    assert parts[0][-3:] == parts[1][:3]
    with pytest.raises(ValueError):
        windows("x", 3, 3)


def test_knowledge_revision_reindexes_without_stale_chunks(service):
    index = Retriever(service.settings, service.store)
    try:
        index.ready()
        item = KnowledgeInput(
            title="限定测试商品规则",
            kind="faq",
            content="Q：玉兰代号测试怎么核对？\nA：玉兰代号测试凭专属标识 LILY-991 处理。",
        )
        key = service.store.put_knowledge(item)
        result = index.search("玉兰代号 LILY-991")
        assert any(d["doc_id"] == key for d in result)
        before = {d["id"] for d in index.chunks() if d["doc_id"] == key}
        service.store.put_knowledge(
            item.model_copy(
                update={"content": "Q：玉兰代号测试怎么核对？\nA：更新为 LILY-992，由人工复核。"}
            ),
            key,
        )
        index.ready()
        assert not before & {d["id"] for d in index.chunks()}
        service.store.delete_knowledge(key)
        index.ready()
        assert not any(d["doc_id"] == key for d in index.chunks())
    finally:
        index.close()


def test_inactive_and_empty_knowledge(service):
    for d in service.store.knowledge():
        service.store.put_knowledge(
            KnowledgeInput(
                **{k: d[k] for k in ("title", "kind", "product_id", "content")}, active=False
            ),
            d["id"],
        )
    index = Retriever(service.settings, service.store)
    try:
        assert index.search("翡翠圈口") == []
    finally:
        index.close()


def test_entity_filter_excludes_other_items(service):
    index = Retriever(service.settings, service.store)
    try:
        documents = index.search("翡翠尺寸重量", "jade-j01")
        assert all(d["product_id"] in ("", "jade-j01") for d in documents)
        assert any(d["doc_id"] == "product-j01" for d in documents)
    finally:
        index.close()


def test_deleting_all_knowledge_does_not_reseed_on_restart(service):
    from shopdesk.service import Service

    for row in service.store.knowledge():
        service.store.delete_knowledge(row["id"])
    assert Service(service.settings).store.knowledge() == []
