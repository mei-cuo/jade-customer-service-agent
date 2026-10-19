"""Read-only order tool, scoped to the customer owning the session."""

import json

from langchain_core.tools import tool

from .config import ASSETS


def order_tool(customer_id):
    @tool
    def lookup_order(order_id: str) -> dict:
        """查询当前客户名下演示订单的状态，不返回其他客户的信息。"""
        rows = json.loads((ASSETS / "data/orders.json").read_text(encoding="utf8"))
        order = next(
            (o for o in rows if o["id"] == order_id and o["customer_id"] == customer_id), None
        )
        if not order:
            return {
                "found": False,
                "message": "未找到当前账号可查询的订单，请确认订单号或转人工核查。",
            }
        return {
            "found": True,
            "order_id": order["id"],
            "status": order["status"],
            "delivery": order["delivery"],
            "source": "demo_order_repository",
        }

    return lookup_order
