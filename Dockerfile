# ============================================================
# 服装智能客服系统 - 生产镜像
# 说明：
# 1. 前端 dist 在本地/构建机已打包好，镜像内不再执行 npm，降低服务器内存压力
# 2. 只安装核心依赖，PaddleOCR 按需另行安装（体积大）
# 3. 单进程 uvicorn，适合 2C2G 小服务器
# ============================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 先只拷贝依赖清单，命中 Docker 层缓存，改代码时不用重新装依赖
# 使用清华 PyPI 镜像：国内服务器直连 pypi.org 经常卡住/超时
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --timeout 60 --retries 5 \
        -r /app/backend/requirements.txt

# 拷贝后端代码与已构建的前端静态文件
COPY backend /app/backend
COPY frontend/dist /app/frontend/dist

# 上传目录（运行时用数据卷挂载）
RUN mkdir -p /app/backend/uploads

EXPOSE 8000

# 健康检查：容器内直接访问健康接口，避免额外安装 curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

CMD ["python", "backend/run.py"]
