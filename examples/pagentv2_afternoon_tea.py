"""下午茶外卖平台仿真 — 多工具、多轮 ``arun()``。

模拟「茶哩茶哩」类平台：查店、搜菜、看库存、加购、优惠券、配送时段、下单。
全程内存仿真，不调真实外卖 API；模型通过工具完成订下午茶任务。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv2_afternoon_tea

    # 自定义需求（一句话）:
    PAGENTV2_TEA_PROMPT="..." uv run python -m examples.pagentv2_afternoon_tea
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass, field

from pagentv2 import (
    Agent,
    DeepSeek,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnResult,
    tool,
)

CYAN = "\033[36m"
DIM = "\033[90m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
RESET = "\033[0m"
YELLOW = "\033[33m"

DEFAULT_PROMPT = (
    "我们在厦门软件园二期开会，团队 6 人，下午 3 点左右想订下午茶外卖。"
    "人均预算 40 元以内，要奶茶和至少一份点心拼盘，且至少 2 杯热饮。"
    "请：1) 在附近找合适店铺并说明理由；2) 选好商品加购；"
    "3) 尽量用优惠券；4) 选 15:00–15:30 能送达的时段；5) 提交订单。"
    "最后用一段话汇总：店名、点了什么、实付金额、预计送达时间、订单号。"
)

SHOPS = {
    "miss_tea": {
        "name": "茶小姐·现制茶饮",
        "area": "软件园二期",
        "rating": 4.8,
        "eta_min": 25,
        "delivery_fee": 3.0,
        "min_order": 20.0,
        "tags": ["奶茶", "果茶", "热饮多"],
    },
    "bake_lab": {
        "name": "焙实验室",
        "area": "软件园二期",
        "rating": 4.6,
        "eta_min": 35,
        "delivery_fee": 5.0,
        "min_order": 35.0,
        "tags": ["烘焙", "咖啡", "三明治"],
    },
    "yuanqi": {
        "name": "元气下午茶",
        "area": "观日路",
        "rating": 4.7,
        "eta_min": 30,
        "delivery_fee": 4.0,
        "min_order": 25.0,
        "tags": ["套餐", "奶茶", "点心拼盘"],
    },
}

MENU: dict[str, list[dict]] = {
    "miss_tea": [
        {
            "id": "mt_oolong",
            "name": "鸭屎香奶茶",
            "price": 18.0,
            "hot": True,
            "stock": 50,
        },
        {
            "id": "mt_jasmine",
            "name": "茉莉奶绿",
            "price": 16.0,
            "hot": True,
            "stock": 40,
        },
        {
            "id": "mt_lemon",
            "name": "手打柠檬茶",
            "price": 15.0,
            "hot": False,
            "stock": 30,
        },
        {
            "id": "mt_cheese",
            "name": "芝士葡萄",
            "price": 22.0,
            "hot": False,
            "stock": 0,
        },
    ],
    "bake_lab": [
        {"id": "bl_latte", "name": "拿铁", "price": 22.0, "hot": True, "stock": 20},
        {
            "id": "bl_croissant",
            "name": "黄油可颂",
            "price": 12.0,
            "hot": False,
            "stock": 15,
        },
        {
            "id": "bl_tiramisu",
            "name": "提拉米苏杯",
            "price": 26.0,
            "hot": False,
            "stock": 8,
        },
    ],
    "yuanqi": [
        {
            "id": "yq_combo_a",
            "name": "双人下午茶套餐A",
            "price": 68.0,
            "hot": False,
            "stock": 12,
        },
        {"id": "yq_milk", "name": "厚乳红茶", "price": 19.0, "hot": True, "stock": 35},
        {"id": "yq_taro", "name": "芋泥波波", "price": 21.0, "hot": True, "stock": 28},
        {
            "id": "yq_platter",
            "name": "点心拼盘(6人份)",
            "price": 48.0,
            "hot": False,
            "stock": 6,
        },
        {
            "id": "yq_mango",
            "name": "芒果冰沙",
            "price": 20.0,
            "hot": False,
            "stock": 18,
        },
    ],
}

COUPONS = {
    "TEA30": {"desc": "满80减30", "min_subtotal": 80.0, "discount": 30.0},
    "HOTDRINK8": {
        "desc": "含热饮订单减8元",
        "min_subtotal": 50.0,
        "discount": 8.0,
        "need_hot": True,
    },
    "NEW15": {"desc": "新客满60减15", "min_subtotal": 60.0, "discount": 15.0},
}

DELIVERY_SLOTS = [
    {"id": "s1", "label": "14:45–15:15", "available": True},
    {"id": "s2", "label": "15:00–15:30", "available": True},
    {"id": "s3", "label": "15:15–15:45", "available": True},
    {"id": "s4", "label": "15:30–16:00", "available": False},
]


@dataclass
class CartLine:
    shop_id: str
    item_id: str
    name: str
    unit_price: float
    quantity: int
    specs: str
    hot: bool


@dataclass
class Platform:
    cart: list[CartLine] = field(default_factory=list)
    coupon: str | None = None
    orders: dict[str, dict] = field(default_factory=dict)

    def find_item(self, shop_id: str, item_id: str) -> dict | None:
        for item in MENU.get(shop_id, []):
            if item["id"] == item_id:
                return item
        return None

    def cart_shop_id(self) -> str | None:
        if not self.cart:
            return None
        shops = {line.shop_id for line in self.cart}
        if len(shops) > 1:
            return "mixed"
        return next(iter(shops))

    def subtotal(self) -> float:
        return sum(line.unit_price * line.quantity for line in self.cart)

    def has_hot_drink(self) -> bool:
        return any(line.hot for line in self.cart)

    def discount(self) -> float:
        if not self.coupon:
            return 0.0
        rule = COUPONS.get(self.coupon)
        if rule is None:
            return 0.0
        sub = self.subtotal()
        if sub < rule["min_subtotal"]:
            return 0.0
        if rule.get("need_hot") and not self.has_hot_drink():
            return 0.0
        return rule["discount"]

    def delivery_fee(self) -> float:
        shop_id = self.cart_shop_id()
        if shop_id in (None, "mixed"):
            return 0.0
        return SHOPS[shop_id]["delivery_fee"]

    def total(self) -> float:
        return max(0.0, self.subtotal() - self.discount() + self.delivery_fee())


platform = Platform()


def fmt(data) -> str:
    return json.dumps(data, ensure_ascii=False)


@tool()
def list_nearby_shops(area: str) -> str:
    """List tea / snack shops near an area.

    Args:
        area: Area name, e.g. 软件园二期 or 观日路.
    """
    hits = []
    for shop_id, shop in SHOPS.items():
        if area in shop["area"] or shop["area"] in area:
            hits.append(
                {
                    "shop_id": shop_id,
                    "name": shop["name"],
                    "rating": shop["rating"],
                    "eta_min": shop["eta_min"],
                    "delivery_fee": shop["delivery_fee"],
                    "min_order": shop["min_order"],
                    "tags": shop["tags"],
                }
            )
    if not hits:
        return fmt(
            {
                "error": f"no shops in {area!r}",
                "known_areas": [s["area"] for s in SHOPS.values()],
            }
        )
    return fmt({"area": area, "shops": hits})


@tool()
def get_menu(shop_id: str) -> str:
    """Get full menu for a shop.

    Args:
        shop_id: Shop id from list_nearby_shops, e.g. yuanqi.
    """
    shop = SHOPS.get(shop_id)
    if shop is None:
        return fmt({"error": f"unknown shop_id {shop_id!r}", "shop_ids": list(SHOPS)})
    items = []
    for item in MENU.get(shop_id, []):
        items.append(
            {
                "item_id": item["id"],
                "name": item["name"],
                "price": item["price"],
                "hot_drink": item["hot"],
                "in_stock": item["stock"] > 0,
                "stock": item["stock"],
            }
        )
    return fmt({"shop_id": shop_id, "shop_name": shop["name"], "items": items})


@tool()
def check_stock(shop_id: str, item_id: str) -> str:
    """Check real-time stock for one menu item.

    Args:
        shop_id: Shop id.
        item_id: Menu item id.
    """
    item = platform.find_item(shop_id, item_id)
    if item is None:
        return fmt({"error": f"item {item_id!r} not in shop {shop_id!r}"})
    return fmt(
        {
            "shop_id": shop_id,
            "item_id": item_id,
            "name": item["name"],
            "stock": item["stock"],
            "available": item["stock"] > 0,
        }
    )


@tool()
def add_to_cart(shop_id: str, item_id: str, quantity: int, specs: str = "") -> str:
    """Add a menu item to cart. Cart must be from a single shop.

    Args:
        shop_id: Shop id.
        item_id: Menu item id.
        quantity: Count, at least 1.
        specs: Sugar/ice notes, e.g. 少糖去冰 or 热饮正常糖.
    """
    if quantity < 1:
        return fmt({"error": "quantity must be >= 1"})

    current = platform.cart_shop_id()
    if current == "mixed":
        return fmt({"error": "cart has mixed shops; clear cart first"})
    if current and current != shop_id:
        return fmt(
            {
                "error": f"cart already has items from {current!r}; clear before switching shop",
                "hint": "call clear_cart or keep same shop_id",
            }
        )

    item = platform.find_item(shop_id, item_id)
    if item is None:
        return fmt({"error": f"unknown item {item_id!r} for shop {shop_id!r}"})
    if item["stock"] < quantity:
        return fmt(
            {
                "error": "insufficient stock",
                "name": item["name"],
                "stock": item["stock"],
                "requested": quantity,
            }
        )

    item["stock"] -= quantity
    platform.cart.append(
        CartLine(
            shop_id=shop_id,
            item_id=item_id,
            name=item["name"],
            unit_price=item["price"],
            quantity=quantity,
            specs=specs,
            hot=item["hot"],
        )
    )
    return fmt(
        {"ok": True, "cart_lines": len(platform.cart), "subtotal": platform.subtotal()}
    )


@tool()
def view_cart() -> str:
    """Show current cart, coupon, fees and estimated total."""
    lines = [
        {
            "name": line.name,
            "quantity": line.quantity,
            "unit_price": line.unit_price,
            "specs": line.specs,
            "hot_drink": line.hot,
        }
        for line in platform.cart
    ]
    shop_id = platform.cart_shop_id()
    shop_name = SHOPS[shop_id]["name"] if shop_id not in (None, "mixed") else shop_id
    return fmt(
        {
            "shop": shop_name,
            "lines": lines,
            "subtotal": platform.subtotal(),
            "coupon": platform.coupon,
            "discount": platform.discount(),
            "delivery_fee": platform.delivery_fee(),
            "total": platform.total(),
            "meets_min_order": platform.subtotal() >= SHOPS[shop_id]["min_order"]
            if shop_id not in (None, "mixed")
            else False,
        }
    )


@tool()
def list_coupons() -> str:
    """List available coupon codes and rules."""
    return fmt({"coupons": COUPONS})


@tool()
def apply_coupon(code: str) -> str:
    """Apply a coupon code to the current cart.

    Args:
        code: Coupon code, e.g. TEA30 or HOTDRINK8.
    """
    rule = COUPONS.get(code.upper())
    if rule is None:
        return fmt({"error": f"unknown coupon {code!r}", "valid": list(COUPONS)})
    platform.coupon = code.upper()
    return fmt(
        {
            "applied": code.upper(),
            "desc": rule["desc"],
            "discount_if_eligible": platform.discount(),
            "subtotal": platform.subtotal(),
            "total_after": platform.total(),
        }
    )


@tool()
def list_delivery_slots() -> str:
    """List delivery time windows for the current order."""
    return fmt(
        {
            "slots": DELIVERY_SLOTS,
            "shop_eta_min": SHOPS.get(platform.cart_shop_id() or "", {}).get("eta_min"),
        }
    )


@tool()
def clear_cart() -> str:
    """Remove all cart lines and release reserved stock."""
    for line in platform.cart:
        item = platform.find_item(line.shop_id, line.item_id)
        if item:
            item["stock"] += line.quantity
    platform.cart.clear()
    platform.coupon = None
    return fmt({"ok": True, "message": "cart cleared"})


@tool()
def submit_order(
    delivery_slot_id: str, address: str, contact: str, remark: str = ""
) -> str:
    """Place order from current cart.

    Args:
        delivery_slot_id: Slot id from list_delivery_slots, e.g. s2.
        address: Delivery address.
        contact: Phone or name for rider.
        remark: Optional note for shop.
    """
    if not platform.cart:
        return fmt({"error": "cart is empty"})
    shop_id = platform.cart_shop_id()
    if shop_id in (None, "mixed"):
        return fmt({"error": "invalid cart state"})

    shop = SHOPS[shop_id]
    if platform.subtotal() < shop["min_order"]:
        return fmt(
            {
                "error": "below min_order",
                "min_order": shop["min_order"],
                "subtotal": platform.subtotal(),
            }
        )

    slot = next((s for s in DELIVERY_SLOTS if s["id"] == delivery_slot_id), None)
    if slot is None:
        return fmt({"error": f"unknown slot {delivery_slot_id!r}"})
    if not slot["available"]:
        return fmt({"error": f"slot {delivery_slot_id!r} not available"})

    order_id = "TEA-" + uuid.uuid4().hex[:8].upper()
    order = {
        "order_id": order_id,
        "shop": shop["name"],
        "items": [line.name for line in platform.cart],
        "subtotal": platform.subtotal(),
        "discount": platform.discount(),
        "delivery_fee": platform.delivery_fee(),
        "paid": platform.total(),
        "delivery_slot": slot["label"],
        "address": address,
        "contact": contact,
        "remark": remark,
        "status": "confirmed",
        "rider": "骑手小陈",
        "eta_note": f"预计 {shop['eta_min']} 分钟内出餐，{slot['label']} 送达",
    }
    platform.orders[order_id] = order
    platform.cart.clear()
    platform.coupon = None
    return fmt(order)


@tool()
def get_order(order_id: str) -> str:
    """Get order status by order id.

    Args:
        order_id: Order id returned by submit_order.
    """
    order = platform.orders.get(order_id)
    if order is None:
        return fmt({"error": f"order {order_id!r} not found"})
    return fmt(order)


SYSTEM = """你是「茶哩茶哩」外卖平台的订餐助手，只能通过工具操作平台。

