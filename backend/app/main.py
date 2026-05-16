import os
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field

from app.graph import finbuddy_graph
from app.llm import is_llm_configured
from app.state import ExpenseItem, FinanceProfile, WishlistItem, _default_profile, build_initial_state


load_dotenv()

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

app = FastAPI(
    title="FinBuddy Backend",
    description="财搭子 LangGraph 核心智能体工作流",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────── 请求 / 响应模型 ───────────────────

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class WishlistItemModel(BaseModel):
    id: str = ""
    name: str = "我的心愿"
    target_amount: float = Field(default=0.0, ge=0)
    saved_amount: float = Field(default=0.0, ge=0)
    months: int = Field(default=12, ge=1)


class ExpenseItemModel(BaseModel):
    amount: float = Field(ge=0)
    category: str = "日常消费"
    note: str = ""


class FinanceProfileModel(BaseModel):
    risk_level: str = ""
    monthly_income: float = 0.0
    has_emergency_fund: bool = False
    suggestion: str = ""
    completed: bool = False
    step: int = 0


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, description="用户本轮输入")
    history: List[ChatMessage] = Field(default_factory=list, description="前端传入的历史消息")
    budget_total: float = Field(default=1500.0, ge=0, description="月度总预算")
    budget_left: float = Field(default=1500.0, ge=0, description="本月剩余预算")
    wishlists: List[WishlistItemModel] = Field(default_factory=list, description="心愿列表")
    active_wishlist_index: int = Field(default=0, ge=0, description="当前操作的心愿索引")
    expense_records: List[ExpenseItemModel] = Field(default_factory=list, description="消费记录")
    finance_profile: Optional[FinanceProfileModel] = Field(default=None, description="理财测评画像")


class ChatResponse(BaseModel):
    reply: str
    intent: str
    risk_flag: bool
    budget_total: float
    budget_left: float
    wishlists: List[WishlistItemModel]
    active_wishlist_index: int
    expense_records: List[ExpenseItemModel]
    finance_profile: FinanceProfileModel
    messages: List[ChatMessage]
    llm_api_key_configured: bool


# ─────────────────── 消息转换 ───────────────────

def _to_langchain_messages(history: List[ChatMessage], message: str) -> List[BaseMessage]:
    messages: List[BaseMessage] = []
    for item in history:
        if item.role == "user":
            messages.append(HumanMessage(content=item.content))
        else:
            messages.append(AIMessage(content=item.content))
    messages.append(HumanMessage(content=message))
    return messages


def _to_response_messages(messages: List[BaseMessage]) -> List[ChatMessage]:
    result: List[ChatMessage] = []
    for message in messages:
        role: Optional[Literal["user", "assistant"]] = None
        if message.type == "human":
            role = "user"
        elif message.type == "ai":
            role = "assistant"
        if role:
            content = message.content if isinstance(message.content, str) else str(message.content)
            result.append(ChatMessage(role=role, content=content))
    return result


def _wishlists_to_state(items: List[WishlistItemModel]) -> List[WishlistItem]:
    return [
        WishlistItem(
            id=item.id,
            name=item.name,
            target_amount=item.target_amount,
            saved_amount=item.saved_amount,
            months=item.months,
        )
        for item in items
    ]


def _expenses_to_state(items: List[ExpenseItemModel]) -> List[ExpenseItem]:
    return [
        ExpenseItem(amount=item.amount, category=item.category, note=item.note)
        for item in items
    ]


def _profile_to_state(model: Optional[FinanceProfileModel]) -> FinanceProfile:
    if model is None:
        return _default_profile()
    return FinanceProfile(
        risk_level=model.risk_level,
        monthly_income=model.monthly_income,
        has_emergency_fund=model.has_emergency_fund,
        suggestion=model.suggestion,
        completed=model.completed,
        step=model.step,
    )


def _profile_from_state(raw: Optional[Dict[str, Any]]) -> FinanceProfileModel:
    if not raw:
        return FinanceProfileModel()
    return FinanceProfileModel(
        risk_level=raw.get("risk_level", ""),
        monthly_income=raw.get("monthly_income", 0.0),
        has_emergency_fund=raw.get("has_emergency_fund", False),
        suggestion=raw.get("suggestion", ""),
        completed=raw.get("completed", False),
        step=raw.get("step", 0),
    )


# ─────────────────── 路由 ───────────────────

@app.get("/health")
def health_check() -> dict:
    return {"status": "ok", "service": "finbuddy", "version": "0.3.0"}


@app.post("/reset")
def reset_session() -> dict:
    """清空会话——由于后端无状态，此接口仅做确认回执，前端拿到响应后再清本地数据。"""
    return {"status": "ok", "message": "session reset"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    state = build_initial_state(
        messages=_to_langchain_messages(request.history, request.message),
        budget_total=request.budget_total,
        budget_left=request.budget_left,
        wishlists=_wishlists_to_state(request.wishlists),
        active_wishlist_index=request.active_wishlist_index,
        expense_records=_expenses_to_state(request.expense_records),
        finance_profile=_profile_to_state(request.finance_profile),
    )
    result = finbuddy_graph.invoke(state)
    response_messages = _to_response_messages(result["messages"])
    reply = response_messages[-1].content if response_messages else ""

    wishlists_out = [
        WishlistItemModel(
            id=w["id"],
            name=w["name"],
            target_amount=w["target_amount"],
            saved_amount=w["saved_amount"],
            months=w["months"],
        )
        for w in result.get("wishlists", [])
    ]
    expenses_out = [
        ExpenseItemModel(amount=e["amount"], category=e["category"], note=e["note"])
        for e in result.get("expense_records", [])
    ]

    return ChatResponse(
        reply=reply,
        intent=result["intent"],
        risk_flag=result["risk_flag"],
        budget_total=result["budget_total"],
        budget_left=result["budget_left"],
        wishlists=wishlists_out,
        active_wishlist_index=result.get("active_wishlist_index", 0),
        expense_records=expenses_out,
        finance_profile=_profile_from_state(result.get("finance_profile")),
        messages=response_messages,
        llm_api_key_configured=is_llm_configured(),
    )
