# 🚀 GAP (Gemini API Proxy)

[![许可证: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)

一个现代化的 Gemini API 代理服务，基于 FastAPI + Vue.js 构建，提供安全、可配置的 Google Gemini 模型访问方式。项目采用单体仓库架构，支持容器化部署和开发环境热重载。

## ✨ 主要功能

### 🔑 API 密钥管理
- **智能密钥轮询**: 自动在多个 Gemini API 密钥间轮换，确保负载均衡
- **健康度评估**: 实时监控每个密钥的使用情况、错误率和响应时间
- **配额管理**: 支持 RPD/RPM/TPD/TPM 限制，智能选择最优密钥
- **故障转移**: 自动禁用失效密钥，恢复后重新启用

### 🔄 多接口支持
- **OpenAI 兼容接口** (`/v1`): 完全兼容 OpenAI API 格式，无缝接入现有工具
- **Gemini 原生接口** (`/v2`): 直接代理 Gemini generateContent API，保持原生特性
- **统一认证**: JWT Token + Bearer Token 双重认证支持

### 💾 智能缓存系统
- **原生缓存支持**: 完整支持 Gemini 的原生缓存机制
- **上下文管理**: 智能管理对话上下文，自动截断防止超限
- **多层缓存**: 内存 + Redis 双层缓存架构
- **自动清理**: 定时清理过期缓存和无效数据

### 📊 实时监控
- **使用统计**: 详细的请求量、Token使用量、成本分析
- **性能监控**: 响应时间、成功率、错误分布实时展示
- **可视化仪表板**: 基于 ECharts 的美观数据展示

### 🛡️ 安全特性
- **速率限制**: IP 级和 Key 级的精细化速率控制
- **安全过滤**: 可配置的内容安全策略
- **JWT 认证**: 安全的 Web UI 访问控制
- **密钥保护**: 管理员密钥和用户密钥分离管理

## 📁 项目结构

```
GAP/
├── backend/                # FastAPI 后端服务
│   ├── src/gap/           # 核心业务逻辑
│   │   ├── api/          # API 路由层
│   │   ├── core/         # 核心业务模块
│   │   │   ├── database/  # 数据库模型
│   │   │   ├── keys/      # 密钥管理
│   │   │   ├── context/   # 上下文管理
│   │   │   ├── cache/     # 缓存系统
│   │   │   └── security/  # 安全认证
│   │   ├── main.py       # 应用入口
│   │   └── config.py     # 配置管理
│   ├── requirements.txt  # Python 依赖
│   └── Dockerfile       # 后端容器配置
├── frontend/              # Vue.js 前端应用
│   ├── src/             # 源代码
│   │   ├── views/       # 页面组件
│   │   ├── components/  # 可复用组件
│   │   ├── stores/      # 状态管理
│   │   └── services/    # API 服务
│   ├── package.json     # Node.js 依赖
│   └── vite.config.js   # 构建配置
├── deployment/            # 部署配置
│   └── docker/          # Docker 相关文件
├── docs/                 # 项目文档
├── logs/                 # 日志文件目录
├── .env.example         # 环境变量模板
├── docker-compose.yml   # 容器编排
└── deploy.sh           # 一键部署脚本
```

## 🚀 快速开始

### 方式一：Docker 一键部署（推荐）

```bash
# 1. 克隆项目
git clone <repository-address>
cd GAP

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，设置必要的配置

# 3. 一键启动
./deploy.sh docker

# 4. 访问服务
# API 文档: http://localhost:7860/docs
# Web 界面: http://localhost:7860
```

### 方式二：本地开发环境

#### 后端服务

```bash
# 1. 进入后端目录
cd backend

# 2. 创建虚拟环境（推荐使用 uv）
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安装依赖
uv pip install -r requirements.txt

# 4. 配置环境变量
cp ../.env.example ../.env
# 编辑 .env 文件

# 5. 启动服务
uvicorn src.gap.main:app --reload --host 0.0.0.0 --port 8000
```

#### 前端服务

```bash
# 1. 进入前端目录
cd frontend

# 2. 安装依赖
npm install

# 3. 配置环境变量
echo "VITE_API_BASE_URL=http://localhost:8000" > .env.local

# 4. 启动开发服务器
npm run dev
```

### 快速验证

```bash
# 健康检查
curl http://localhost:7860/healthz

# 获取模型列表
curl -H "Authorization: Bearer YOUR_API_KEY" \
     http://localhost:7860/v1/models

# 测试对话（OpenAI 格式）
curl -X POST http://localhost:7860/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
       "model": "gemini-2.0-flash-exp",
       "messages": [{"role": "user", "content": "Hello!"}]
     }'
```

## ⚙️ 配置说明

### 核心配置

在项目根目录创建 `.env` 文件：

```dotenv
# 必需配置
SECRET_KEY=your_very_strong_random_secret_key_here

# API 密钥配置
GEMINI_API_KEYS=key1,key2,key3  # 逗号分隔的密钥列表
KEY_STORAGE_MODE=memory         # 或 database

# 数据库配置（可选）
DATABASE_URL=sqlite:///./data/gap.db
REDIS_URL=redis://localhost:6379

# 认证配置
ADMIN_API_KEY=admin_key_here    # 管理员密钥
PASSWORD=web_password1,pass2    # Web UI 登录密码

# 功能开关
ENABLE_NATIVE_CACHING=true      # 启用原生缓存
ENABLE_CONTEXT_COMPLETION=true  # 启用上下文补全
DISABLE_SAFETY_FILTERING=false  # 禁用安全过滤（谨慎）

# 速率限制
MAX_REQUESTS_PER_MINUTE=60     # 每分钟最大请求数
MAX_REQUESTS_PER_DAY_PER_IP=600 # 每日最大请求数
```

### 高级配置

```dotenv
# 上下文管理
DEFAULT_MAX_CONTEXT_TOKENS=30000
CONTEXT_TOKEN_SAFETY_MARGIN=200
DEFAULT_CONTEXT_TTL_DAYS=7

# JWT 配置
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# 监控配置
USAGE_REPORT_INTERVAL_MINUTES=30
CACHE_REFRESH_INTERVAL_SECONDS=600
```

## 🔌 API 使用

### OpenAI 兼容接口

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:7860/v1",
    api_key="your_api_key"
)