规则：
- 先查店、看菜单和库存，再加购；加购前确认库存足够。
- 购物车只能来自同一家店；换店需先 clear_cart。
- 下单前用 view_cart 核对金额、起送价、优惠券是否生效。
- 选配送时段前调用 list_delivery_slots；不可选 available=false 的时段。
- 信息不足时做合理假设并在最终回复里说明。
- 步骤尽量完整，但不要编造工具没返回过的价格或订单号。"""

TOOLS = [
    list_nearby_shops,
    get_menu,
    check_stock,
    add_to_cart,
    view_cart,
    list_coupons,
    apply_coupon,
    list_delivery_slots,
    clear_cart,
    submit_order,
    get_order,
]


def use_color() -> bool:
    return sys.stdout.isatty()


async def stream_run(agent: Agent, prompt: str) -> None:
    color = use_color()
    answer: list[str] = []
    turns = 0
    tool_calls = 0

    print(f"{MAGENTA if color else ''}用户：{prompt}{RESET if color else ''}\n")

    async for event in agent.arun(prompt, reasoning_effort="medium"):
        if isinstance(event, ToolCallBegin):
            tool_calls += 1
            line = f"→ {event.name}({event.arguments})"
            print(f"{CYAN}{line}{RESET}" if color else line)

        elif isinstance(event, ToolResult):
            body = event.content.replace("\n", " ")
            if len(body) > 120:
                body = body[:119] + "…"
            tone = GREEN if event.ok else YELLOW
            print(
                f"  {tone if color else ''}{'✓' if event.ok else '✗'} {body}{RESET if color else ''}"
            )

        elif isinstance(event, TextDelta):
            sys.stdout.write(event.text)
            sys.stdout.flush()
            answer.append(event.text)

        elif isinstance(event, TurnResult):
            turns += 1
            mark = (
                f"\n{DIM}── 第 {turns} 轮 LLM 结束 ──{RESET}"
                if color
                else f"\n── 第 {turns} 轮 LLM 结束 ──"
            )
            print(mark)

    print(
        f"\n{DIM if color else ''}"
        f"统计：{turns} 轮模型调用，{tool_calls} 次工具，会话 {len(agent.messages)} 条消息"
        f"{RESET if color else ''}"
    )


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请设置 DEEPSEEK_API_KEY: export DEEPSEEK_API_KEY='your-key'")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    prompt = os.getenv("PAGENTV2_TEA_PROMPT", DEFAULT_PROMPT)
    agent = Agent(
        DeepSeek("deepseek-v4-flash"),
        system=SYSTEM,
        tools=TOOLS,
        max_turns=16,
    )

    await stream_run(agent, prompt)

    if platform.orders:
        print(
            f"\n{MAGENTA if use_color() else ''}平台订单快照：{RESET if use_color() else ''}"
        )
        for oid, order in platform.orders.items():
            print(
                f"  {oid}: ¥{order['paid']:.0f} · {order['shop']} · {order['delivery_slot']}"
            )


if __name__ == "__main__":
    asyncio.run(main())
