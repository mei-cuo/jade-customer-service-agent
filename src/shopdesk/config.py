import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ASSETS = Path(__file__).parent / "assets"


def valid_id(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise ValueError("ID 使用字母、数字、连字符或下划线，长度 1–80")
    return value


@dataclass(frozen=True)
class Settings:
    home: Path
    mode: str = "local"
    embedding: str = "hash"
    reranker: str = "local"
    qdrant_url: str = ""
    collection: str = "shopdesk_jade_knowledge"
    admin_token: str = "local-demo-admin"

    @classmethod
    def load(cls, home=None):
        root = Path(home or os.getenv("SHOPDESK_HOME", ".")).resolve()
        load_dotenv(root / ".env", override=False)
        os.environ.setdefault("LANGSMITH_TRACING", "false")
        return cls(
            root,
            os.getenv("SHOPDESK_MODE", "local"),
            os.getenv("EMBEDDING_BACKEND", "hash"),
            os.getenv("RERANK_BACKEND", "local"),
            os.getenv("QDRANT_URL", ""),
            os.getenv("QDRANT_COLLECTION", "shopdesk_jade_knowledge"),
            os.getenv("SHOPDESK_ADMIN_TOKEN", "local-demo-admin"),
        )

    @property
    def runtime(self):
        p = self.home / "runtime"
        p.mkdir(parents=True, exist_ok=True)
        return p
