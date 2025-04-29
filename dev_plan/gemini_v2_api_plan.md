# Gemini 原生 API (v2) 及上下文管理增强计划

## 1. 目标

在现有 OpenAI 兼容 API (`/v1`) 的基础上，增加一套符合 Gemini 原生 API 规范的新接口 (`/v2`)，目标是高保真地代理 Gemini 功能。同时，将现有的按 Key 自动补全上下文功能适配到 `/v2` 接口，并增加按 Key 单独配置是否启用该功能的选项。

## 2. API 路径结构

* **OpenAI 兼容接口 (现有):** 使用 `/v1` 前缀。
  * 例如: `/v1/chat/completions`, `/v1/models`
* **Gemini 原生接口 (新增):** 使用 `/v2` 前缀。
  * 目标端点: `/v2/models/{model}:generateContent`
  * 未来可扩展其他 `/v2` 端点。

## 3. 核心功能扩展 - 上下文管理与配置

### 3.1. Key 配置增强

* **修改密钥存储:** 为每个 API Key 增加一个布尔型配置项 `enable_context_completion` (默认值待定，建议 `True`)。
* **更新 Web UI (`app/web/templates/manage_keys.html` & `app/web/routes.py`):**
  * 在密钥管理页面显示每个 Key 的上下文补全启用状态。
  * 添加控件（如复选框）允许管理员修改此状态。
  * 实现后端逻辑以保存更改。

### 3.2. 认证/依赖注入增强

* 修改或创建新的依赖项函数 (例如 `verify_proxy_key_with_config`)，用于：
  * 验证 API Key 的有效性。
  * 查询并返回该 Key 的 `enable_context_completion` 配置状态。

### 3.3. 上下文存储适配 (`app/core/context_store.py`)

* **格式转换:**
  * 实现 `convert_openai_to_gemini_contents(history: List[Dict]) -> List[Dict]` 函数，用于将存储的 OpenAI 格式历史记录转换为 Gemini `contents` 格式。
  * 实现 `convert_gemini_to_storage_format(request_content: Dict, response_content: Dict) -> List[Dict]` 函数，用于将 Gemini 的请求/响应部分转换为内部存储格式（可能是 OpenAI 格式）。
* **逻辑调整:** 确保上下文存储和检索能处理可能存在的格式差异。

### 3.4. 请求处理逻辑适配

* **`/v1` 接口 (`app/api/request_processor.py`):**
  * 使用增强的依赖项获取 Key 配置。
  * 仅在 `enable_context_completion` 为 `True` 时执行上下文获取和注入。
* **`/v2` 接口 (`app/api/v2_endpoints.py`):**
  * 在 `generateContent` 端点函数中，使用增强的依赖项获取 Key 配置。
  * **上下文注入 (如果启用):**
    1. 获取存储的上下文历史。
    2. 调用 `convert_openai_to_gemini_contents` 进行格式转换。
    3. 将转换后的 `contents` 注入到当前请求的 `contents` 字段开头。
  * 调用 `GeminiClient`。
  * **上下文存储 (如果启用):**
    1. 提取当前请求的用户部分和模型响应部分。
    2. 调用 `convert_gemini_to_storage_format` 进行格式转换。
    3. 将转换后的对话回合添加到 `context_store`。

## 4. `/v2` 接口实现步骤

1. **创建 Pydantic 模型:** 在 `app/api/` 下创建 `v2_models.py` (或添加到 `models.py`)，定义 `GeminiGenerateContentRequestV2` 和 `GeminiGenerateContentResponseV2`，精确匹配 Gemini `generateContent` API 规范。
2. **创建 API 路由文件:** 创建 `app/api/v2_endpoints.py`。
3. **定义新 Router:** 在 `v2_endpoints.py` 中创建 `v2_router = APIRouter()`。
4. **定义端点:** 实现 `@v2_router.post("/models/{model}:generateContent")` 端点，集成第 3.4 节中的上下文处理逻辑和配置检查。
5. **注册路由:** 在 `app/main.py` 中，使用 `app.include_router(v2_router, prefix="/v2", tags=["Gemini Native API v2"])` 注册新路由。确保 `/v1` 路由也明确使用了前缀。

## 5. 文档更新 (`readme.md`)

* 清晰说明 `/v1` (OpenAI 兼容) 和 `/v2` (Gemini 原生) 的区别和用途。
* 解释上下文自动补全功能及其适用范围 (`/v1` 和 `/v2`)。
* 添加关于如何在管理界面配置 Key 的上下文补全功能的说明。
* 提供 `/v2/models/{model}:generateContent` 的使用示例和参数说明。

## 6. 可视化方案 (Mermaid Diagram)

```mermaid
graph TD
    subgraph FastAPI App (main.py)
        direction LR
        A1(API v1 Router<br>/v1)
        A2(API v2 Router<br>/v2)
    end

    subgraph API Endpoints
        direction TB
        B1(/v1/chat/completions)
        B2(/v1/models)
        C1(/v2/models/{model}:generateContent)
    end

    subgraph Core Logic
        direction TB
        D{Request Processor<br>(OpenAI Format)}
        E{Gemini v2 Request Handler}
        F[Gemini Client<br>(core/gemini.py)]
        G[Context Store<br>(core/context_store.py)<br>- Get/Add Context<br>- Format Conversion]
        H[Key Management<br>(core/key_management.py)<br>- Store Key Config<br>(enable_context_completion)]
        I[Auth Middleware<br>(middleware.py)<br>- Verify Key<br>- Return Key Config]
    end

    subgraph Web UI
        direction TB
        J[Manage Keys Page<br>(web/templates/manage_keys.html)<br>- Display/Edit Context Config]
        K[Web Routes<br>(web/routes.py)<br>- Handle Key Config Update]
    end

    L[readme.md]

    A1 --> B1; A1 --> B2; A2 --> C1;
    B1 --> D; B2 --> D; C1 --> E;
    I --> D; I --> E;
    D -- Check Config --> G; E -- Check Config --> G;
    G -- Inject/Store --> D; G -- Inject/Store --> E;
    D --> F; E --> F;
    H --> I; K --> H; J --> K;
    A1 & A2 & G & H & J --> L{Update Documentation};
```

