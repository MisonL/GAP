# ---- Stage 1: Build Vue.js Frontend ----
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# 安装构建工具和依赖
RUN apk add --no-cache autoconf automake build-base libtool nasm zlib-dev

# 复制前端文件
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install --legacy-peer-deps

COPY frontend ./frontend/

# 安装依赖并构建
RUN cd frontend && npm run build

# ---- Stage 2: Build Python Backend ----
FROM python:3.11-alpine

WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=on

# 1. 安装系统依赖
RUN apk add --no-cache build-base libffi-dev curl

# 2. 复制依赖文件
COPY backend/requirements.txt ./backend/

# 3. 安装Python依赖
RUN pip install --no-cache-dir -r backend/requirements.txt

# 4. 复制应用代码
COPY backend/src ./backend/src

# 5. 从前端构建阶段复制静态文件
COPY --from=frontend-builder /app/frontend/dist ./backend/src/gap/frontend/dist

# 6. 创建数据目录
RUN mkdir -p /app/data

# 7. 添加健康检查
HEALTHCHECK --interval=30s --timeout=5s \
    CMD curl -f http://localhost:7860/healthz || exit 1

# 暴露端口
EXPOSE 7860

# 设置工作目录
WORKDIR /app/backend/src

# 启动命令
CMD ["uvicorn", "gap.main:app", "--host", "0.0.0.0", "--port", "7860", "--no-access-log"]
