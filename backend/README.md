# GAP 后端服务

> Gemini API Proxy 后端 - 基于 FastAPI 的高性能异步 API 服务

## 🚀 快速开始

### 环境要求

- Python 3.8+
- PostgreSQL 12+
- Redis 6+

### 安装依赖

```bash
# 使用 uv (推荐)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建虚拟环境
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
uv pip install -r requirements.txt
```

### 环境配置

```bash
# 复制环境模板
cp ../.env.example ../.env

# 编辑配置文件
nano ../.env
```

### 数据库设置

```bash
# 创建数据库
createdb gap_dev

# 数据库迁移
uv run alembic upgrade head

# 或使用脚本
uv run ./scripts/migrate.sh
```

### 启动服务

```bash
# 开发模式
uvicorn src.gap.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn src.gap.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## 📁 项目结构

```
backend/
├── src/gap/                 # 主应用代码
│   ├── main.py             # FastAPI 应用入口
│   ├── config.py           # 配置管理
│   ├── api/                # API 端点
│   ├── core/               # 核心业务逻辑
│   │   ├── database/       # 数据库模型和工具
│   │   ├── keys/          # API密钥管理
│   │   ├── cache/         # Redis缓存管理
│   │   ├── security/      # JWT认证和安全
│   │   ├── processing/    # 请求处理逻辑
│   │   ├── reporting/     # 使用报告和统计
│   │   └── services/      # 外部服务集成
├── tests/                  # 测试文件
├── config/                 # 配置文件
├── scripts/               # 开发脚本
└── requirements.txt       # Python依赖
```

## 🔧 开发命令

### 运行测试

```bash
# 运行所有测试
pytest

# 运行单元测试
pytest tests/unit/

# 运行集成测试
pytest tests/integration/

# 运行带覆盖率的测试
pytest --cov=src --cov-report=html
```

### 代码质量

```bash
# 格式化代码
black src/
isort src/

# 类型检查
mypy src/

# 代码检查
flake8 src/
```

### 数据库操作

```bash
# 创建迁移
alembic revision --autogenerate -m "描述"

# 应用迁移
alembic upgrade head

# 回滚迁移
alembic downgrade -1

# 重置数据库
dropdb gap_dev && createdb gap_dev && alembic upgrade head
```

## 🏗️ 核心模块

### API 端点

- **/api/v1/** - OpenAI 兼容 API
- **/api/v2/** - Gemini 原生 API
- **/api/cache/** - 缓存管理 API
- **/admin/** - 管理接口

### 核心功能

- **密钥管理** - 多 API 密钥轮换和验证
- **缓存系统** - Redis 缓存策略
- **限流控制** - IP 和密钥级别的限流
- **使用统计** - 详细的 API 使用报告
- **上下文管理** - 对话历史存储
- **安全认证** - JWT 令牌系统

## 📊 环境变量

### 必需变量

```bash
# 数据库
DATABASE_URL=postgresql://user:pass@localhost:5432/gap_dev

# Redis
REDIS_URL=redis://localhost:6379/0

# 安全
SECRET_KEY=your-secret-key-here
JWT_SECRET_KEY=your-jwt-secret-key

# Gemini API（单 key 老字段，建议逐步迁移到 GEMINI_API_KEYS）
GEMINI_API_KEY=your-gemini-api-key

# Gemini API（推荐，多 key 池管理）
GEMINI_API_KEYS=sk-your-key-1,sk-your-key-2
```

### 可选变量

```bash
# 调试
DEBUG=true
LOG_LEVEL=DEBUG

# 限流
MAX_REQUESTS_PER_MINUTE=60
MAX_REQUESTS_PER_DAY_PER_IP=1000

# 功能开关
ENABLE_DOCS=true
DISABLE_SAFETY_FILTERING=false

# 运行模式 / 测试
APP_DB_MODE=memory          # memory 或 postgres/sqlite 等
TESTING=true                # 测试 / 压测场景下自动注入内存 key

# 认证相关
USERS_API_KEY=test_key       # 内存模式下的平台用户登录密钥，对应 Authorization: Bearer <USERS_API_KEY>
ADMIN_TOKEN=admin_token     # 管理员接口使用的独立 token
```

## 🔐 认证 / 密钥 / 模型校验概览

### 认证模式

- **内存模式（APP_DB_MODE=memory / IS_MEMORY_DB=True）**：
  - 普通请求通过 `Authorization: Bearer <USERS_API_KEY>` 认证；
  - USERS_API_KEY 会被加载到 `WEB_UI_PASSWORDS` 列表中，由 `verify_proxy_key` 校验；
  - 适用于开发 / 单机测试 / demo 环境。
- **数据库模式（非 memory）**：
  - Proxy key 存储在数据库中，由 `context_store.is_valid_proxy_key(...)` + `APIKeyManager` 校验；
  - 适用于生产和多用户场景。

### 密钥管理

- 使用 `APIKeyManager` 统一管理 Gemini API key：
  - 内存模式下可从 `GEMINI_API_KEYS` 环境变量加载一组 key，组成 key 池；
  - 生产环境通常通过数据库存储 key，并在管理界面维护；
  - 当 `TESTING=true` 且尚未初始化时，`get_key_manager` 会自动创建一个内存 key，避免 key 池为空导致 503。

### 模型校验与别名

- `/v1/chat/completions` 和 `/v2/models/{model}:generateContent` 共用同一套模型校验逻辑：
  - 所有模型名会通过 `validate_model_name` 做合法性检查和别名映射；
  - 常见别名如 `gemini-pro` 会被转换为当前真实模型名（例如 `gemini-*-pro`）；
  - 无效模型名会返回 400/404。
- `/v1/models` 的模型列表来源按优先级：
  1. 已加载的 `MODEL_LIMITS` 配置；
  2. 使用可用 key 调用 Gemini API 动态获取；
  3. 内置兜底模型列表，保证始终有可用输出。

## 🐳 Docker 开发

### 使用 Docker Compose

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f backend

# 重建镜像
docker-compose build backend
```

### 独立 Docker 运行

```bash
# 构建镜像
docker build -t gap-backend .

# 运行容器
docker run -p 8000:8000 --env-file ../.env gap-backend
```

## 🔍 调试指南

### 日志查看

```bash
# 实时查看日志
tail -f logs/app.log

# 查看错误日志
tail -f logs/error.log

# 查看访问日志
tail -f logs/access.log
```

### 性能监控

```bash
# 启用性能分析
python -m cProfile -o profile.prof src/gap/main.py

# 使用py-spy
py-spy top --pid $(pgrep -f "uvicorn")
```

## 📚 API 文档

启动服务后访问：

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI**: http://localhost:8000/openapi.json

## 🚨 故障排除

### 常见问题

1. **数据库连接失败** - 检查 DATABASE_URL 配置
2. **Redis 连接失败** - 检查 REDIS_URL 配置
3. **API 密钥无效** - 检查 GEMINI_API_KEY 配置
4. **端口占用** - 使用`lsof -i :8000`查找占用进程

### 调试模式

```bash
# 启用详细日志
export LOG_LEVEL=DEBUG

# 启用SQL日志
export SQLALCHEMY_ECHO=true
```

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支：`git checkout -b feature/amazing-feature`
3. 提交更改：`git commit -m 'Add amazing feature'`
4. 推送分支：`git push origin feature/amazing-feature`
5. 创建 Pull Request

## 📞 支持

- **Issues**: [GitHub Issues](https://github.com/MisonL/GAP/issues)
- **Discussions**: [GitHub Discussions](https://github.com/MisonL/GAP/discussions)
- **Email**: 1360962086@qq.com
