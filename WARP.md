# WARP.md

本文件为 WARP (warp.dev) 在此代码仓库中工作时提供指导。

## 项目概览和关键文档

此仓库是 **GAP (Gemini API Proxy)** 的单体仓库：

- **后端（Backend）**: 位于 `backend/` 的基于 FastAPI 的 API 服务。
- **前端（Frontend）**: 位于 `frontend/` 的 Vue 3 + TypeScript 单页应用。
- **部署（Deployment）**: 位于 `deployment/` 和根目录 shell 脚本的 Docker 和辅助脚本。

权威文档（优先使用这些而不是 `readme.md` 中提到的较旧路径）：

- 根目录概览和功能文档：`readme.md`。
- 后端专用使用说明：`backend/README.md`。
- 前端专用使用说明：`frontend/README.md`。
- 单体仓库布局和预期结构：`docs/PROJECT_STRUCTURE.md`。
- 部署工作流：`DEPLOYMENT.md` 和 `deploy.sh`。
- iFlow / 更高级别产品和运维视图：`IFLOW.md`。

> 注意：`readme.md` 中的一些旧文档仍然引用 `app/` 目录（例如 `app/main.py`）。此仓库中的实际后端代码位于 `backend/src/gap`。如有疑问，请遵循 `backend/README.md` 和 `docs/PROJECT_STRUCTURE.md`。

## 常用命令和工作流

### 根级工作流

环境和编排：

```bash
# 从仓库根目录

# 1) 初始化环境变量
cp .env.example .env
# 编辑 .env 文件，设置 DATABASE_URL, REDIS_URL, SECRET_KEY, GEMINI_API_KEYS 等

# 2) 基于 Docker 的部署（后端 + 前端在单个端口后，推荐用于生产环境运行）
./deploy.sh docker      # 或：./deploy.sh

# 3) 本地基于 uv 的部署（后端 + 前端作为本地进程）
./deploy.sh local

# 4) 停止由 deploy.sh 启动的服务
./deploy.sh stop
```

健康检查和日志（路径来自 `DEPLOYMENT.md` 和 `docs/PROJECT_STRUCTURE.md`）：

```bash
# 健康检查（如果更改了配置，端口可能有所不同）
curl http://localhost:7860/healthz    # 组合堆栈
curl http://localhost:8000/healthz    # 仅后端，本地开发模式（如果暴露）

# 调试时跟踪核心日志
ls logs/
# 典型文件：app.log, error.log, access.log, backend.log, frontend.log
```

### 后端（位于 `backend/` 的 FastAPI 服务）

#### 环境设置

首选（基于 uv 的）工作流（来自 `IFLOW.md`）：

```bash
cd backend

# 创建并激活虚拟环境
uv venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 安装运行时和开发依赖
uv pip install -r requirements.txt
# （可选的开发依赖，如果在你的需求/约束中启用）
# uv pip install -r requirements.txt --extra dev
```

替代方案（纯 pip，来自 `backend/README.md`）：

```bash
cd backend
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

#### 运行后端

FastAPI 入口点是 `backend/src/gap/main.py`：

```bash
cd backend
source .venv/bin/activate           # 或者 venv/bin/activate

# 开发模式（自动重载）
uvicorn src.gap.main:app --reload --host 0.0.0.0 --port 8000

# 生产风格的单进程运行
uvicorn src.gap.main:app --host 0.0.0.0 --port 8000 --workers 4
```

后端的 OpenAPI UI 可在以下位置访问：

- Swagger UI 用户界面: `http://localhost:8000/docs`
- ReDoc 文档界面: `http://localhost:8000/redoc`

#### 后端测试

Pytest 是规范的测试运行器（参见 `backend/README.md` 和 `IFLOW.md`）：

```bash
cd backend
source .venv/bin/activate

# 运行所有测试
pytest

# 仅运行单元测试
pytest tests/unit/

# 仅运行集成测试
pytest tests/integration/

# 运行测试并生成覆盖率和 HTML 报告
pytest --cov=src --cov-report=html
```

针对更小范围的测试（标准 pytest 用法，在迭代错误修复时很有用）：