## 7. 下一步

切换到 "Code" 模式，按照此计划逐步实施代码更改和文档更新。

## 8. 配置

* **环境变量 (必需):**
  * `GEMINI_API_KEYS`: Google Gemini API Key 列表。
  * `PASSWORD`: 用于 Web UI 登录 **和** 内存模式下的 API 认证。
  * `SECRET_KEY`: 用于 JWT 签名的强随机密钥。
* **环境变量 (可选):**
  * `CONTEXT_DB_PATH`: SQLite 数据库文件路径 (不设置则使用内存数据库)。
  * `DEFAULT_MAX_CONTEXT_TOKENS`: 回退 Token 限制 (默认: `30000`)。
  * `CONTEXT_TOKEN_SAFETY_MARGIN`: Token 安全边际 (默认: `200`)。
  * `MAX_REQUESTS_PER_MINUTE`: 本地 RPM 限制 (默认 30)。
  * `MAX_REQUESTS_PER_DAY_PER_IP`: 本地每日 IP 请求限制 (默认 600)。
  * `DISABLE_SAFETY_FILTERING`: 是否全局禁用安全过滤 (默认 false)。
  * `JWT_ALGORITHM`: JWT 算法 (默认 HS256)。
  * `ACCESS_TOKEN_EXPIRE_MINUTES`: JWT 有效期 (分钟, 默认 30)。
  * `USAGE_REPORT_INTERVAL_MINUTES`: 使用报告间隔 (分钟, 默认 30)。
  * `REPORT_LOG_LEVEL`: 使用报告日志级别 (默认 INFO)。
  * `CACHE_REFRESH_INTERVAL_SECONDS`: Key 分数缓存刷新间隔 (秒, 默认 10)。
  * `MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS`: 内存上下文清理间隔 (秒, 默认 3600)。
  * `MAX_CONTEXT_RECORDS_MEMORY`: 内存上下文最大记录数 (默认 5000)。
  * `STREAM_SAVE_REPLY`: (可选) 是否在流式响应后保存模型回复 (默认 false)。
* **文件配置:**
  * `app/data/model_limits.json`: **需要扩展**，为相关模型添加 `input_token_limit` 字段。
* **数据库配置:**
  * 上下文 TTL 默认值在代码中设置 (7 天)，实际值存储在 SQLite `settings` 表中，可通过 Web UI 修改。

## 9. 部署

* **依赖 (`requirements.txt`):** 需要添加/确认 `fastapi`, `uvicorn[standard]`, `python-dotenv`, `httpx`, `starlette`, `jinja2`, `python-multipart`, **`python-jose[cryptography]`**。
* **Docker:** 确保应用有权限写入数据库文件所在的目录 (如果使用文件模式)。
* **Hugging Face Space:** 配置所需的环境变量 (Secrets)。**注意内存模式的非持久性**。**建议配置 `--workers 1` 以确保内存数据库一致性**。
* **单 Worker 建议:** 在使用内存数据库时，强烈建议配置 Uvicorn 或 Gunicorn 只使用单个工作进程 (`--workers 1`)，以避免多进程访问共享内存数据库可能导致的状态不一致问题。

## 10. 用户责任

用户负责保护好 `PASSWORD` 和 `SECRET_KEY` 环境变量，避免泄露。

## 11. 兼容性说明

本次改造主要集中在认证、上下文管理和 Web UI，对核心的 API 代理逻辑影响较小。API 请求体和响应体格式保持与 OpenAI 规范兼容。

## 12. 测试计划

* **单元测试:** 针对新的 JWT 认证函数、数据库操作函数、上下文管理逻辑编写单元测试。
* **集成测试:** 测试 Web UI 登录、Key 管理、上下文管理等功能的端到端流程。
* **性能测试:** 评估 SQLite 持久化对性能的影响。
* **安全测试:** 验证 JWT 认证的安全性，确保只有授权用户能访问管理功能。

## 13. 计划实施步骤 (高层)

1. **环境准备:** 确保安装 `aiosqlite` 和 `python-jose[cryptography]`。
2. **数据库改造:** 修改 `db_utils.py`，实现异步数据库连接和操作。
3. **上下文存储改造:** 修改 `context_store.py`，使用异步数据库操作。
4. **密钥管理改造:** 修改 `key_management.py` 和 `utils.py`，统一密钥加载和管理器初始化。
5. **JWT 认证实现:** 修改 `auth.py` 和 `routes.py`，实现 JWT 登录和验证。
6. **Web UI 改造:** 修改 `routes.py` 和模板文件，实现基于 JWT 的管理界面。
7. **代理 Key 管理实现:** 在文件模式下实现 Key 的增删改查功能。
8. **上下文管理实现:** 实现上下文的查看和删除功能。
9. **配置更新:** 更新 `.env` 和 `config.py`。
10. **测试:** 进行全面的单元测试、集成测试和性能测试。
11. **文档更新:** 更新 `readme.md` 和 `changelog.md`。
12. **部署验证:** 在不同环境下验证部署和功能。
