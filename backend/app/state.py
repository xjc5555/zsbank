from typing import List, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage


Intent = Literal["记账", "心愿规划", "高危咨询", "日常闲聊", "理财问答", "理财测评"]

# 风险偏好等级
RiskLevel = Literal["保守型", "稳健型", "积极型", ""]


class WishlistItem(TypedDict):
    id: str
    name: str
    target_amount: float
    saved_amount: float
    months: int


class ExpenseItem(TypedDict):
    amount: float
    category: str
    note: str


class FinanceProfile(TypedDict):
    """用户理财画像（测评结果）"""
    risk_level: str          # 保守型 / 稳健型 / 积极型
    monthly_income: float    # 月均可支配收入（元）
    has_emergency_fund: bool # 是否有应急储蓄
    suggestion: str          # 个性化建议摘要
    completed: bool          # 测评是否已完成
    step: int                # 当前测评进度（0=未开始，1~3=进行中）


class FinBuddyState(TypedDict):
    messages: List[BaseMessage]
    intent: Intent
    budget_total: float
    budget_left: float
    wishlists: List[WishlistItem]
    # 当前操作的心愿索引（-1 表示未选中）
    active_wishlist_index: int
    expense_records: List[ExpenseItem]
    risk_flag: bool
    finance_profile: FinanceProfile


def _default_profile() -> FinanceProfile:
    return FinanceProfile(
        risk_level="",
        monthly_income=0.0,
        has_emergency_fund=False,
        suggestion="",
        completed=False,
        step=0,
    )


def build_initial_state(
    messages: List[BaseMessage],
    budget_total: float = 1500.0,
    budget_left: Optional[float] = None,
    wishlists: Optional[List[WishlistItem]] = None,
    active_wishlist_index: int = 0,
    expense_records: Optional[List[ExpenseItem]] = None,
    finance_profile: Optional[FinanceProfile] = None,
) -> FinBuddyState:
    if budget_left is None:
        budget_left = budget_total
    return {
        "messages": messages,
        "intent": "日常闲聊",
        "budget_total": budget_total,
        "budget_left": budget_left,
        "wishlists": wishlists or [],
        "active_wishlist_index": active_wishlist_index,
        "expense_records": expense_records or [],
        "risk_flag": False,
        "finance_profile": finance_profile or _default_profile(),
    }
