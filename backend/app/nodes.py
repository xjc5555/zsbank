import re
import uuid
from dataclasses import dataclass
from math import ceil
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.llm import generate_finbuddy_reply, get_deepseek_llm
from app.state import ExpenseItem, FinanceProfile, FinBuddyState, Intent, WishlistItem, _default_profile


HIGH_RISK_KEYWORDS = ("兼职刷单", "校园贷", "高收益", "刷流水", "套现", "裸贷", "返利", "稳赚")
BOOKKEEPING_KEYWORDS = ("花了", "消费", "买了", "支出", "记账", "付款", "吃饭", "奶茶", "打车")
WISHLIST_KEYWORDS = ("心愿", "攒钱", "计划", "目标", "买电脑", "换电脑", "旅行", "存钱", "攒够")
SAVINGS_DEPOSIT_KEYWORDS = ("存入", "攒了", "往里存", "多攒", "储蓄到账", "本月存入", "今天攒")
BUDGET_SET_KEYWORDS = ("设置预算", "预算改为", "月预算", "生活费是", "每月预算", "预算设为", "设定预算")
FINANCE_QA_KEYWORDS = (
    # 通用问答触发词
    "是什么", "怎么用", "什么是", "怎么理财", "利率", "风险等级", "怎么开户",
    # 储蓄/低风险工具
    "货币基金", "定期存款", "余额宝", "国债", "活期", "零钱通", "理财通",
    "国债逆回购", "银行理财", "大额存单", "存款",
    # 投资工具（科普向）
    "基金", "指数基金", "ETF", "股票", "保险", "理财产品",
    # 大学生高频消费金融词
    "花呗", "白条", "分期", "信用卡", "借呗", "网贷", "消费贷",
    "还款", "账单", "免息期", "最低还款", "循环利息", "征信", "信用分",
    # 场景词
    "奖学金理财", "压岁钱", "兼职收入", "生活费理财", "应急储蓄",
)

FINANCE_PROFILE_KEYWORDS = (
    "理财测评", "测一测", "风险测评", "适合我", "我该怎么理财", "给我个建议",
    "我的理财画像", "帮我分析", "理财规划", "入门理财",
)

# ── 大学生理财工具知识卡片（注入 FinanceQANode prompt 上下文）──
_FINANCE_KNOWLEDGE_CARD = """
【大学生常用理财工具对比参考（供科普使用）】

① 货币基金（余额宝/零钱通等）
  - 风险等级：R1（最低风险）
  - 流动性：T+0 或 T+1，随存随取
  - 年化收益：约 1.5%~2.5%（随市场波动）
  - 适合场景：存放日常备用金、心愿储蓄隔离
  - 注意：收益不保证，但历史极少亏损

② 定期存款（银行3/6/12个月期）
  - 风险等级：R1，本金有存款保险保障（50万以内）
  - 流动性：提前取出按活期计息
  - 年化收益：约 1.5%~2.5%（国有行），部分城商行更高
  - 适合场景：有固定不动用的资金，确定几个月不用

③ 国债逆回购（交易所1~182天）
  - 风险等级：R1，实质等同于借钱给国家
  - 流动性：到期自动归还，期间不可提前
  - 收益：年化偶有脉冲（节前可达3%~5%），平时1%~2%
  - 适合场景：节假日前短期闲置资金，须有证券账户

④ 花呗/白条等消费分期
  - 本质：短期消费贷款，免息期内不收利息
  - 风险：按最低还款额还款会产生循环利息（日息约0.05%，折合年化≈18%）
  - 建议：账单日全额还款，避免分期手续费，保持良好征信

⑤ 信用卡
  - 免息期：通常20~56天
  - 征信影响：逾期记录会影响未来贷款/房贷
  - 建议：额度控制在月收入1倍以内，全额还款
""".strip()


# ─────────────────── Pydantic 模型 ───────────────────

class ExpenseRecord(BaseModel):
    amount: float = Field(ge=0, description="本次支出金额")
    category: str = Field(default="日常消费", description="消费分类")


