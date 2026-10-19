import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from .config import Settings
from .contracts import ChatRequest
from .service import Service
from .storage import write_json


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf8")
    p = argparse.ArgumentParser(prog="shopdesk", description="ShopDesk 电商智能客服")
    p.add_argument("--home")
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--strategy", choices=["adaptive", "window"], default="adaptive")
    demo = commands.add_parser("demo")
    demo.add_argument("--message", default="清圆 J01 平安扣的尺寸和重量是多少？")
    demo.add_argument("--session")
    ev = commands.add_parser("evaluate")
    ev.add_argument("--report", type=Path, default=Path("outputs/benchmark.json"))
    args = p.parse_args(argv)
    try:
        settings = Settings.load(args.home)
        if args.command == "serve":
            import uvicorn

            from .api import create_app

            uvicorn.run(create_app(settings.home), host="127.0.0.1", port=8010)
            return 0
        if args.command == "evaluate":
            from .evaluation import evaluate

            value = evaluate()
            write_json(args.report, value)
        else:
            service = Service(settings)
            if args.command == "ingest":
                value = service.index(args.strategy)
            else:
                session = args.session or service.store.new_session("demo-customer")["id"]
                value = service.chat(
                    ChatRequest(
                        session_id=session, request_id=uuid4().hex[:12], message=args.message
                    )
                )
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
