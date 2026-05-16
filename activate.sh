# 终端1 - 后端
cd /Users/xujc/Desktop/zsbank/backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端2 - 前端
cd /Users/xujc/Desktop/zsbank/frontend && npm run dev