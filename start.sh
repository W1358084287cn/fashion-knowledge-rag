#!/usr/bin/env bash
# ============================================================
# 一键启动脚本（macOS / Linux）
# 使用前请确保已安装：Python 3.9+、Node.js 18+、Docker
# 用法：bash start.sh
# ============================================================
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  基于 LangChain + 知识图谱双引擎的服装智能客服系统"
echo "============================================================"

# 1. 虚拟环境
if [ ! -x ".venv/bin/python" ]; then
  echo "[1/5] 创建 Python 虚拟环境 .venv ..."
  python3 -m venv .venv
fi

echo "[1/5] 检查后端依赖 ..."
if ! .venv/bin/python -c "import fastapi, langchain_openai, qdrant_client, neo4j, pdfplumber" >/dev/null 2>&1; then
  echo "      正在安装后端依赖（首次约 5~10 分钟）..."
  .venv/bin/python -m pip install -r backend/requirements.txt
fi

# 2. Docker 检查
DOCKER_OK=1
echo "[2/5] 检查 Docker 引擎 ..."
if ! docker info >/dev/null 2>&1; then
  DOCKER_OK=0
  echo "      [警告] Docker 未就绪，Qdrant / Neo4j 无法启动，问答检索将降级。"
fi

# 3. 启动基础设施：本机有 MySQL 就只启动 qdrant + neo4j
echo "[3/5] 启动基础设施 ..."
if [ "$DOCKER_OK" = "1" ]; then
  if nc -z 127.0.0.1 3306 >/dev/null 2>&1 || (echo > /dev/tcp/127.0.0.1/3306) >/dev/null 2>&1; then
    echo "      检测到本机 MySQL（3306），使用本机 MySQL 作为业务库。"
    docker compose up -d qdrant neo4j
  else
    echo "      未检测到本机 MySQL，使用 Docker MySQL（3307）。"
    export MYSQL_PORT=3307
    docker compose --profile with-mysql up -d
  fi
else
  echo "      Docker 未就绪，跳过容器启动。"
fi

# 4. 前端构建
echo "[4/5] 检查前端页面 ..."
if [ ! -f "frontend/dist/index.html" ]; then
  echo "      正在构建前端 ..."
  (cd frontend && npm install && npm run build)
fi

# 5. 启动后端
echo "[5/5] 启动后端服务 ..."
echo ""
echo "  管理端： http://127.0.0.1:8000/admin   （admin / 123456）"
echo "  客户端： http://127.0.0.1:8000/"
echo "  局域网访问：http://<本机IP>:8000/"
echo ""

# macOS 自动打开浏览器（可选）
if command -v open >/dev/null 2>&1; then
  (sleep 6 && open "http://127.0.0.1:8000/admin") &
elif command -v xdg-open >/dev/null 2>&1; then
  (sleep 6 && xdg-open "http://127.0.0.1:8000/admin") &
fi

.venv/bin/python backend/run.py