class WishlistPlan(BaseModel):
    target_amount: float = Field(ge=0, description="心愿目标金额")
    saved_amount: float = Field(ge=0, description="已储蓄金额")
    months: int = Field(ge=1, description="计划达成月份数")
    monthly_saving: float = Field(ge=0, description="每月建议储蓄金额")


# ─────────────────── 工具函数 ───────────────────

def _latest_text(state: FinBuddyState) -> str:
    if not state["messages"]:
        return ""
    content = state["messages"][-1].content
    return content if isinstance(content, str) else str(content)


def _append_reply(state: FinBuddyState, text: str) -> list:
    return [*state["messages"], AIMessage(content=text)]


def _extract_amount(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|rmb|RMB)?", text)
    return float(match.group(1)) if match else None


def _is_savings_deposit(text: str) -> bool:
    return any(keyword in text for keyword in SAVINGS_DEPOSIT_KEYWORDS)


def _amounts_with_currency(text: str) -> list[float]:
    return [float(m.group(1)) for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:元|块)", text)]


def _extract_deposit_amount(text: str) -> Optional[float]:
    if not _is_savings_deposit(text):
        return None
    match = re.search(r"(?:本月\s*)?存入\s*(\d+(?:\.\d+)?)\s*(?:元|块)?", text)
    if match:
        return float(match.group(1))
    match = re.search(r"攒了\s*(\d+(?:\.\d+)?)\s*(?:元|块)?", text)
    if match:
        return float(match.group(1))
    amounts = _amounts_with_currency(text)
    if len(amounts) == 1:
        return amounts[0]
    return _extract_amount(text)


def _extract_months(text: str) -> int:
    month_match = re.search(r"(\d+)\s*(?:个月|月)", text)
    if month_match:
        return max(1, int(month_match.group(1)))
    year_match = re.search(r"(\d+)\s*(?:年)", text)
    if year_match:
        return max(1, int(year_match.group(1)) * 12)
    return 12


def _classify_category(text: str) -> str:
    category_keywords = {
        "餐饮": ("饭", "外卖", "奶茶", "咖啡", "食堂", "火锅", "饮料", "零食", "烧烤"),
        "交通": ("打车", "地铁", "公交", "高铁", "机票", "滴滴", "出行"),
        "学习": ("书", "课程", "资料", "文具", "考试", "教材", "网课"),
        "数码": ("电脑", "耳机", "手机", "键盘", "鼠标", "充电", "数据线"),
        "娱乐": ("电影", "游戏", "演唱会", "会员", "ktv", "KTV", "密室"),
        "购物": ("衣服", "鞋", "包", "化妆品", "淘宝", "京东", "拼多多"),
        "医疗": ("药", "医院", "门诊", "体检"),
    }
    for category, keywords in category_keywords.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "日常消费"


def _extract_wishlist_name(text: str) -> str:
    """从用户文本中提取心愿名称"""
    patterns = [
        r"(?:攒钱|存钱|攒够|心愿)\s*(?:买|换|去)?\s*(.{2,10}?)(?:的钱|目标|计划|$)",
        r"(?:买|换|去)\s*(.{2,10}?)(?:\s*\d|，|,|$)",
        r"目标\s*(?:是)?\s*(.{2,10}?)(?:\s*\d|，|,|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            name = m.group(1).strip()
            if 1 < len(name) <= 10:
                return name
    # 兜底：取关键词
    if "电脑" in text:
        return "换电脑"
    if "旅行" in text or "旅游" in text:
        return "旅行基金"
    if "手机" in text:
        return "换手机"
    return "我的心愿"


def _extract_budget_amount(text: str) -> Optional[float]:
    """从设置预算的语句中提取金额"""
    match = re.search(
        r"(?:预算|生活费)[^0-9]*(\d+(?:\.\d+)?)\s*(?:元|块)?",
        text,
    )
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块)", text)
    if match:
        return float(match.group(1))
    return None


