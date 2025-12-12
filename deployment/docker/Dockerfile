# ---- Stage 1: Build Vue.js Frontend ----
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# 创建非root用户（仅在构建时需要）
RUN addgroup -g 1001 -S appgroup && \
    adduser -S appuser -u 1001

# 安全更新和安装构建工具
RUN apk update && \
    apk upgrade && \
    apk add --no-cache \
        autoconf \
        automake \
        build-base \
        libtool \
        nasm \
        zlib-dev \
        && \
    rm -rf /var/cache/apk/* && \
    rm -rf /tmp/* && \
    rm -rf /var/tmp/*

# 复制前端文件
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm ci --legacy-peer-deps && \
    npm cache clean --force

COPY frontend ./frontend/

# 安装依赖并构建
RUN cd frontend && npm run build && \
    # 清理构建缓存
    npm cache clean --force && \
    rm -rf ~/.npm

# ---- Stage 2: Build Python Runtime ----
FROM python:3.11-alpine AS runtime

# 设置安全环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=on \
    PYTHONDONTWRITEBYTECODE=1 \
    # 安全相关环境变量
    PYTHONHASHSEED=random \
    # 限制Python路径
    PYTHONPATH="/app/backend/src"

# 创建非root用户
RUN addgroup -g 1001 -S appgroup && \
    adduser -S appuser -u 1001

# 更新系统并安装安全补丁
RUN apk update && \
    apk upgrade && \
    # 安装运行时依赖（最小化）
    apk add --no-cache \
        build-base \
        libffi-dev \
        curl \
        tini \
        && \
    # 清理缓存
    rm -rf /var/cache/apk/* && \
    rm -rf /tmp/* && \
    rm -rf /var/tmp/*

# 复制依赖文件
COPY backend/requirements.txt /app/backend/

# 安装Python依赖（使用pip检查）
RUN pip install --no-cache-dir -r /app/backend/requirements.txt && \
    # 验证安装
    pip check

# 复制应用代码
COPY backend/src /app/backend/src

# 从前端构建阶段复制静态文件
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# 创建必要的目录并设置权限
RUN mkdir -p /app/backend /app/data /app/logs && \
    # 设置所有文件为非root用户
    chown -R appuser:appgroup /app && \
    # 设置安全权限
    chmod -R 755 /app && \
    chmod -R 644 /app/backend/src/*.py /app/backend/src/**/*.py 2>/dev/null || true

# 切换到非root用户
USER appuser

# 设置工作目录
WORKDIR /app/backend/src

# 添加安全元数据
LABEL maintainer="GAP Team" \
      version="1.0" \
      description="Gemini API Proxy - Secure Docker Image" \
      security.scan="enabled"

# 强化运行时健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:7860/healthz || exit 1

# 暴露端口
EXPOSE 7860

# 使用tini作为init进程
ENTRYPOINT ["/sbin/tini", "--"]

# 安全启动命令
CMD ["uvicorn", "gap.main:app", \
     "--host", "0.0.0.0", \
     "--port", "7860", \
     "--no-access-log", \
     "--workers", "1", \
     "--limit-concurrency", "100", \
     "--timeout-keep-alive", "5"]
