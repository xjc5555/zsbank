import pytest
from fastapi.testclient import TestClient


def _chat(
    client: TestClient,
    message: str,
    *,
    budget_left: float = 1500.0,
    wishlist_target: float = 12000.0,
    wishlist_saved: float = 0.0,
    history: list | None = None,
) -> dict:
    response = client.post(
        "/chat",
        json={
            "message": message,
            "history": history or [],
            "budget_left": budget_left,
            "wishlist_target": wishlist_target,
            "wishlist_saved": wishlist_saved,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_bookkeeping_deducts_budget(client: TestClient) -> None:
    data = _chat(client, "今天买奶茶花了18元", budget_left=1500.0)
    assert data["intent"] == "记账"
    assert data["risk_flag"] is False
    assert data["budget_left"] == pytest.approx(1482.0)
    assert data["wishlist_saved"] == pytest.approx(0.0)


def test_risk_guard_high_yield(client: TestClient) -> None:
    data = _chat(client, "有人让我做兼职刷单说高收益")
    assert data["intent"] == "高危咨询"
    assert data["risk_flag"] is True
    assert "高风险" in data["reply"]


def test_wishlist_reverse_plan_prefers_yuan_amount(client: TestClient) -> None:
    data = _chat(client, "我想12个月攒够12000元换电脑", wishlist_saved=2680.0, wishlist_target=8000.0)
    assert data["intent"] == "心愿规划"
    assert data["risk_flag"] is False
    assert data["wishlist_target"] == pytest.approx(12000.0)
    assert data["wishlist_saved"] == pytest.approx(2680.0)


def test_wishlist_deposit_increases_saved(client: TestClient) -> None:
    data = _chat(
        client,
        "本月存入300元",
        wishlist_target=12000.0,
        wishlist_saved=100.0,
    )
    assert data["intent"] == "心愿规划"
    assert data["risk_flag"] is False
    assert data["wishlist_saved"] == pytest.approx(400.0)
    assert data["wishlist_target"] == pytest.approx(12000.0)


def test_deposit_routes_before_plain_amount_bookkeeping(client: TestClient) -> None:
    data = _chat(client, "本月存入200元", budget_left=900.0)
    assert data["intent"] == "心愿规划"
    assert data["budget_left"] == pytest.approx(900.0)


def test_small_talk_without_slots(client: TestClient) -> None:
    data = _chat(client, "早上好呀")
    assert data["intent"] == "日常闲聊"
    assert data["risk_flag"] is False