def _budget_warning(budget_left: float, budget_total: float) -> str:
    """根据预算剩余生成预警提示"""
    if budget_total <= 0:
        return ""
    ratio = budget_left / budget_total
    if budget_left <= 0:
        return "\n\n⚠️ 本月日常预算已用完，剩余消费建议先借助心愿储蓄以外的备用金，别动攒钱的钱哦。"
    if budget_left <= 100:
        return f"\n\n⚠️ 本月预算只剩 {budget_left:.0f} 元，快撑到月底了，接下来以\"够用就好\"为准则。"
    if budget_left <= 300 or ratio <= 0.2:
        return f"\n\n💡 小提醒：本月预算还剩 {budget_left:.0f} 元（{ratio*100:.0f}%），进入谨慎消费模式吧。"
    return ""


# ─────────────────── LLM 意图识别 ───────────────────

_INTENT_SYSTEM = """
你是大学生理财助手"财搭子"的意图分类器。
请根据用户最新一句话，从以下5类意图中选择最合适的一类，只输出意图名称，不要有任何多余文字：

- 记账        （记录一笔支出，如"买奶茶花了18元"）
- 心愿规划    （设定/更新储蓄目标或存入进度，如"我想攒12000换电脑"、"今天攒了200"）
- 高危咨询    （涉及刷单、校园贷、高收益稳赚、套现等）
- 理财问答    （询问理财知识，如"货币基金是什么"）
- 日常闲聊    （其他所有情况）
""".strip()

_INTENT_EXAMPLES = [
    ("今天午饭吃了26元", "记账"),
    ("外卖花了35块", "记账"),
    ("我想12个月攒12000元换电脑", "心愿规划"),
    ("今天存了300", "心愿规划"),
    ("有人让我刷单说日入500", "高危咨询"),
    ("校园贷利息高不高", "高危咨询"),
    ("货币基金和定期存款哪个好", "理财问答"),
    ("余额宝怎么用", "理财问答"),
    ("最近有点焦虑", "日常闲聊"),
    ("你好", "日常闲聊"),
]


def _llm_classify_intent(text: str) -> Intent:
    """用 LLM 做 few-shot 意图分类，失败时回退关键词匹配"""
    llm = get_deepseek_llm()
    if llm is None:
        return _keyword_classify_intent(text)

    example_lines = "\n".join(f'用户："{u}" → {label}' for u, label in _INTENT_EXAMPLES)
    prompt = f"{example_lines}\n用户：\"{text}\" →"

    try:
        response = llm.invoke(
            [
                SystemMessage(content=_INTENT_SYSTEM),
                HumanMessage(content=prompt),
            ]
        )
        raw = (response.content or "").strip()
        # 从回复中匹配意图
        for intent in ("记账", "心愿规划", "高危咨询", "理财问答", "日常闲聊"):
            if intent in raw:
                return intent  # type: ignore[return-value]
    except Exception:
        pass

    return _keyword_classify_intent(text)


def _keyword_classify_intent(text: str) -> Intent:
    """关键词兜底分类（原有逻辑）"""
    if any(kw in text for kw in HIGH_RISK_KEYWORDS):
        return "高危咨询"
    if any(kw in text for kw in BUDGET_SET_KEYWORDS):
        return "日常闲聊"  # 由 IntentClassifier 单独处理
    if any(kw in text for kw in WISHLIST_KEYWORDS) or _extract_deposit_amount(text) is not None:
        return "心愿规划"
    if any(kw in text for kw in FINANCE_QA_KEYWORDS):
        return "理财问答"
    if any(kw in text for kw in BOOKKEEPING_KEYWORDS) or _extract_amount(text) is not None:
        return "记账"
    return "日常闲聊"


# ─────────────────── 节点实现 ───────────────────

@dataclass
class IntentClassifierNode:
    def __call__(self, state: FinBuddyState) -> dict:
        text = _latest_text(state)
        risk_flag = any(keyword in text for keyword in HIGH_RISK_KEYWORDS)

        if risk_flag:
            intent: Intent = "高危咨询"
        elif any(kw in text for kw in BUDGET_SET_KEYWORDS):
            # 预算设置走 ChatNode 处理
            intent = "日常闲聊"
        else:
            intent = _llm_classify_intent(text)
            if intent != "高危咨询":
                risk_flag = False

        return {"intent": intent, "risk_flag": risk_flag}


