# ---- Stage 1: Build Vue.js Frontend with pnpm ----
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# 启用 corepack 以使用 pnpm
RUN corepack enable && corepack prepare pnpm@9.15.2 --activate

# 安全更新并安装构建工具
RUN apk update && apk upgrade && \
    apk add --no-cache \
    autoconf \
    automake \
    build-base \
    libtool \
    nasm \
    zlib-dev \
    && \
    rm -rf /var/cache/apk/*

# 复制依赖配置文件
COPY frontend/package.json frontend/pnpm-lock.yaml* frontend/.npmrc ./frontend/

# 安装依赖（使用 pnpm，支持缓存挂载）
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    cd frontend && \
    pnpm install --frozen-lockfile --ignore-scripts 2>/dev/null || \
    pnpm install --no-frozen-lockfile

# 复制前端源码
COPY frontend ./frontend/

# 构建前端
RUN cd frontend && pnpm run build

# ---- Stage 2: Build Python Runtime with uv ----
FROM python:3.11-alpine AS runtime

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random \
    PYTHONPATH="/app/backend/src" \
    # uv 配置
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

# 创建非root用户
RUN addgroup -g 1001 -S appgroup && \
    adduser -S appuser -u 1001

# 安装系统依赖和 uv
RUN apk update && apk upgrade && \
    apk add --no-cache \
    build-base \
    libffi-dev \
    curl \
    tini \
    && \
    # 安装 uv
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    # 清理缓存
    rm -rf /var/cache/apk/* /tmp/* /var/tmp/*

# 添加 uv 到 PATH
ENV PATH="/root/.local/bin:$PATH"

# 复制依赖文件
COPY backend/pyproject.toml backend/requirements.txt /app/backend/

# 安装 Python 依赖（使用 uv，支持缓存挂载）
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    cd /app/backend && \
    uv pip install --system -r requirements.txt

# 复制应用代码
COPY backend/src /app/backend/src

# 从前端构建阶段复制静态文件
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# 创建必要的目录并设置权限
RUN mkdir -p /app/backend /app/data /app/logs && \
    chown -R appuser:appgroup /app && \
    chmod -R 755 /app

# 切换到非root用户
USER appuser

# 设置工作目录
WORKDIR /app/backend/src

# 添加元数据
LABEL maintainer="GAP Team" \
    version="1.9.0" \
    description="Gemini API Proxy - Optimized Docker Image"

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:7860/healthz || exit 1

# 暴露端口
EXPOSE 7860

# 使用tini作为init进程
ENTRYPOINT ["/sbin/tini", "--"]

# 启动命令
CMD ["uvicorn", "gap.main:app", \
    "--host", "0.0.0.0", \
    "--port", "7860", \
    "--no-access-log", \
    "--workers", "1", \
    "--limit-concurrency", "100", \
    "--timeout-keep-alive", "5"]
