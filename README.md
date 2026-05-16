# FinBuddy

财搭子是一个面向大学生的陪伴型理财产品。本仓库采用前后端分离结构：

- `frontend/`: Next.js App Router + React + Tailwind CSS + lucide-react
- `backend/`: Python + FastAPI + LangGraph StateGraph

## Backend

后端负责意图识别、LangGraph 编排、预算与心愿状态管理，并配置了本地前端跨域访问。

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

DeepSeek 相关环境变量位于 `backend/.env`：

```bash
FINBUDDY_LLM_API_KEY=your-deepseek-api-key
FINBUDDY_LLM_BASE_URL=https://api.deepseek.com
FINBUDDY_LLM_MODEL=deepseek-chat
```

## Frontend

前端只负责展示状态和收集用户输入，调用后端 `/chat` 接口。

```bash
cd frontend
npm install
npm run dev
```

可选环境变量：

```bash
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

## Chat API

- `GET /health`
- `POST /chat`

请求示例：

```json
{
  "message": "今天买奶茶花了18元",
  "budget_left": 1500,
  "wishlist_target": 12000,
  "wishlist_saved": 0,
  "history": []
}
```
