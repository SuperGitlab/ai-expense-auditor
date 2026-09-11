# 后端生产镜像
# 注意：构建上下文是仓库根（pyproject.toml/uv.lock 在根），见 compose 的 build.context
FROM python:3.12-slim

# libgomp1: onnxruntime(rapidocr)运行依赖；tini: 容器信号转发
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# 先拷依赖清单再拷代码（利用层缓存）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ ./backend/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
# ./uploads ./data ./logs 相对路径基于此目录，与开发环境一致
RUN mkdir -p uploads data logs

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
