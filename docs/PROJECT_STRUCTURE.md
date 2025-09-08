# GAP 项目结构文档

本文档描述了 GAP (Gemini API Proxy) 项目的优化目录结构。

## 📁 目录总览

```
GAP/
├── 📄 readme.md                 # 项目概览和快速开始
├── 📄 changelog.md              # 版本历史和变更记录
├── 📄 deploy.sh                 # 一键部署脚本
├── 📄 LICENSE                   # MIT许可证
├── 📄 LICENSE.zh-CN             # 中文MIT许可证
├── 📄 .gitignore               # Git忽略规则
├── 📄 .env.example             # 环境变量模板
├── 📁 backend/                 # 后端API服务
├── 📁 frontend/                # 前端Web应用
├── 📁 deployment/              # 部署配置
├── 📁 docs/                    # 项目文档
├── 📁 logs/                    # 应用日志
└── 📁 tools/                   # 开发工具
```

## 🏗️ 后端结构

```
backend/
├── 📁 src/
│   └── 📁 gap/
│       ├── 📄 __init__.py
│       ├── 📄 main.py          # FastAPI应用入口
│       ├── 📄 config.py        # 配置管理
│       ├── 📁 api/             # API端点
│       │   ├── 📄 __init__.py
│       │   ├── 📄 endpoints.py
│       │   ├── 📄 v2_endpoints.py
│       │   ├── 📄 cache_endpoints.py
│       │   └── 📁 admin/
│       ├── 📁 core/            # 核心业务逻辑
│       │   ├── 📄 __init__.py
│       │   ├── 📄 dependencies.py
│       │   ├── 📄 tracking.py
│       │   ├── 📁 cache/
│       │   │   ├── 📄 __init__.py
│       │   │   ├── 📄 manager.py
│       │   │   └── 📄 cleanup.py
│       │   ├── 📁 context/
│       │   │   ├── 📄 __init__.py
│       │   │   ├── 📄 store.py
│       │   │   └── 📄 converter.py
│       │   ├── 📁 database/
│       │   │   ├── 📄 __init__.py
│       │   │   ├── 📄 models.py
│       │   │   ├── 📄 settings.py
│       │   │   └── 📄 utils.py
│       │   ├── 📁 keys/
│       │   │   ├── 📄 __init__.py
│       │   │   ├── 📄 manager.py
│       │   │   ├── 📄 checker.py
│       │   │   └── 📄 utils.py
│       │   ├── 📁 processing/
│       │   │   ├── 📄 __init__.py
│       │   │   ├── 📄 main_handler.py
│       │   │   ├── 📄 stream_handler.py
│       │   │   ├── 📄 error_handler.py
│       │   │   └── 📄 utils.py
│       │   ├── 📁 reporting/
│       │   │   ├── 📄 __init__.py
│       │   │   ├── 📄 reporter.py
│       │   │   ├── 📄 scheduler.py
│       │   │   └── 📄 daily_reset.py
│       │   ├── 📁 security/
│       │   │   ├── 📄 __init__.py
│       │   │   ├── 📄 jwt.py
│       │   │   ├── 📄 rate_limit.py
│       │   │   └── 📄 auth_dependencies.py
│       │   ├── 📁 services/
│       │   │   ├── 📄 __init__.py
│       │   │   └── 📄 gemini.py
│       │   └── 📁 utils/
│       │       ├── 📄 __init__.py
│       │       ├── 📄 request_helpers.py
│       │       └── 📄 response_wrapper.py
├── 📁 tests/
│   ├── 📁 unit/
│   └── 📁 integration/
├── 📁 config/
│   ├── 📄 settings.py
│   └── 📄 logging.py
├── 📁 scripts/
│   ├── 📄 dev_server.sh
│   ├── 📄 test.sh
│   └── 📄 migrate.sh
├── 📄 requirements.txt
├── 📄 pyproject.toml
└── 📄 uv.lock
```

## 🎨 前端结构

