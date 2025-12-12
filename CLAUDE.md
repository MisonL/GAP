# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

GAP (Gemini API Proxy) 是一个基于 FastAPI + Vue.js 的现代化 API 代理服务，提供 OpenAI 兼容和 Gemini 原生的 API 接口，支持智能 API 密钥轮换、缓存管理、用户认证等功能。

## 常用开发命令

### 后端开发
```bash
# 进入后端目录
cd backend

# 安装依赖 (使用 UV - 现代化包管理器)
uv venv  # 创建虚拟环境
source .venv/bin/activate  # 激活环境
uv pip install -e ".[dev]"  # 安装所有依赖

# 或使用快速开发脚本
./scripts/dev.sh

# 开发模式启动
uv run uvicorn src.gap.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式启动
uvicorn src.gap.main:app --host 0.0.0.0 --port 8000 --workers 4

# 运行测试 (使用 UV)
uv run pytest                   # 运行所有测试
uv run pytest tests/unit/       # 单元测试
uv run pytest tests/integration/ # 集成测试
uv run pytest --cov=src --cov-report=html  # 带覆盖率报告
# 或使用测试脚本
./scripts/test.sh all            # 完整测试套件
./scripts/test.sh coverage       # 覆盖率测试

# 代码质量检查 (使用 UV)
uv run black src/               # 代码格式化
uv run isort src/               # 导入排序
uv run mypy src/                # 类型检查
uv run flake8 src/              # 代码检查
# 或使用测试脚本
./scripts/test.sh lint          # 综合质量检查

# 数据库操作
alembic revision --autogenerate -m "描述"  # 创建迁移
alembic upgrade head                        # 应用迁移
alembic downgrade -1                        # 回滚迁移
```

## 🚀 UV 包管理器指南

### 安装 UV
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### UV 基本命令
```bash
# 创建虚拟环境
uv venv --python 3.10

# 激活环境
source .venv/bin/activate

# 安装依赖
uv pip install -e ".[dev]"    # 开发依赖
uv pip install -e "."         # 仅生产依赖

# 同步依赖
uv pip sync

# 运行命令
uv run uvicorn src.gap.main:app --reload
uv run pytest
uv run black src/
```

### 依赖分组
- **默认**: 生产依赖
- **[dev]**: 开发 + 测试 + 代码质量工具
- **[test]**: 仅测试相关
- **[lint]**: 代码质量检查
- **[docs]**: 文档生成

### 性能优势
- 比 pip 快 10-100 倍
- 智能缓存和并发安装
- 内存安全，Rust 编写

**详细使用指南**: 查看 `backend/UV_USAGE.md` 文件

### 前端开发
```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install
# 或使用 yarn
yarn install

# 开发服务器
npm run dev                     # 默认端口启动
npm run dev -- --port 3000     # 指定端口
npm run dev-host                # 监听所有接口

# 构建和预览
npm run build                   # 生产构建
npm run preview                 # 预览构建结果
npm run analyze                 # 构建分析

# 测试
npm run test                    # 运行所有测试
npm run test:unit               # 单元测试
npm run test:e2e                # 端到端测试
npm run test:coverage           # 带覆盖率测试

# 代码质量
npm run lint                    # ESLint检查
npm run lint -- --fix           # 自动修复
npm run format                  # Prettier格式化
npm run type-check              # TypeScript类型检查
```

### Docker 开发
```bash
# 使用 Docker Compose
cd deployment/docker
docker-compose up -d             # 启动所有服务
docker-compose logs -f backend   # 查看后端日志
docker-compose build backend     # 重建后端镜像

# 独立构建和运行
docker build -f deployment/docker/Dockerfile -t gap-backend .
docker run -p 8000:8000 --env-file .env gap-backend
```

## 核心架构

### 技术栈
- **后端**: FastAPI 0.116.1 + Uvicorn + Python 3.11
- **前端**: Vue 3.5.13 + TypeScript + Vite 6.0.3
- **数据库**: PostgreSQL (主), SQLite (备), Redis (缓存)
- **认证**: JWT + python-jose[cryptography]
- **HTTP客户端**: httpx (异步), requests (同步)
- **任务调度**: APScheduler 3.11.0
- **测试**: pytest (后端) + vitest + playwright (前端)

### 后端核心模块 (`backend/src/gap/core/`)

#### API 层 (`api/`)
- **endpoints.py**: OpenAI 兼容 API - `/v1/chat/completions`, `/v1/models`
- **v2_endpoints.py**: Gemini 原生 API - 直接代理 Google Gemini API
- **cache_endpoints.py**: 缓存管理 - 用户缓存查看、清理
- **config_endpoints.py**: 运行时配置管理

