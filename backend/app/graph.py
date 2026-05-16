from langgraph.graph import END, START, StateGraph

from app.nodes import (
    BookkeeperNode,
    ChatNode,
    FinanceProfileNode,
    FinanceQANode,
    IntentClassifierNode,
    ReversePlannerNode,
    RiskGuardNode,
    FINANCE_PROFILE_KEYWORDS,
)
from app.state import FinBuddyState


def route_by_intent(state: FinBuddyState) -> str:
    if state["risk_flag"]:
        return "RiskGuardNode"

    # 理财测评：关键词触发 或 测评进行中（step 1~3）
    profile = state.get("finance_profile") or {}
    profile_step = int(profile.get("step", 0))
    if profile_step in (1, 2, 3):
        # 测评进行中，继续走测评节点
        return "FinanceProfileNode"

    # 新触发测评
    from app.nodes import _latest_text  # noqa: PLC0415
    text = _latest_text(state)
    if any(kw in text for kw in FINANCE_PROFILE_KEYWORDS):
        return "FinanceProfileNode"

    intent_routes = {
        "记账": "BookkeeperNode",
        "心愿规划": "ReversePlannerNode",
        "高危咨询": "RiskGuardNode",
        "理财问答": "FinanceQANode",
        "理财测评": "FinanceProfileNode",
        "日常闲聊": "ChatNode",
    }
    return intent_routes.get(state["intent"], "ChatNode")


def build_finbuddy_graph():
    graph = StateGraph(FinBuddyState)

    graph.add_node("IntentClassifierNode", IntentClassifierNode())
    graph.add_node("BookkeeperNode", BookkeeperNode())
    graph.add_node("ReversePlannerNode", ReversePlannerNode())
    graph.add_node("RiskGuardNode", RiskGuardNode())
    graph.add_node("FinanceQANode", FinanceQANode())
    graph.add_node("FinanceProfileNode", FinanceProfileNode())
    graph.add_node("ChatNode", ChatNode())

    graph.add_edge(START, "IntentClassifierNode")
    graph.add_conditional_edges(
        "IntentClassifierNode",
        route_by_intent,
        {
            "BookkeeperNode": "BookkeeperNode",
            "ReversePlannerNode": "ReversePlannerNode",
            "RiskGuardNode": "RiskGuardNode",
            "FinanceQANode": "FinanceQANode",
            "FinanceProfileNode": "FinanceProfileNode",
            "ChatNode": "ChatNode",
        },
    )
    graph.add_edge("BookkeeperNode", END)
    graph.add_edge("ReversePlannerNode", END)
    graph.add_edge("RiskGuardNode", END)
    graph.add_edge("FinanceQANode", END)
    graph.add_edge("FinanceProfileNode", END)
    graph.add_edge("ChatNode", END)

    return graph.compile()


finbuddy_graph = build_finbuddy_graph()