```
frontend/
├── 📁 src/
│   ├── 📄 main.js
│   ├── 📄 App.vue
│   ├── 📁 assets/
│   ├── 📁 components/
│   │   ├── 📁 common/
│   │   └── 📁 specific/
│   ├── 📁 composables/
│   ├── 📁 constants/
│   ├── 📁 layouts/
│   ├── 📁 router/
│   ├── 📁 services/
│   ├── 📁 stores/
│   ├── 📁 types/
│   └── 📁 views/
├── 📁 public/
│   ├── 📄 index.html
│   └── 📄 favicon.ico
├── 📁 tests/
├── 📁 scripts/
│   ├── 📄 build.sh
│   └── 📄 dev.sh
├── 📄 package.json
├── 📄 package-lock.json
├── 📄 vite.config.js
├── 📄 tsconfig.json
└── 📄 playwright.config.js
```

## 🚀 部署结构

```
deployment/
├── 📁 docker/
│   ├── 📄 Dockerfile
│   ├── 📄 Dockerfile.simple
│   ├── 📄 docker-compose.yml
│   ├── 📄 .dockerignore
│   └── 📄 README.md
├── 📁 k8s/
│   ├── 📄 deployment.yaml
│   ├── 📄 service.yaml
│   ├── 📄 configmap.yaml
│   └── 📄 ingress.yaml
└── 📁 scripts/
    ├── 📄 setup.sh
    └── 📄 health-check.sh
```

## 📚 文档结构

```
docs/
├── 📁 api/
│   ├── 📄 openapi.yaml
│   └── 📄 endpoints.md
├── 📁 deployment/
│   ├── 📄 docker.md
│   ├── 📄 kubernetes.md
│   └── 📄 environment-setup.md
├── 📁 development/
│   ├── 📄 setup.md
│   ├── 📄 contributing.md
│   └── 📄 architecture.md
├── 📁 licenses/
│   ├── 📄 LICENSE
│   └── 📄 LICENSE.zh-CN
└── 📄 PROJECT_STRUCTURE.md
```

## 🔧 工具结构

```
tools/
├── 📄 api-key-generator.html    # API密钥生成工具
├── 📄 db-migrate.py            # 数据库迁移脚本
├── 📄 log-analyzer.py          # 日志分析工具
└── 📄 performance-test.py      # 性能测试脚本
```

## 📊 日志结构

```
logs/
├── 📄 app.log                  # 主应用程序日志
├── 📄 error.log                # 错误日志
├── 📄 access.log               # API访问日志
└── 📁 archives/               # 归档日志
```

## 🎯 核心特性

### 后端
- **FastAPI** 异步框架支持
- **SQLAlchemy** ORM与数据库迁移
- **Redis** 缓存层
- **JWT** 身份验证
- **限流** 和安全中间件
- **全面日志** 和监控

### 前端
- **Vue 3** 组合式API
- **Vite** 构建工具
- **TypeScript** 支持
- **响应式设计** 支持移动端
- **实时更新** WebSocket支持

### 开发
- **热重载** 前后端支持
- **全面测试** pytest和Playwright
- **代码格式化** black和prettier
- **类型检查** mypy和TypeScript
- **Docker** 一致环境支持

## 🚀 快速开始

1. **后端启动**:
   ```bash
   cd backend
   pip install -r requirements.txt
   uvicorn src.gap.main:app --reload
   ```

2. **前端启动**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

3. **Docker启动**:
   ```bash
   docker-compose up -d
   ```

## 📋 环境变量

查看 `.env.example` 获取所需环境变量:
- `DATABASE_URL`: PostgreSQL连接字符串
- `REDIS_URL`: Redis连接字符串
- `SECRET_KEY`: JWT密钥
- `GEMINI_API_KEY`: Google Gemini API密钥
- `LOG_LEVEL`: 日志级别 (DEBUG, INFO, WARNING, ERROR)

## 📞 联系与支持

- **邮箱**: 1360962086@qq.com
- **Issues**: [GitHub Issues](https://github.com/MisonL/GAP/issues)
- **Discussions**: [GitHub Discussions](https://github.com/MisonL/GAP/discussions)