#### 核心业务逻辑
- **keys/manager.py**: API 密钥智能管理 - 轮换、健康评分、使用统计
- **processing/**: 请求处理管道
  - `main_handler.py`: 主请求处理器
  - `request_prep.py`: 请求预处理和格式转换
  - `api_caller.py`: HTTP API 调用逻辑
  - `post_processing.py`: 响应后处理
  - `key_selection.py`: 智能密钥选择算法
- **database/**: SQLAlchemy 异步 ORM 模型和会话管理
- **security/**: JWT 认证、速率限制、安全中间件
- **context/**: 对话上下文存储和管理
- **cache/**: Redis 缓存策略和 Gemini 原生缓存集成
- **reporting/**: 使用统计和健康监控

### 前端架构 (`frontend/src/`)

#### 核心结构
- **views/**: 页面级组件 - Dashboard, Key Management, Cache Management
- **components/**: Vue 组件 (common/ 通用, specific/ 特定功能)
- **stores/**: Pinia 状态管理
- **services/**: API 客户端层，统一 HTTP 请求处理
- **types/**: TypeScript 接口定义
- **router/**: Vue Router 配置

#### 关键功能模块
- **Dashboard**: 实时使用统计，ECharts 图表展示
- **Key Management**: API 密钥 CRUD 操作，健康状态监控
- **Cache Management**: Redis 缓存查看，用户缓存清理
- **Context Management**: 对话历史存储和检索

### 前后端通信
- **OpenAI 兼容接口**: `/v1/*` - 用于客户端兼容性
- **Gemini 原生接口**: `/v2/*` - 直接 Google API 访问
- **管理接口**: `/api/*` - 缓存、配置、用户管理
- **认证**: JWT Bearer Token 在 Authorization 头
- **格式**: RESTful API，JSON 请求/响应

## 关键配置

### 环境变量 (.env)
```bash
# 数据库配置
DATABASE_URL=postgresql://user:pass@localhost:5432/gap_dev
REDIS_URL=redis://localhost:6379/0

# 安全配置
SECRET_KEY=your-secret-key
JWT_SECRET_KEY=your-jwt-secret-key

# Gemini API
GEMINI_API_KEY=your-gemini-api-key

# 功能开关
DEBUG=true
LOG_LEVEL=DEBUG
ENABLE_DOCS=true
```

### 前端环境变量 (.env)
```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_DEV_MODE=true
VITE_ENABLE_ANALYTICS=false
```

## 数据库模式

### 主要模型
- **API Keys**: 存储和管理 Gemini API 密钥
- **Context**: 用户对话上下文和历史记录
- **Cache**: API 响应缓存和 Gemini 原生缓存
- **Users**: 用户账户和认证信息

### 迁移管理
使用 Alembic 进行数据库版本控制：
- 迁移文件位置: `backend/alembic/versions/`
- 配置文件: `backend/alembic.ini`

## 特殊注意事项

### 开发工作流
1. 后端开发优先：API 设计和核心逻辑先实现
2. 前后端分离：使用 OpenAPI/Swagger 进行接口定义
3. 测试驱动：新功能必须有对应测试用例
4. 代码审查：使用 ESLint + Prettier (前端)，black + mypy (后端)

### 性能优化
- **异步优先**: 后端全异步实现，注意协程管理
- **连接池**: 数据库和 HTTP 客户端都使用连接池
- **智能缓存**: 多层缓存策略 (Redis + Gemini 原生)
- **负载均衡**: API 密钥健康评分和智能轮换

### 安全考虑
- **JWT 认证**: 无状态 token 认证
- **多层限流**: IP 级和密钥级双重限流
- **数据隔离**: 用户级别数据隔离
- **安全头**: 使用 secure 模块添加安全 HTTP 头

### 部署相关
- **容器化**: Docker 镜像多阶段构建优化
- **反向代理**: 推荐使用 Nginx/Caddy
- **监控**: 集成 Sentry 错误追踪
- **日志**: 结构化日志 (structlog + loguru)

## 故障排除快速指南

### 常见问题
1. **数据库连接失败**: 检查 DATABASE_URL 和 PostgreSQL 服务状态
2. **Redis 连接失败**: 检查 REDIS_URL 和 Redis 服务状态
3. **API 密钥错误**: 验证 GEMINI_API_KEY 配置
4. **端口占用**: 使用 `lsof -i :8000` 查看占用的进程
5. **前端代理错误**: 检查 VITE_API_BASE_URL 配置

### 调试技巧
- **后端调试**: 设置 `LOG_LEVEL=DEBUG` 和 `SQLALCHEMY_ECHO=true`
- **前端调试**: 启用 Vue DevTools 和网络请求监控
- **性能分析**: 使用 `py-spy` 进行 Python 性能分析
- **内存泄漏**: 使用 GC 调试和对象追踪

### API 文档访问
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## 项目特有的开发模式

### API 密钥智能管理
系统实现了一套复杂的 API 密钥健康评分和轮换机制：
- **健康评分**: 基于成功率、响应时间、错误率
- **智能轮换**: 自动选择健康度最高的密钥
- **使用监控**: 实时统计 RPD/RPM/TPD/TPM 指标
- **故障恢复**: 自动检测和恢复失效密钥

### 请求处理管道
所有 API 请求都经过标准化的处理管道：
1. **请求验证**: 认证、限流、参数校验
2. **格式转换**: OpenAI 格式 ↔ Gemini 格式
3. **密钥选择**: 基于健康评分的智能选择
4. **API 调用**: 异步 HTTP 请求处理
5. **响应处理**: 格式转换、缓存、监控

### 缓存策略
多层缓存设计优化性能和成本：
- **本地缓存**: 内存级别快速缓存
- **Redis 缓存**: 分布式缓存，支持过期策略
- **Gemini 原生缓存**: 利用 Google 的缓存 API 减少成本