response = client.chat.completions.create(
    model="gemini-2.0-flash-exp",
    messages=[
        {"role": "user", "content": "解释一下量子计算"}
    ]
)

print(response.choices[0].message.content)
```

### Gemini 原生接口

```python
import requests

response = requests.post(
    "http://localhost:7860/v2/models/gemini-2.0-flash-exp:generateContent",
    headers={
        "Authorization": "Bearer your_api_key",
        "Content-Type": "application/json"
    },
    json={
        "contents": [{
            "parts": [{"text": "解释一下量子计算"}]
        }]
    }
)

print(response.json())
```

## 📊 监控和管理

### Web UI 功能

- **仪表板**: 实时系统状态和使用统计
- **密钥管理**: 添加、编辑、删除 API 密钥，查看使用情况
- **缓存管理**: 查看和管理缓存内容
- **上下文管理**: 管理对话上下文和历史记录
- **系统配置**: 在线修改系统配置
- **日志查看**: 实时查看系统日志

### API 管理接口

```bash
# 获取系统状态
curl http://localhost:7860/api/v1/status

# 获取使用统计
curl -H "Authorization: Bearer admin_key" \
     http://localhost:7860/api/v1/stats

# 管理密钥
curl -X POST http://localhost:7860/api/v1/keys \
     -H "Authorization: Bearer admin_key" \
     -H "Content-Type: application/json" \
     -d '{"key": "new_key", "name": "Key 1"}'
```

## 🐳 Docker 部署

### 使用 Docker Compose

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 自定义构建

```bash
# 构建镜像
docker build -t gap-backend -f deployment/docker/Dockerfile .

# 运行容器
docker run -d \
  --name gap-server \
  -p 7860:7860 \
  --env-file .env \
  gap-backend
```

## 🧪 开发指南

### 后端开发

```bash
cd backend

# 代码格式化
black src/
isort src/

# 类型检查
mypy src/

# 运行测试
pytest

# 生成测试覆盖率报告
pytest --cov=src --cov-report=html
```

### 前端开发

```bash
cd frontend

# 代码检查
npm run lint

# 自动修复
npm run lint -- --fix

# 格式化代码
npm run format

# 类型检查
npm run type-check

# 运行测试
npm run test

# 构建生产版本
npm run build
```

## 📋 API 参考

详细 API 文档请访问：
- Swagger UI: `http://localhost:7860/docs`
- ReDoc: `http://localhost:7860/redoc`

### 核心端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/healthz` | GET | 健康检查 |
| `/v1/models` | GET | 获取模型列表 |
| `/v1/chat/completions` | POST | OpenAI 兼容对话 |
| `/v2/models/{model}:generateContent` | POST | Gemini 原生接口 |
| `/api/v1/status` | GET | 系统状态 |
| `/api/v1/caches` | GET/POST | 缓存管理 |

## 🤝 贡献指南

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 许可证

本项目采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 许可证。

## 🆘 支持

- 📖 [详细文档](docs/)
- 🐛 [问题反馈](issues)
- 💬 [讨论区](discussions)

---

⭐ 如果这个项目对你有帮助，请给个 Star！