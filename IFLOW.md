# GAP (Gemini API Proxy) - iFlow 项目指南

## 项目概述

**GAP** 是一个基于 FastAPI 构建的 Gemini API 代理服务，提供 OpenAI 兼容接口和 Gemini 原生接口，支持多 API 密钥轮换、使用情况跟踪、上下文管理和缓存功能。

### 核心特性
- **多接口支持**: OpenAI 兼容 API (`/v1`) 和 Gemini 原生 API (`/v2`)
- **智能密钥管理**: 多 API 密钥轮换、健康度评分、自动失效检测
- **上下文管理**: 对话历史存储、原生缓存支持、TTL 管理
- **使用统计**: 实时 API 使用情况跟踪和报告
- **Web 管理界面**: Vue.js 单页应用，支持密钥、缓存、上下文管理
- **安全认证**: JWT 令牌系统、IP 速率限制
- **现代化部署**: 支持 Docker 和本地 uv 部署

## 技术栈

### 后端
- **框架**: FastAPI 0.116+ (Python 3.9+)
- **包管理**: uv (现代化 Python 包管理器)
- **数据库**: SQLite (默认) / PostgreSQL (可选)
- **缓存**: Redis (可选)
- **异步**: asyncio + httpx
- **认证**: JWT + OAuth2
- **测试**: pytest + pytest-asyncio

### 前端
- **框架**: Vue 3.5+ + TypeScript 5.6+
- **构建工具**: Vite 6.0+
- **UI 库**: Element Plus 2.9+ + Tailwind CSS 3.4+
- **状态管理**: Pinia 2.3+
- **图表**: ECharts 5.5+ + Chart.js 4.4+
- **工具库**: VueUse 12.0+ + Day.js 1.11+
- **测试**: Vitest + Playwright

## 项目结构

```
GAP/
├── backend/                    # FastAPI 后端服务
│   ├── src/gap/
│   │   ├── main.py            # 应用入口
│   │   ├── config.py          # 配置管理
│   │   ├── api/               # API 端点
│   │   │   ├── endpoints.py   # OpenAI 兼容 API
│   │   │   ├── v2_endpoints.py # Gemini 原生 API
│   │   │   ├── cache_endpoints.py # 缓存管理
│   │   │   └── config_endpoints.py # 配置管理
│   │   ├── core/              # 核心业务逻辑
│   │   │   ├── keys/          # API 密钥管理
│   │   │   ├── cache/         # 缓存系统
│   │   │   ├── context/       # 上下文管理
│   │   │   ├── database/      # 数据库模型
│   │   │   ├── security/      # 安全认证
│   │   │   ├── processing/    # 请求处理
│   │   │   ├── reporting/     # 使用报告和统计
│   │   │   └── services/      # 外部服务集成
│   │   └── utils/             # 工具函数
│   ├── pyproject.toml         # Python 依赖配置 (uv)
│   ├── requirements.txt       # 传统依赖文件
│   └── uv.lock               # uv 锁文件
├── frontend/                  # Vue.js 前端应用
│   ├── src/
│   │   ├── components/        # Vue 组件
│   │   ├── views/            # 页面视图
│   │   ├── stores/           # Pinia 状态管理
│   │   ├── services/         # API 服务层
│   │   ├── types/            # TypeScript 类型定义
│   │   ├── composables/      # 组合式函数
│   │   ├── constants/        # 常量定义
│   │   └── assets/           # 静态资源
│   ├── package.json          # Node.js 依赖配置
│   ├── vite.config.js        # Vite 配置
│   ├── tailwind.config.js    # Tailwind 配置
│   └── tsconfig.json         # TypeScript 配置
├── deployment/               # 部署配置
│   ├── docker/              # Docker 配置
│   │   ├── docker-compose.yml
│   │   ├── Dockerfile
│   │   └── Dockerfile.simple
│   └── scripts/             # 部署脚本
├── docs/                    # 项目文档
├── logs/                    # 日志文件
├── tools/                   # 工具脚本
├── .env.example             # 环境变量模板
├── deploy.sh               # 一键部署脚本
├── start.sh                # 启动脚本
└── changelog.md            # 更新日志
```