@dataclass
class BookkeeperNode:
    def __call__(self, state: FinBuddyState) -> dict:
        text = _latest_text(state)
        amount = _extract_amount(text) or 0.0
        category = _classify_category(text)
        record = ExpenseRecord(amount=amount, category=category)
        budget_left = max(0.0, state["budget_left"] - record.amount)
        budget_total = state.get("budget_total", 1500.0)

        # 更新消费记录列表
        expense_records: list[ExpenseItem] = list(state.get("expense_records") or [])
        if record.amount > 0:
            expense_records.append(
                ExpenseItem(amount=record.amount, category=category, note=text[:30])
            )

        warning = _budget_warning(budget_left, budget_total)

        if record.amount == 0:
            fallback = '我先帮你记个待确认账目，不过金额我没看清。你补一句"花了 xx 元"，我马上给预算小本本扣上。'
        elif record.amount <= 30:
            fallback = (
                f"收到，{category} {record.amount:.2f} 元已记下。本月日常预算还剩 {budget_left:.2f} 元。"
                f"小钱花在开心上也算给生活充电，咱们稳稳地看住大头就好。{warning}"
            )
        elif record.amount > 300:
            fallback = (
                f"记上啦，{category} {record.amount:.2f} 元，本月日常预算还剩 {budget_left:.2f} 元。"
                f"这笔有点存在感，钱包可能刚刚轻咳了一声；不过别慌，后面几天我陪你把节奏拉回来。{warning}"
            )
        else:
            fallback = (
                f"好嘞，{category} {record.amount:.2f} 元已入账，本月日常预算还剩 {budget_left:.2f} 元。"
                f"这笔不算离谱，今天就别内耗了，下一笔咱们继续聪明花。{warning}"
            )

        reply = generate_finbuddy_reply(
            task=(
                f"记账反馈。已识别消费分类为{category}，金额为{record.amount:.2f}元，"
                f"扣减后预算剩余{budget_left:.2f}元（月度总预算{budget_total:.2f}元）。"
                + (f" 预算紧张，请在回复末加一句温柔提醒。" if warning else "")
            ),
            user_text=text,
            state={**state, "budget_left": budget_left},
            fallback=fallback,
        )
        return {
            "budget_left": budget_left,
            "expense_records": expense_records,
            "messages": _append_reply(state, reply),
        }


