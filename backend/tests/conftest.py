import pytest
from fastapi.testclient import TestClient

from app.llm import get_deepseek_llm
from app.main import app


@pytest.fixture(autouse=True)
def disable_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINBUDDY_LLM_API_KEY", raising=False)
    get_deepseek_llm.cache_clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)