## 快速开始

### 1. 环境准备

#### 系统要求
- **Docker 模式**: Docker 20.10+ 和 Docker Compose 2.0+
- **本地模式**: Python 3.9+ 和 Node.js 18+
- **包管理器**: uv (Python) 和 npm (Node.js)

#### 克隆项目
```bash
git clone https://github.com/MisonL/GAP.git
cd GAP
```

### 2. 配置环境变量

```bash
# 复制环境模板
cp .env.example .env

# 编辑配置文件
nano .env
```

**必需配置**:
```bash
# JWT 密钥 - 必须设置强随机字符串
SECRET_KEY=your_very_strong_random_secret_key_here

# Gemini API 密钥
GEMINI_API_KEYS=your_gemini_api_key_1,your_gemini_api_key_2

# Web UI 登录密码
PASSWORD=your_web_ui_password
```

**可选配置**:
```bash
# 数据库配置
DATABASE_URL=sqlite+aiosqlite:///./data/context_store.db

# Redis 配置 (可选)
REDIS_URL=redis://localhost:6379/0

# 存储模式
KEY_STORAGE_MODE=memory  # 或 database
CONTEXT_STORAGE_MODE=memory  # 或 database

# 功能开关
ENABLE_NATIVE_CACHING=false
ENABLE_CONTEXT_COMPLETION=true

# 限流设置
MAX_REQUESTS_PER_MINUTE=60
MAX_REQUESTS_PER_DAY_PER_IP=600
```

### 3. 一键部署

#### Docker 部署（推荐）
```bash
# 一键部署
./deploy.sh docker

# 或简写
./deploy.sh

# 交互式菜单
./deploy.sh  # 无参数进入交互式菜单
```

#### 本地 uv 部署
```bash
# 本地 uv 部署
./deploy.sh local

# 停止所有服务
./deploy.sh stop
```

### 4. 访问服务

- **Web UI**: http://localhost:7860
- **API 文档**: http://localhost:7860/docs
- **健康检查**: http://localhost:7860/healthz

## 开发指南

### 后端开发

#### 安装依赖 (使用 uv)
```bash
cd backend

# 创建虚拟环境
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
uv pip install -r requirements.txt

# 安装开发依赖
uv pip install -r requirements.txt --extra dev
```

#### 启动开发服务器
```bash
# 开发模式
uvicorn src.gap.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn src.gap.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### 运行测试
```bash
# 运行所有测试
pytest

# 运行带覆盖率的测试
pytest --cov=src --cov-report=html

# 代码质量检查
black src/
isort src/
mypy src/
```

### 前端开发

#### 安装依赖
```bash
cd frontend

# 安装依赖
npm install

# 或使用更快的包管理器
npm install --prefer-offline
```

#### 启动开发服务器
```bash
# 开发模式
npm run dev

# 指定端口
npm run dev -- --port 3000

# 开发模式并监听所有接口
npm run dev-host
```

#### 构建和测试
```bash
# 构建生产版本
npm run build

# 预览构建结果
npm run preview

# 运行测试
npm run test:unit
npm run test:e2e

# 代码质量检查
npm run lint
npm run format
npm run type-check

# 构建分析
npm run analyze
```

## API 接口

### OpenAI 兼容接口 (`/v1`)

#### 获取模型列表
```bash
GET /v1/models
Authorization: Bearer your_api_key
```

#### 聊天补全
```bash
POST /v1/chat/completions
Authorization: Bearer your_api_key
Content-Type: application/json