@dataclass
class ReversePlannerNode:
    def __call__(self, state: FinBuddyState) -> dict:
        text = _latest_text(state)
        wishlists: list[WishlistItem] = list(state.get("wishlists") or [])
        active_idx: int = state.get("active_wishlist_index", 0)

        amounts_yuan = _amounts_with_currency(text)
        deposit_amount = _extract_deposit_amount(text)
        planning_focus = any(kw in text for kw in WISHLIST_KEYWORDS) or bool(
            re.search(r"\d+\s*(?:个月|月)", text)
        )

        # ── 判断是否要新建心愿 ──
        is_new_wishlist = (
            planning_focus
            and amounts_yuan
            and not deposit_amount
            and (
                not wishlists
                or any(kw in text for kw in ("新", "另一个", "再", "还想", "还要"))
            )
        )

        if is_new_wishlist and amounts_yuan:
            target = max(amounts_yuan)
            months = _extract_months(text)
            name = _extract_wishlist_name(text)
            new_item = WishlistItem(
                id=str(uuid.uuid4())[:8],
                name=name,
                target_amount=target,
                saved_amount=0.0,
                months=months,
            )
            wishlists.append(new_item)
            active_idx = len(wishlists) - 1
        elif wishlists:
            # 在当前活跃心愿上操作
            idx = min(active_idx, len(wishlists) - 1)
            item = dict(wishlists[idx])

            if deposit_amount:
                item["saved_amount"] = float(item["saved_amount"]) + deposit_amount
            if planning_focus and amounts_yuan:
                item["target_amount"] = max(amounts_yuan)
            if re.search(r"\d+\s*(?:个月|月)", text):
                item["months"] = _extract_months(text)

            wishlists[idx] = WishlistItem(**item)
            active_idx = idx
        else:
            # 没有任何心愿，创建默认
            target = max(amounts_yuan) if amounts_yuan else 12000.0
            months = _extract_months(text)
            name = _extract_wishlist_name(text)
            wishlists.append(WishlistItem(
                id=str(uuid.uuid4())[:8],
                name=name,
                target_amount=target,
                saved_amount=0.0,
                months=months,
            ))
            active_idx = 0

        # 计算当前活跃心愿的规划数据
        active = wishlists[active_idx]
        remaining = max(0.0, float(active["target_amount"]) - float(active["saved_amount"]))
        months = int(active["months"])
        monthly_saving = ceil((remaining / months) * 100) / 100 if months else 0.0

        deposit_note = f"我已帮你把 {deposit_amount:.2f} 元计入「{active['name']}」进度。" if deposit_amount else ""

        fallback = (
            f"{deposit_note}"
            f"「{active['name']}」心愿进度：目标 {active['target_amount']:.2f} 元，"
            f"已攒 {active['saved_amount']:.2f} 元，还差 {remaining:.2f} 元。"
            f"按 {months} 个月来走，每月先留出 {monthly_saving:.2f} 元就能慢慢靠近。"
            "建议把心愿资金放进极低风险、流动性好的货币基金或活钱管理，和日常花销隔开。"
            "你负责期待新生活，我负责提醒你别被短期冲动拐跑。"
        )

        plan_desc = (
            f"心愿逆向规划。心愿名称「{active['name']}」，目标{active['target_amount']:.2f}元，"
            f"已攒{active['saved_amount']:.2f}元，还差{remaining:.2f}元，"
            f"周期{months}个月，每月建议储蓄{monthly_saving:.2f}元。"
            + (f" 本轮入账{deposit_amount:.2f}元。" if deposit_amount else "")
            + (f" 共有{len(wishlists)}个心愿目标。" if len(wishlists) > 1 else "")
        )

        reply = generate_finbuddy_reply(
            task=plan_desc,
            user_text=text,
            state={
                **state,
                "intent": "心愿规划",
                "wishlists": wishlists,
                "active_wishlist_index": active_idx,
            },
            fallback=fallback,
        )

        return {
            "wishlists": wishlists,
            "active_wishlist_index": active_idx,
            "messages": _append_reply(state, reply),
        }


@dataclass
class RiskGuardNode:
    def __call__(self, state: FinBuddyState) -> dict:
        fallback = (
            "先停一下，这类信息已经触发高风险预警。凡是涉及兼职刷单、校园贷、高收益稳赚、刷流水、套现返利的说法，"
            "都可能伴随诈骗、非法借贷、洗钱或个人信息泄露风险。不要转账，不要提供身份证、银行卡、验证码，也不要继续按对方指引操作。"
            "我不会提供任何投资建议或操作路径。建议你立刻保存聊天和转账证据，联系学校辅导员、家人或官方反诈渠道核实。"
        )
        reply = generate_finbuddy_reply(
            task="高危咨询风控接管。必须严厉警示诈骗、非法借贷、洗钱和隐私泄露风险，不提供任何投资建议。",
            user_text=_latest_text(state),
            state={**state, "risk_flag": True},
            fallback=fallback,
        )
        return {"risk_flag": True, "messages": _append_reply(state, reply)}


@dataclass
class FinanceQANode:
    """理财知识问答节点：回答大学生常见的理财入门问题，注入预置知识卡片"""

    def __call__(self, state: FinBuddyState) -> dict:
        text = _latest_text(state)

        # 注入知识卡片，引导 LLM 给出更准确的对比回答
        task = (
            "理财知识问答。用户询问理财基础知识，请参考以下知识卡片内容，"
            "用同龄学长/学姐口吻，简洁清晰地回答，不超过200字，"
            "不推荐具体产品购买，不承诺收益，以科普为主。\n\n"
            + _FINANCE_KNOWLEDGE_CARD
        )

        fallback = (
            "这是个好问题！理财的核心原则是：先保证日常流动性，再考虑收益。\n"
            "对学生来说，货币基金（如余额宝类产品）是很合适的起步工具——"
            "风险等级R1（最低风险）、随存随取，年化收益约1.5%~2.5%。\n"
            "花呗/白条记得账单日全额还款，避免产生循环利息（年化约18%）。\n"
            "如果你有具体想了解的产品或概念，直接问我，我用大白话讲清楚。"
        )
        reply = generate_finbuddy_reply(
            task=task,
            user_text=text,
            state=state,
            fallback=fallback,
        )
        return {"messages": _append_reply(state, reply)}