```bash
# 单个文件
pytest tests/unit/test_keys_manager.py

# 文件中的单个测试
pytest tests/unit/test_keys_manager.py::test_select_best_key

# 按测试名称模式过滤
pytest tests/unit/ -k "select_best_key"
```

#### 后端代码质量工具

来自 `backend/README.md` 和 `IFLOW.md` 的命令：

```bash
cd backend
source .venv/bin/activate

# 格式化
black src/
isort src/

# 类型检查
mypy src/

# 代码检查（如果在此仓库中配置）
flake8 src/
```

### 前端 Frontend (Vue 3 + TypeScript 单页应用，位于 `frontend/`)

#### 环境设置 Environment setup

```bash
cd frontend

# 安装依赖 (需要 Node 18+)
npm install
# 或者
yarn install
```

#### 运行前端 Running the frontend

来自 `frontend/README.md` 和 `frontend/package.json` 的脚本：

```bash
cd frontend

# 开发服务器 (Vite 默认端口，通常是 5173)
npm run dev

# 在自定义端口上运行开发服务器
npm run dev -- --port 3000

# 监听所有接口 (在容器/VPN 内很有用)
npm run dev-host
```

#### 前端构建和预览 Frontend build and preview

```bash
cd frontend

# 生产环境构建
npm run build

# 本地预览构建的资产
npm run preview

# 构建并分析包 (使用 Vite "analyze" 模式)
npm run analyze
```

#### 前端测试 Frontend tests

使用 Vitest 和 Playwright (参见 `frontend/README.md` 和 `package.json`):

```bash
cd frontend

# 运行单元测试和端到端测试
npm run test          # test:unit && test:e2e 的简写

# 仅运行单元测试
npm run test:unit

# 端到端测试
npm run test:e2e

# 带覆盖率的单元测试
npm run test:coverage
```

要专注于单个规范或交互式调试：

```bash
# 运行特定的单元测试文件
npm run test:unit Button.spec.ts

# 运行 Vitest UI
npm run test:unit -- --ui

# 在调试模式下运行单元测试
npm run test:unit -- --debug
```

#### 前端代码检查、格式化和类型检查 Frontend linting, formatting, and type checking

```bash
cd frontend

# 代码检查 (ESLint)
npm run lint

# 代码检查并自动修复
npm run lint -- --fix

# 格式化 (Prettier)
npm run format

# 类型检查 (vue-tsc + TypeScript)
npm run type-check
```

单页应用 SPA 的环境变量通过 Vite 定义 (参见 `frontend/README.md`):

```bash
# frontend/ 目录中的 .env 示例
VITE_API_BASE_URL=http://localhost:8000
VITE_DEV_MODE=true
VITE_ENABLE_ANALYTICS=false
```

## 高级架构

### 单体仓库布局

高级别视图（参见 `docs/PROJECT_STRUCTURE.md`, `IFLOW.md`）：

- `backend/`: 实现兼容 OpenAI 的 `/v1` API 和 Gemini 原生 `/v2` API 的 FastAPI 服务，以及缓存/上下文/管理端点。
- `frontend/`: 用于 Web UI 的 Vue 3 SPA（密钥管理、缓存/上下文管理、分析、配置）。
- `deployment/`: 用于运行组合堆栈的 Dockerfiles、`docker-compose.yml` 和 K8s 清单文件。
- `docs/`: 附加文档（API 模式、部署说明、开发指南、项目结构）。
- `logs/`: 运行时日志（应用程序、错误、访问和部署相关日志）。
- `tools/`: 辅助脚本（例如，数据库迁移助手、日志分析器、性能测试）。

### 后端服务架构 Backend service architecture (`backend/src/gap`)

后端围绕 **API 表面层**、**核心领域逻辑** 和 **基础设施** 之间的清晰分离进行组织：

- **入口和配置 Entry and configuration**

  - `main.py` 构建 FastAPI 应用，连接路由器，配置日志记录，并注册启动/关闭钩子（例如，后台调度器、健康检查）。
  - `config.py` 集中管理配置，主要读取 `.env` 中定义的环境变量（例如数据库 URL、Redis URL、JWT/SECRET_KEY、速率限制、存储模式、像 `ENABLE_NATIVE_CACHING` 这样的功能标志）。