{
  "model": "gemini-1.5-pro-latest",
  "messages": [
    {"role": "user", "content": "你好！"}
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "stream": false
}
```

### Gemini 原生接口 (`/v2`)

#### 生成内容
```bash
POST /v2/models/gemini-1.5-pro-latest:generateContent
Authorization: Bearer your_api_key
Content-Type: application/json

{
  "contents": [
    {
      "role": "user",
      "parts": [{"text": "你好！"}]
    }
  ],
  "generationConfig": {
    "temperature": 0.7,
    "maxOutputTokens": 1024,
    "topP": 0.8,
    "topK": 40
  }
}
```

### 缓存管理接口

#### 获取用户缓存
```bash
GET /api/v1/caches
Authorization: Bearer your_api_key
```

#### 删除缓存
```bash
DELETE /api/v1/caches/{cache_id}
Authorization: Bearer your_api_key
```

### 配置管理接口

#### 获取系统配置
```bash
GET /api/v1/config
Authorization: Bearer your_api_key
```

#### 更新配置
```bash
PUT /api/v1/config
Authorization: Bearer your_api_key
Content-Type: application/json

{
  "max_requests_per_minute": 100,
  "enable_native_caching": true
}
```

## 配置说明

### 环境变量详解

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `SECRET_KEY` | JWT 加密密钥 | 必需 | `your-secret-key-here` |
| `GEMINI_API_KEYS` | Gemini API 密钥列表 | 必需 | `key1,key2,key3` |
| `PASSWORD` | Web UI 登录密码 | 必需 | `your-password` |
| `DATABASE_URL` | 数据库连接字符串 | SQLite | `postgresql://...` |
| `REDIS_URL` | Redis 连接字符串 | 可选 | `redis://localhost:6379/0` |
| `KEY_STORAGE_MODE` | API 密钥存储模式 | `memory` | `memory` / `database` |
| `CONTEXT_STORAGE_MODE` | 上下文存储模式 | `memory` | `memory` / `database` |
| `ENABLE_NATIVE_CACHING` | 启用原生缓存 | `false` | `true` / `false` |
| `MAX_REQUESTS_PER_MINUTE` | 每分钟最大请求数 | `60` | `100` |
| `MAX_REQUESTS_PER_DAY_PER_IP` | 每日每 IP 最大请求数 | `600` | `1000` |

### 存储模式

#### 内存模式 (`memory`)
- **优点**: 快速、无需持久化存储、零配置
- **缺点**: 重启后数据丢失
- **适用**: 开发环境、测试环境、Hugging Face Spaces

#### 数据库模式 (`database`)
- **优点**: 数据持久化、支持多用户、可扩展
- **缺点**: 需要数据库配置
- **适用**: 生产环境、长期运行、多用户场景

## 部署模式

### Docker 部署

#### 一键部署
```bash
# 标准部署
./deploy.sh docker

# 查看状态
docker-compose -f deployment/docker/docker-compose.yml ps

# 查看日志
docker-compose -f deployment/docker/docker-compose.yml logs -f

# 停止服务
docker-compose -f deployment/docker/docker-compose.yml down
```

#### Docker 服务管理
```bash
# 清理旧容器和镜像
docker system prune -a

# 查看资源使用
docker stats

# 强制重启
docker-compose -f deployment/docker/docker-compose.yml restart
```

### 本地部署

#### 一键部署
```bash
# 本地 uv 部署
./deploy.sh local

# 手动启动后端
cd backend && source .venv/bin/activate && uvicorn src.gap.main:app --reload

# 手动启动前端
cd frontend && npm run dev
```

#### 本地服务管理
```bash
# 查看进程
ps aux | grep gap

# 查看日志
tail -f logs/backend.log
tail -f logs/frontend.log

# 停止服务
./deploy.sh stop
```

### 生产部署

#### 使用 Nginx 反向代理
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://localhost:7860;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
    }
}
```

#### 使用 HTTPS (Let's Encrypt)
```bash
# 安装 certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# 自动续期
sudo crontab -e
# 添加: 0 12 * * * /usr/bin/certbot renew --quiet
```

## 故障排除

### 常见问题

#### 端口冲突
```bash
# 检查端口占用
sudo lsof -i :7860
sudo lsof -i :8000
sudo lsof -i :3000

# 强制清理占用进程
./deploy.sh stop
```

#### 依赖问题
```bash
# 清理并重新安装后端依赖
rm -rf backend/.venv
cd backend && uv venv && source .venv/bin/activate && uv pip install -r requirements.txt