# ── 理财测评问题配置 ──
_PROFILE_QUESTIONS = [
    {
        "step": 1,
        "question": (
            "先来了解一下你的情况～\n"
            "**问题1/3：你每月大概有多少可自由支配的钱（生活费+兼职收入等）？**\n"
            "A. 500元以下  B. 500~1000元  C. 1000~2000元  D. 2000元以上"
        ),
        "key": "monthly_income",
    },
    {
        "step": 2,
        "question": (
            "**问题2/3：如果手头有500元暂时不用，你更倾向于？**\n"
            "A. 全部放活期/余额宝，随时能取  "
            "B. 存3~6个月定期，牺牲流动性换高一点的利息  "
            "C. 买点低风险基金碰碰运气  "
            "D. 买股票/高收益理财博一把"
        ),
        "key": "risk_preference",
    },
    {
        "step": 3,
        "question": (
            "**问题3/3：你现在有应急储蓄吗（够支撑1~3个月基本开销的备用金）？**\n"
            "A. 有，而且超过3个月  B. 有一点，但不够  C. 完全没有"
        ),
        "key": "emergency_fund",
    },
]

_INCOME_MAP = {"A": 300, "B": 750, "C": 1500, "D": 2500}
_RISK_MAP = {"A": "保守型", "B": "稳健型", "C": "稳健型", "D": "积极型"}
_EMERGENCY_MAP = {"A": True, "B": False, "C": False}


def _parse_choice(text: str, valid: tuple) -> Optional[str]:
    """从用户输入中提取选项字母（大小写不敏感）"""
    for ch in valid:
        if ch in text.upper():
            return ch
    return None


def _generate_profile_suggestion(profile: FinanceProfile) -> str:
    """根据测评结果生成个性化建议"""
    risk = profile["risk_level"]
    income = profile["monthly_income"]
    has_emergency = profile["has_emergency_fund"]

    lines = [f"📊 你的理财画像：**{risk}**\n"]

    if not has_emergency:
        lines.append(
            "🔴 第一步：先建立应急储蓄！"
            f"建议先把{min(income * 3, 3000):.0f}元（约3个月生活费）"
            "存进货币基金，和日常花销隔开。"
        )
    else:
        lines.append("✅ 很好，你已经有应急储蓄的意识了！")

    if risk == "保守型":
        lines.append(
            "💡 适合你的工具：货币基金（余额宝/零钱通）> 定期存款 > 国债\n"
            "核心原则：本金安全第一，收益其次，不碰股票和高波动基金。"
        )
    elif risk == "稳健型":
        lines.append(
            "💡 适合你的工具：货币基金打底 + 低风险债券基金 > 定期存款\n"
            "核心原则：生活备用金放货币基金，多余资金可尝试R2级债基，不追涨杀跌。"
        )
    else:
        lines.append(
            "💡 适合你的工具：货币基金（备用金）+ 指数基金定投（闲钱）\n"
            "核心原则：只用不影响生活的闲钱做指数定投，长期持有，不要满仓。"
        )

    lines.append("\n花呗/信用卡务必账单日全额还款，征信是未来重要资产。")
    return "\n".join(lines)


