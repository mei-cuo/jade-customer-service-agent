"""SQLite source of truth for knowledge revisions, sessions, turns and handoffs."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from .config import ASSETS, valid_id
from .contracts import KnowledgeInput


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS knowledge(id TEXT PRIMARY KEY,title TEXT NOT NULL,kind TEXT NOT NULL,product_id TEXT NOT NULL,content TEXT NOT NULL,active INTEGER NOT NULL,version INTEGER NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,memory TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS turns(session_id TEXT NOT NULL,request_id TEXT NOT NULL,message TEXT NOT NULL,status TEXT NOT NULL,response TEXT,created_at TEXT NOT NULL,PRIMARY KEY(session_id,request_id));
            CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,request_id TEXT NOT NULL,reason TEXT NOT NULL,summary TEXT NOT NULL,status TEXT NOT NULL,assignee TEXT NOT NULL,resolution TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(session_id,request_id));
            CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,request_id TEXT NOT NULL,rating INTEGER NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(session_id,request_id));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def seed(self):
        with self.connect() as db:
            if db.execute("SELECT value FROM metadata WHERE key='seeded'").fetchone():
                return
            if not db.execute("SELECT count(*) FROM knowledge").fetchone()[0]:
                for item in json.loads((ASSETS / "data/knowledge.json").read_text(encoding="utf8")):
                    db.execute(
                        "INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,?)",
                        (
                            item["id"],
                            item["title"],
                            item["kind"],
                            item.get("product_id", ""),
                            item["content"],
                            1,
                            1,
                            now(),
                        ),
                    )
            db.execute("INSERT INTO metadata VALUES ('seeded','jade-v1')")

    def knowledge(self, active_only=False):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM knowledge"
                    + (" WHERE active=1" if active_only else "")
                    + " ORDER BY updated_at DESC,id"
                )
            ]

    def put_knowledge(self, item: KnowledgeInput, document_id=None):
        catalog = json.loads((ASSETS / "data/catalog.json").read_text(encoding="utf8"))
        if item.product_id and item.product_id not in {p["id"] for p in catalog}:
            raise ValueError("商品 ID 不在当前翡翠目录中")
        key = valid_id(document_id or uuid4().hex[:12])
        with self.connect() as db:
            old = db.execute("SELECT version FROM knowledge WHERE id=?", (key,)).fetchone()
            if document_id and old is None:
                raise ValueError("知识文档不存在")
            version = old[0] + 1 if old else 1
            db.execute(
                "INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,kind=excluded.kind,product_id=excluded.product_id,content=excluded.content,active=excluded.active,version=excluded.version,updated_at=excluded.updated_at",
                (
                    key,
                    item.title,
                    item.kind,
                    item.product_id,
                    item.content,
                    int(item.active),
                    version,
                    now(),
                ),
            )
        return key

    def delete_knowledge(self, key):
        with self.connect() as db:
            if db.execute("DELETE FROM knowledge WHERE id=?", (key,)).rowcount != 1:
                raise ValueError("知识文档不存在")

    def new_session(self, customer):
        valid_id(customer)
        key = uuid4().hex[:16]
        with self.connect() as db:
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?)", (key, customer, "{}", now(), now())
            )
        return self.session(key, customer)

    def session(self, key, customer):
        valid_id(key)
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM sessions WHERE id=? AND customer_id=?", (key, customer)
            ).fetchone()
            if row is None:
                raise ValueError("会话不存在或不属于当前客户")
            value = dict(row)
            value["memory"] = json.loads(value["memory"])
            value["messages"] = [
                dict(r)
                for r in db.execute(
                    "SELECT role,content,created_at FROM (SELECT id,role,content,created_at FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 40) ORDER BY id",
                    (key,),
                )
            ]
            return value

    def sessions(self, customer):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,created_at,updated_at FROM sessions WHERE customer_id=? ORDER BY updated_at DESC LIMIT 30",
                    (customer,),
                )
            ]

    def claim_turn(self, session, request, message):
        valid_id(request)
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM turns WHERE session_id=? AND request_id=?", (session, request)
            ).fetchone()
            if row:
                if row["message"] != message:
                    raise ValueError("同一 request_id 不能用于不同消息")
                if row["status"] == "completed":
                    return json.loads(row["response"])
                raise ValueError("该请求正在处理或已失败，请使用新的 request_id")
            db.execute(
                "INSERT INTO turns VALUES (?,?,?,?,?,?)",
                (session, request, message, "running", None, now()),
            )
        return None

    def fail_turn(self, session, request):
        with self.connect() as db:
            db.execute(
                "UPDATE turns SET status='failed' WHERE session_id=? AND request_id=? AND status='running'",
                (session, request),
            )

    def finish_turn(self, session, request, message, response, memory):
        with self.connect() as db:
            db.execute(
                "UPDATE turns SET status='completed',response=? WHERE session_id=? AND request_id=?",
                (json.dumps(response, ensure_ascii=False), session, request),
            )
            for role, content in [("user", message), ("assistant", response["answer"])]:
                db.execute(
                    "INSERT INTO messages(session_id,role,content,created_at) VALUES (?,?,?,?)",
                    (session, role, content, now()),
                )
            db.execute(
                "UPDATE sessions SET memory=?,updated_at=? WHERE id=?",
                (json.dumps(memory, ensure_ascii=False), now(), session),
            )

    def ticket(self, session, request, reason, summary):
        with self.connect() as db:
            old = db.execute(
                "SELECT * FROM tickets WHERE session_id=? AND status!='resolved' ORDER BY created_at DESC LIMIT 1",
                (session,),
            ).fetchone()
            if old:
                return dict(old)
            key = "T-" + uuid4().hex[:10].upper()
            db.execute(
                "INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?)",
                (key, session, request, reason, summary, "open", "", "", now(), now()),
            )
            return dict(db.execute("SELECT * FROM tickets WHERE id=?", (key,)).fetchone())

    def tickets(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM tickets ORDER BY created_at DESC")]

    def update_ticket(self, key, update):
        with self.connect() as db:
            old = db.execute("SELECT * FROM tickets WHERE id=?", (key,)).fetchone()
            if not old:
                raise ValueError("工单不存在")
            allowed = {
                "open": {"open", "in_progress"},
                "in_progress": {"in_progress", "resolved"},
                "resolved": {"resolved"},
            }
            if update.status not in allowed[old["status"]]:
                raise ValueError("工单按待接入→处理中→已解决流转")
            if update.status == "resolved" and not update.resolution.strip():
                raise ValueError("解决工单需要处理说明")
            db.execute(
                "UPDATE tickets SET status=?,assignee=?,resolution=?,updated_at=? WHERE id=?",
                (update.status, update.assignee, update.resolution, now(), key),
            )
            return dict(db.execute("SELECT * FROM tickets WHERE id=?", (key,)).fetchone())

    def feedback(self, session, request, rating, note):
        if rating not in (-1, 1):
            raise ValueError("反馈值应为 1 或 -1")
        with self.connect() as db:
            row = db.execute(
                "SELECT status FROM turns WHERE session_id=? AND request_id=?", (session, request)
            ).fetchone()
            if not row or row[0] != "completed":
                raise ValueError("只能评价已完成的回答")
            db.execute(
                "INSERT INTO feedback VALUES (?,?,?,?,?,?) ON CONFLICT(session_id,request_id) DO UPDATE SET rating=excluded.rating,note=excluded.note",
                (uuid4().hex, session, request, rating, note, now()),
            )

    def metrics(self):
        with self.connect() as db:
            completed = [
                json.loads(r[0])
                for r in db.execute("SELECT response FROM turns WHERE status='completed'")
            ]
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM feedback WHERE rating=-1 ORDER BY created_at DESC LIMIT 20"
                )
            ]
        return {
            "conversations": len(completed),
            "handoffs": sum(bool(v.get("ticket")) for v in completed),
            "answered": sum(v["status"] == "answered" for v in completed),
            "bad_cases": rows,
            "latency_ms_avg": round(sum(v["elapsed_ms"] for v in completed) / len(completed), 1)
            if completed
            else 0,
        }