- **API 层 (`api/`)**

  - 实现服务的 HTTP 契约：
    - **兼容 OpenAI 的 API**: `/v1` 下的端点（例如 `endpoints.py`）接受 OpenAI Chat Completions 风格的载荷并将其转换为内部请求对象。
    - **Gemini 原生 API**: `/v2` 下的端点（例如 `v2_endpoints.py`）以最小转换代理到 Gemini `generateContent`。
    - **缓存和管理端点**: `cache_endpoints.py` 和管理相关路由暴露像 `/api/v1/caches` 这样的 API 和内部仪表板。
  - API 函数故意设计得很薄：它们验证/认证输入，然后委托给 `core/` 模块。

- **核心领域逻辑 (`core/`)**
  - **`database/`**
    - 包含 SQLAlchemy 模型和数据库工具，包括对话上下文、缓存、API 密钥和任何额外持久化配置的实体。
    - 提供异步会话管理和常见查询的辅助工具（例如，查找与缓存条目关联的密钥），在整个 `core/` 中重用。
  - **`keys/`**
    - 封装 **API 密钥池管理**：加载密钥、针对 Gemini 验证密钥、跟踪每个密钥的配额（RPD/RPM/TPD/TPM），并为给定请求选择"最佳"密钥。
    - 处理自动密钥轮换和故障转移，当密钥耗尽或返回错误时；与使用跟踪和报告集成。
  - **`context/`**
    - 管理以 `Authorization: Bearer <credential>` 令牌为键的 **对话状态**。
    - 支持传统服务器端对话历史和（启用时）与 Gemini 原生缓存的协调。
    - 基于模型限制和可配置的安全边距应用基于令牌的截断，以避免超出模型上下文窗口。
  - **`cache/`**
    - 实现 **Gemini 原生缓存**支持和任何额外缓存（例如请求/响应缓存），包括后台清理作业。
    - 协调缓存条目与用户和特定 API 密钥，以便可以安全地重用缓存内容。
  - **`processing/`**
    - 编排 **请求管道**：
      - 将 OpenAI 风格的 `/v1` 载荷转换为 Gemini `generateContent` 请求。
      - 集成密钥选择、上下文扩展/截断、安全过滤选项以及流式与非流式响应。
      - 将响应包装并标准化回 `/v1` 风格或 `/v2` 风格的输出。
    - 在更改提示、上下文或模型参数的转换方式时的核心查找位置。
  - **`reporting/`** 和 **`tracking.py`**
    - 跟踪每个密钥和每个模型的实时使用情况（令牌和请求，每分钟/每天）。
    - 计算密钥管理器使用的健康分数，并定期记录报告总结使用情况、剩余配额和密钥池大小建议。
    - 通过后台任务安排定期作业（例如计数器的每日重置）。
  - **`security/`**
    - 实现 JWT 处理、认证助手和 IP/密钥级速率限制。
    - 提供 FastAPI 依赖项以在端点间一致地强制执行认证和授权。
  - **`services/`**
    - 与外部系统接口，特别是 Gemini/Google API（HTTP 客户端、重试、低级传输）。
  - **`utils/`**
    - 用于请求/响应操作、错误规范化和 `processing/`、`api/` 和管理视图使用的其他横切关注点的共享工具。

从 **请求生命周期** 的角度看：

1. HTTP 调用通过 `/v1` 或 `/v2` 进入（API 层）。
2. 执行认证和速率限制（`security/`）。
3. 密钥管理器选择合适的 API 密钥（`keys/`），考虑跟踪的使用情况和配额（`reporting/`, `tracking`）。
4. 解析上下文/历史和缓存参与（`context/`, `cache/`）。
5. 请求被转换并发送到 Gemini（`processing/`, `services/`）。
6. 响应被记录，使用情况和缓存指标被更新，客户端收到兼容 OpenAI 或 Gemini 原生的载荷。

### 前端应用架构 Frontend application architecture (`frontend/src`)

前端是一个展现 GAP 的运营和管理功能的 Vue 3 单页应用：