@dataclass
class FinanceProfileNode:
    """对话式理财测评节点：3步问卷 → 风险偏好画像 → 个性化建议"""

    def __call__(self, state: FinBuddyState) -> dict:
        text = _latest_text(state)
        profile: FinanceProfile = dict(state.get("finance_profile") or _default_profile())  # type: ignore
        step = int(profile.get("step", 0))

        # ── step=0：刚触发测评，发出第一问 ──
        if step == 0:
            profile["step"] = 1
            q = _PROFILE_QUESTIONS[0]["question"]
            return {
                "finance_profile": profile,
                "messages": _append_reply(state, f"好的，我来帮你做个简单的理财画像测评～\n\n{q}"),
            }

        # ── step=1：处理第1题答案，发第2题 ──
        if step == 1:
            choice = _parse_choice(text, ("A", "B", "C", "D"))
            profile["monthly_income"] = _INCOME_MAP.get(choice or "B", 750)
            profile["step"] = 2
            q = _PROFILE_QUESTIONS[1]["question"]
            return {
                "finance_profile": profile,
                "messages": _append_reply(state, f"收到！\n\n{q}"),
            }

        # ── step=2：处理第2题答案，发第3题 ──
        if step == 2:
            choice = _parse_choice(text, ("A", "B", "C", "D"))
            profile["risk_level"] = _RISK_MAP.get(choice or "A", "保守型")
            profile["step"] = 3
            q = _PROFILE_QUESTIONS[2]["question"]
            return {
                "finance_profile": profile,
                "messages": _append_reply(state, f"了解～\n\n{q}"),
            }

        # ── step=3：处理第3题答案，生成最终画像 ──
        if step == 3:
            choice = _parse_choice(text, ("A", "B", "C"))
            profile["has_emergency_fund"] = _EMERGENCY_MAP.get(choice or "C", False)
            profile["step"] = 4
            profile["completed"] = True

            suggestion = _generate_profile_suggestion(profile)  # type: ignore
            profile["suggestion"] = suggestion

            task = (
                f"理财测评完成。用户风险偏好：{profile['risk_level']}，"
                f"月均可支配收入约{profile['monthly_income']:.0f}元，"
                f"应急储蓄状态：{'已有' if profile['has_emergency_fund'] else '未建立'}。\n"
                "请根据以下初步建议，用同龄学长口吻做一段温暖、实用的个性化理财规划总结（150字内），"
                "不推荐具体产品，重点突出最优先的1~2个行动建议。\n\n"
                + suggestion
            )
            fallback = suggestion

            reply = generate_finbuddy_reply(
                task=task,
                user_text=text,
                state={**state, "finance_profile": profile},  # type: ignore
                fallback=fallback,
            )
            return {
                "finance_profile": profile,
                "messages": _append_reply(state, reply),
            }

        # step>=4：测评已完成，可重新触发
        profile["step"] = 0
        profile["completed"] = False
        return {
            "finance_profile": profile,
            "messages": _append_reply(
                state,
                "你想重新做一次理财测评吗？直接说「理财测评」我们就重新开始～",
            ),
        }


@dataclass
class ChatNode:
    def __call__(self, state: FinBuddyState) -> dict:
        text = _latest_text(state)

        # 处理预算设置
        if any(kw in text for kw in BUDGET_SET_KEYWORDS):
            new_budget = _extract_budget_amount(text)
            if new_budget and new_budget > 0:
                fallback = (
                    f"好的，已把你的月度预算更新为 {new_budget:.0f} 元。"
                    "从现在开始，每次记账都会以这个数字为基准来提醒你剩余预算。"
                    "合理规划，量入为出，你已经走在正确的路上了！"
                )
                reply = generate_finbuddy_reply(
                    task=f"用户设置月度生活预算为{new_budget:.0f}元，请友好确认并给予鼓励。",
                    user_text=text,
                    state={**state, "budget_total": new_budget, "budget_left": new_budget},
                    fallback=fallback,
                )
                return {
                    "budget_total": new_budget,
                    "budget_left": new_budget,
                    "messages": _append_reply(state, reply),
                }

        fallback = (
            "我在呢。你可以把我当成同龄学长版的财务搭子：想吐槽消费、记一笔账、"
            "拆一个心愿目标，或者遇到看起来很香但有点怪的赚钱机会，都可以先丢给我看看。"
        )
        reply = generate_finbuddy_reply(
            task="日常闲聊。维持同龄学长人设，自然陪伴，引导用户可以记账、规划心愿或做风险核查。",
            user_text=text,
            state=state,
            fallback=fallback,
        )
        return {"messages": _append_reply(state, reply)}