# 清理并重新安装前端依赖
rm -rf frontend/node_modules frontend/package-lock.json
cd frontend && npm install
```

#### 数据库问题
```bash
# 重置数据库（开发环境）
rm backend/src/gap/data/context_store.db
cd backend && python -c "
import asyncio
from gap.core.database.models import Base
from gap.core.database.settings import engine
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
asyncio.run(init_db())
"
```

### 日志查看

#### Docker 日志
```bash
# 实时查看所有日志
docker-compose -f deployment/docker/docker-compose.yml logs -f

# 查看特定服务日志
docker-compose -f deployment/docker/docker-compose.yml logs -f backend
docker-compose -f deployment/docker/docker-compose.yml logs -f frontend
```

#### 本地日志
```bash
# 后端日志
tail -f logs/backend.log
tail -f logs/app.log
tail -f logs/error.log

# 前端日志
tail -f logs/frontend.log
```

## 监控和维护

### 健康检查
```bash
# 检查服务状态
curl http://localhost:7860/healthz

# 检查 API 状态
curl -H "Authorization: Bearer your_api_key" http://localhost:7860/v1/models

# 检查数据库连接
curl http://localhost:8000/healthz
```

### 性能监控
```bash
# Docker 资源使用
docker stats

# 系统资源监控
htop

# 查看进程资源使用
ps aux | grep gap
```

### 定期维护
```bash
# 清理旧日志
find logs/ -name "*.log.*" -mtime +7 -delete

# 清理 Docker 镜像
docker system prune -a

# 更新依赖
cd backend && source .venv/bin/activate && uv pip install -U -r requirements.txt
cd ../frontend && npm update

# 清理 npm 缓存
npm cache clean --force
```

## 开发工具

### 代码质量工具

#### 后端
```bash
# 代码格式化
black src/
isort src/

# 类型检查
mypy src/

# 运行测试
pytest tests/ -v
```

#### 前端
```bash
# 代码检查
npm run lint

# 自动修复
npm run lint -- --fix

# 格式化代码
npm run format

# 运行测试
npm run test:unit
npm run test:e2e
```

### 调试工具

#### 后端调试
```bash
# 启用调试模式
export DEBUG=true
export LOG_LEVEL=DEBUG

# 使用调试器
python -m debugpy --listen 0.0.0.0:5678 src/gap/main.py
```

#### 前端调试
```bash
# 启用 Vue DevTools
npm run dev -- --mode development

# 性能分析
npm run analyze
```

## 贡献指南

### 开发规范
1. **代码风格**: 遵循 PEP 8 (Python) 和 ESLint (JavaScript)
2. **提交信息**: 使用 Conventional Commits
3. **测试**: 保持测试覆盖率 > 80%
4. **文档**: 更新相关文档
5. **分支管理**: 使用 feature/ 前缀创建功能分支

### 提交格式
```bash
# 功能提交
git commit -m "feat: add new feature"

# 修复提交
git commit -m "fix: resolve bug in API"

# 文档提交
git commit -m "docs: update README"

# 重构提交
git commit -m "refactor: improve code structure"
```

### 开发流程
```bash
# 1. Fork 项目
# 2. 创建功能分支
git checkout -b feature/amazing-feature

# 3. 开发并测试
# 4. 提交更改
git add .
git commit -m "feat: add amazing feature"

# 5. 推送分支
git push origin feature/amazing-feature

# 6. 创建 Pull Request
```

## 许可证

本项目采用 **知识共享署名-非商业性使用 4.0 国际许可协议** (CC BY-NC 4.0)。

## 支持

- **Issues**: [GitHub Issues](https://github.com/MisonL/GAP/issues)
- **Discussions**: [GitHub Discussions](https://github.com/MisonL/GAP/discussions)
- **邮箱**: 1360962086@qq.com

## 快速命令参考

| 命令 | 说明 |
|------|------|
| `./deploy.sh` | Docker 一键部署 |
| `./deploy.sh local` | 本地 uv 部署 |
| `./deploy.sh stop` | 停止所有服务 |
| `npm run dev` | 启动前端开发服务器 |
| `uvicorn src.gap.main:app --reload` | 启动后端开发服务器 |
| `pytest` | 运行后端测试 |
| `npm run test:unit` | 运行前端单元测试 |
| `npm run build` | 构建前端生产版本 |
| `docker-compose logs -f` | 查看 Docker 日志 |