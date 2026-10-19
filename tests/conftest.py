import pytest

from shopdesk.config import Settings
from shopdesk.service import Service


@pytest.fixture(autouse=True)
def local_environment(monkeypatch):
    for key in ("OPENAI_API_KEY", "CHAT_MODEL", "QDRANT_URL", "EMBEDDING_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("SHOPDESK_MODE", "local")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("RERANK_BACKEND", "local")
    monkeypatch.setenv("SHOPDESK_ADMIN_TOKEN", "test-admin")


@pytest.fixture
def service(tmp_path):
    return Service(Settings(tmp_path))


@pytest.fixture
def session(service):
    return service.store.new_session("demo-customer")["id"]
