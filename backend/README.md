# GAP 后端服务

> Gemini API Proxy 后端 - 基于 FastAPI 的高性能异步 API 服务

## 🚀 快速开始

### 环境要求
- Python 3.8+
- PostgreSQL 12+
- Redis 6+

### 安装依赖
```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 或使用 uv (推荐)
pip install uv
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

# 运行迁移
alembic upgrade head

# 或使用脚本
./scripts/migrate.sh
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

### API端点
- **/api/v1/** - OpenAI兼容API
- **/api/v2/** - Gemini原生API
- **/api/cache/** - 缓存管理API
- **/admin/** - 管理接口

### 核心功能
- **密钥管理** - 多API密钥轮换和验证
- **缓存系统** - Redis缓存策略
- **限流控制** - IP和密钥级别的限流
- **使用统计** - 详细的API使用报告
- **上下文管理** - 对话历史存储
- **安全认证** - JWT令牌系统

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

# Gemini API
GEMINI_API_KEY=your-gemini-api-key
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
```

## 🐳 Docker开发

### 使用Docker Compose
```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f backend

# 重建镜像
docker-compose build backend
```

### 独立Docker运行
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

## 📚 API文档

启动服务后访问：
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI**: http://localhost:8000/openapi.json

## 🚨 故障排除

### 常见问题
1. **数据库连接失败** - 检查DATABASE_URL配置
2. **Redis连接失败** - 检查REDIS_URL配置
3. **API密钥无效** - 检查GEMINI_API_KEY配置
4. **端口占用** - 使用`lsof -i :8000`查找占用进程

### 调试模式
```bash
# 启用详细日志
export LOG_LEVEL=DEBUG

# 启用SQL日志
export SQLALCHEMY_ECHO=true
```

## 🤝 贡献指南

1. Fork项目
2. 创建功能分支：`git checkout -b feature/amazing-feature`
3. 提交更改：`git commit -m 'Add amazing feature'`
4. 推送分支：`git push origin feature/amazing-feature`
5. 创建Pull Request

## 📞 支持

- **Issues**: [GitHub Issues](https://github.com/MisonL/GAP/issues)
- **Discussions**: [GitHub Discussions](https://github.com/MisonL/GAP/discussions)
- **Email**: 1360962086@qq.com