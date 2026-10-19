import json
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ASSETS, Settings
from .contracts import ChatRequest, KnowledgeInput, TicketUpdate
from .service import Service
from .storage import read_json, write_json


class SessionInput(BaseModel):
    pass


class FeedbackInput(BaseModel):
    session_id: str
    request_id: str
    rating: int
    note: str = Field(default="", max_length=2000)


def create_app(home=None):
    settings = Settings.load(home)
    service = Service(settings)
    app = FastAPI(
        title="ShopDesk AI", version="0.1.0", description="电商智能客服 · RAG、知识管理与人工转接"
    )
    app.state.service = service

    def customer(x_customer_id: str = Header(default="demo-customer")):
        return x_customer_id

    def admin(x_admin_token: str = Header(default="")):
        if not settings.admin_token or not secrets.compare_digest(
            x_admin_token, settings.admin_token
        ):
            raise HTTPException(401, "请输入有效的工作台管理口令")

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": settings.mode}

    @app.get("/api/bootstrap")
    def bootstrap():
        return {
            "name": "ShopDesk AI",
            "mode": settings.mode,
            "catalog": service.planner.catalog,
            "knowledge_count": len(service.store.knowledge(active_only=True)),
        }

    @app.post("/api/sessions")
    def session(who: str = Depends(customer)):
        try:
            return service.store.new_session(who)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/sessions")
    def sessions(who: str = Depends(customer)):
        return service.store.sessions(who)

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, who: str = Depends(customer)):
        try:
            return service.store.session(session_id, who)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/chat")
    def chat(request: ChatRequest, who: str = Depends(customer)):
        try:
            return service.chat(request, who)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/chat/stream")
    def stream(request: ChatRequest, who: str = Depends(customer)):
        try:
            service.store.session(request.session_id, who)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

        def events():
            try:
                for event in service.events(request, who):
                    yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            except Exception as exc:
                # Send actionable errors without credentials, request headers or tracebacks.
                yield (
                    "event: error\ndata: "
                    + json.dumps(
                        {
                            "message": str(exc)
                            if isinstance(exc, ValueError)
                            else "本次请求执行失败，请查看服务日志并使用新的请求 ID 重试。"
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/knowledge", dependencies=[Depends(admin)])
    def knowledge():
        return service.store.knowledge()

    @app.post("/api/knowledge", dependencies=[Depends(admin)])
    def add_knowledge(item: KnowledgeInput):
        try:
            with service.lock:
                key = service.store.put_knowledge(item)
            return {"id": key, "status": "saved", "index": "rebuilds_on_next_query"}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.put("/api/knowledge/{key}", dependencies=[Depends(admin)])
    def update_knowledge(key: str, item: KnowledgeInput):
        try:
            with service.lock:
                service.store.put_knowledge(item, key)
            return {"id": key, "status": "saved"}
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.delete("/api/knowledge/{key}", dependencies=[Depends(admin)])
    def delete_knowledge(key: str):
        try:
            with service.lock:
                service.store.delete_knowledge(key)
            return {"status": "deleted"}
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/knowledge/reindex", dependencies=[Depends(admin)])
    def reindex(strategy: str = "adaptive"):
        try:
            return service.index(strategy)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/tickets", dependencies=[Depends(admin)])
    def tickets():
        return service.store.tickets()

    @app.patch("/api/tickets/{key}", dependencies=[Depends(admin)])
    def update_ticket(key: str, update: TicketUpdate):
        try:
            return service.store.update_ticket(key, update)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/feedback")
    def feedback(item: FeedbackInput, who: str = Depends(customer)):
        try:
            service.store.session(item.session_id, who)
            service.store.feedback(item.session_id, item.request_id, item.rating, item.note)
            return {"status": "recorded"}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/metrics", dependencies=[Depends(admin)])
    def metrics():
        return service.store.metrics()

    @app.get("/api/benchmark", dependencies=[Depends(admin)])
    def benchmark():
        path = settings.runtime / "benchmark.json"
        return read_json(path) if path.exists() else {"status": "not_run"}

    @app.post("/api/benchmark", dependencies=[Depends(admin)])
    def run_benchmark():
        from .evaluation import evaluate

        value = evaluate()
        write_json(settings.runtime / "benchmark.json", value)
        return value

    app.mount("/static", StaticFiles(directory=ASSETS / "web"), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ASSETS / "web/index.html")

    return app