- **入口和布局 Entry and layout**

  - `main.js` 启动 Vue 应用，安装路由器和 Pinia，注册全局组件，并挂载 `App.vue`。
  - `layouts/` 包含在多个视图中使用的 shell 组件（导航、侧边栏、布局容器），通常包装 `router-view`。

- **核心功能区域 Core feature areas**

  - `views/`: 关键操作流程的页面级组件（例如，密钥管理、使用情况仪表板、缓存/上下文管理、配置、状态页面）。
  - `components/common/`: 在视图间共享的可重用 UI 原语（表单、表格、对话框、过滤器）。
  - `components/specific/`: 特定功能的构建块（例如，密钥详细信息面板、使用图表、缓存检查器）。
  - `stores/`: 封装认证、密钥、缓存、上下文和设置的客户端状态的 Pinia 模块，通常镜像后端域。
  - `services/`: 集中化对后端调用的 API 客户端层（Axios 实例），使用 `VITE_API_BASE_URL`。添加/更改后端端点时，首先要更新这一层。
  - `types/`: 用于 API 载荷和域模型的共享 TypeScript 接口和类型，在存储、服务和组件间使用。
  - `composables/`: 封装可重用逻辑的 Vue Composition API 工具（例如，加载状态、轮询、选择和过滤逻辑、表单提交流程）。
  - `constants/`: 应用中使用的路由名称、API 路径、配置键和功能标志的中心定义。

- **横切关注点 Cross-cutting concerns**
  - **样式和设计 Styling and design**: Tailwind CSS 和 Element Plus 提供设计系统；Tailwind 工具和组件主题全局配置。
  - **可视化 Visualization**: ECharts 和 Chart.js 为分析仪表板提供动力；专用组件包装图表以保持视图声明性。
  - **国际化、通知和用户体验 I18n, notifications, and UX**: Vue I18n、toast/通知工具和虚拟滚动库支持大型表格和仪表板的响应式实时用户体验。

### 部署和运行时拓扑 Deployment and runtime topology

- `deployment/` 中的 Docker 和 K8s 清单文件的构造方式为：
  - 后端 FastAPI 应用和前端构建产物组合成单个可部署服务（默认暴露在像 `7860` 的端口上）。
  - `deployment/docker/Dockerfile` 和 `docker-compose.yml` 协调构建后端（Python/uvicorn）和服务前端（Vite 构建输出）。
- `deploy.sh` 包装这些清单，处理环境检查、镜像构建、容器启动、健康检查和停止/清理流程。
- 对于本地开发，通常是：
  - 通过 `uvicorn src.gap.main:app --reload` 在端口 `8000` 上直接运行后端。
  - 通过 `npm run dev` 在单独端口（例如 `5173`）上运行前端，配置为与 `VITE_API_BASE_URL=http://localhost:8000` 通信。

### 配置和环境 Configuration and environment

配置主要通过环境变量驱动（参见 `.env.example`、`DEPLOYMENT.md`、`IFLOW.md`、`backend/README.md` 和 `readme.md`）。修改行为时需要注意的关键类别：

- **后端基础设施 Backend infrastructure**: `DATABASE_URL`、`REDIS_URL`、日志级别和日志路径。
- **认证和安全 Authentication and security**: `SECRET_KEY`、`JWT_SECRET_KEY`、`USERS_API_KEY`（平台用户登录密钥，用于 Web UI 登录）和 API 密钥相关设置。
- **Gemini 访问和使用控制 Gemini access and usage control**: `GEMINI_API_KEYS`（或数据库存储的密钥）、上下文和缓存存储模式、原生缓存启用和速率限制控制旋钮（`MAX_REQUESTS_PER_MINUTE`、`MAX_REQUESTS_PER_DAY_PER_IP`）。
- **前端集成 Frontend integration**: `VITE_API_BASE_URL` 和相关的控制分析和开发行为的 Vite `VITE_*` 标志。

在对认证、速率限制或密钥/缓存行为进行重大更改时，协调以下方面的更新：

- 后端配置和 `core/` 模块。
- 前端 `services/`、`stores/` 和 `types/`。
- 部署清单（`deployment/docker/*`、`.env.example`），以便为所有环境引入新设置。
