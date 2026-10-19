"""Intent and contextual query rewriting share a typed contract across backends."""

import json
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage

from .config import ASSETS
from .contracts import QueryPlan


class Planner:
    def __init__(self, mode="local"):
        self.mode = mode
        self.catalog = json.loads((ASSETS / "data/catalog.json").read_text(encoding="utf8"))
        self._model = None

    def model(self):
        if self._model is None:
            from langchain_openai import ChatOpenAI

            if not os.getenv("OPENAI_API_KEY") or not os.getenv("CHAT_MODEL"):
                raise ValueError("LLM 模式需要 OPENAI_API_KEY 与 CHAT_MODEL")
            self._model = ChatOpenAI(
                model=os.environ["CHAT_MODEL"],
                api_key=os.environ["OPENAI_API_KEY"],
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                temperature=0,
                timeout=90,
                max_retries=2,
            )
        return self._model

    def identify_product(self, text):
        matches = [
            p for p in self.catalog if any(alias.lower() in text.lower() for alias in p["aliases"])
        ]
        return matches[0]["id"] if len(matches) == 1 else ""

    def local_plan(self, message, memory):
        product = self.identify_product(message)
        previous = memory.get("product_id", "")
        follows_topic = any(
            word in message
            for word in (
                "它",
                "这款",
                "这只",
                "那",
                "尺寸",
                "圈口",
                "直径",
                "重量",
                "厚度",
                "拆封",
                "退货",
                "运费",
                "价格",
                "多少钱",
                "清洁",
                "证书",
            )
        )
        if not product and previous and follows_topic:
            product = previous
        specialist = any(
            w in message
            for w in (
                "看实物",
                "看货",
                "自然光视频",
                "检查裂纹",
                "证书真假",
                "证书真伪",
                "鉴定真伪",
                "估价",
                "升值",
                "治病",
                "功效",
                "保值",
                "手腕",
                "手掌",
                "戴多大",
                "适合我",
                "有没有裂",
                "真翡翠",
                "是不是天然",
            )
        )
        if specialist:
            intent = "handoff"
        elif any(w in message for w in ("转人工", "人工客服", "真人客服", "人工处理", "找人工")):
            intent = "handoff"
        elif any(w in message for w in ("投诉", "气死", "太差", "欺骗", "严重不满", "垃圾")):
            intent = "complaint"
        elif any(w in message for w in ("退", "换货", "拆封", "售后", "退款", "质量问题")) or (
            "运费" in message and memory.get("intent") == "returns"
        ):
            intent = "returns"
        elif any(
            w in message for w in ("物流", "发货", "配送", "快递", "送达", "多久到", "订单", "运费")
        ):
            intent = "shipping"
        elif message.strip("！!。,.， ") in ("你好", "您好", "谢谢", "好的", "hi", "hello"):
            intent = "smalltalk"
        elif product or any(
            w in message
            for w in (
                "翡翠",
                "圈口",
                "尺寸",
                "厚度",
                "重量",
                "直径",
                "保养",
                "清洁",
                "证书",
                "价格",
                "多少钱",
                "支持",
                "怎么用",
                "发票",
                "优惠",
            )
        ):
            intent = "product"
        else:
            intent = "unknown"
        # General invoices and promotions do not require a product slot.
        needs = (
            intent == "product"
            and not product
            and not any(w in message for w in ("发票", "优惠", "保养", "清洁", "证书"))
        )
        if (
            not product
            and any(w in message for w in ("它", "这款", "这个"))
            and intent not in ("handoff", "complaint")
        ):
            needs = True
        name = next((p["name"] for p in self.catalog if p["id"] == product), "")
        query = (name + " " + message).strip()
        if intent == "returns":
            query += " 退换货售后"
        order = re.search(r"ORD-\d+", message, re.I)
        return QueryPlan(
            intent=intent,
            rewritten_query=query,
            product_id=product,
            needs_clarification=needs,
            handoff_reason="需要人工核对该件实物、证书或交易诉求" if specialist else "",
        ), order.group(0).upper() if order else memory.get("order_id", "")

    def plan(self, message, memory, history):
        local, order = self.local_plan(message, memory)
        if self.mode == "local" or local.intent in ("handoff", "complaint"):
            return local, order
        prompt = (ASSETS / "prompts/rewrite.md").read_text(encoding="utf8")
        result = (
            self.model()
            .with_structured_output(
                QueryPlan, method=os.getenv("STRUCTURED_METHOD", "function_calling")
            )
            .invoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(
                        content=json.dumps(
                            {
                                "message": message,
                                "memory": memory,
                                "history": history[-8:],
                                "catalog": self.catalog,
                            },
                            ensure_ascii=False,
                        )
                    ),
                ]
            )
        )
        if result.product_id and result.product_id not in {p["id"] for p in self.catalog}:
            raise ValueError("改写返回未知商品 ID")
        if local.intent == "shipping" and order:
            result.intent = "shipping"
        return result, order
