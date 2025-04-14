# Gemini API 代理持久化上下文管理方案

## 1. 目标

解决当前 Gemini API 代理在多 Key 轮询模式下无法保持对话上下文的问题。实现一个持久化的、支持多租户（基于代理 Key）的上下文管理机制，同时严格保持对 OpenAI Chat Completions API 规范的兼容性，并兼容 Docker 及 Hugging Face Space 部署环境。

## 2. 核心方案：基于代理 Key 的多租户上下文管理

采用中转服务自身发放和管理的 **代理 Key** 作为区分不同对话上下文的标识符。

*   **API 认证:** 客户端调用 API 时，在 HTTP Header 中提供 `Authorization: Bearer <proxy_api_key>` 进行认证。
*   **上下文标识:** 使用验证通过的 `<proxy_api_key>` 作为该次请求关联的上下文 ID。
*   **上下文隔离:** 每个有效的代理 Key 对应一套独立的对话历史上下文，存储在持久化介质中。
*   **兼容性:** API 的请求体和响应体格式严格遵守 OpenAI 规范。

## 3. 持久化存储

*   **技术选型:** SQLite 数据库。
*   **数据库文件:** 默认存储在 `app/data/context_store.db` (路径可通过 `CONTEXT_DB_PATH` 环境变量覆盖)。
*   **存储持久性说明:**
    *   **本地部署/持久环境:** 将 `CONTEXT_DB_PATH` 指向持久化存储位置时，上下文将持久保存。
    *   **Hugging Face Spaces (免费层):** 由于免费层文件系统限制，SQLite 文件在此环境下**不是持久的**。Space 重启（如更新、不活动、资源调整）将导致数据库文件丢失，上下文历史将清空。此模式下提供的是**临时的、会话级别的上下文保持**。
*   **数据库表结构:**
    *   `proxy_keys`: 存储代理 Key 信息。
        *   `key TEXT PRIMARY KEY`: 代理 Key 字符串。
        *   `description TEXT`: Key 的描述信息（可选）。
        *   `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`: 创建时间。
        *   `is_active BOOLEAN DEFAULT TRUE`: Key 是否启用。
    *   `contexts`: 存储对话上下文历史。
        *   `proxy_key TEXT PRIMARY KEY`: 关联的代理 Key。
        *   `contents TEXT NOT NULL`: 对话历史（Gemini `contents` 格式）的 JSON 序列化字符串。
        *   `last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP`: 上下文最后使用时间。
        *   *外键约束:* `FOREIGN KEY(proxy_key) REFERENCES proxy_keys(key) ON DELETE CASCADE` (删除代理 Key 时自动删除其关联的上下文)。
    *   `settings`: 存储全局配置项。
        *   `key TEXT PRIMARY KEY`: 配置项名称 (例如: `"context_ttl_days"`)。
        *   `value TEXT NOT NULL`: 配置项的值。

## 4. 代理 Key 管理

*   **存储:** 代理 Key 及其元数据存储在 SQLite 的 `proxy_keys` 表中。
*   **管理:** 通过 Web 管理界面 (`/manage/keys`) 进行增、删、改（描述、状态）、查操作。需要管理员密码登录。提供“生成新 Key”的功能。

## 5. 上下文管理逻辑

*   **存储:** 对话历史存储在 SQLite 的 `contexts` 表中，与代理 Key 关联。
*   **加载/保存:**
    *   在 API 请求处理函数 (`process_request`) 中，根据验证通过的 `proxy_key` 从 `contexts` 表加载历史。
    *   在 Gemini API 调用成功后，将模型回复追加到上下文中，并将更新后的上下文写回 `contexts` 表，同时更新 `last_used` 时间戳。
*   **Token 估算:** 使用 `len(json.dumps(contents)) / 4` 作为 Token 数量的粗略估计。在代码注释和文档中说明其局限性。
*   **截断逻辑 (模型感知):**
    *   在发送给 Gemini API 前和保存回数据库前进行检查。
    *   获取当前请求使用的模型名称 (`chat_request.model`)。
    *   从 `app/data/model_limits.json` 中查找该模型的 `input_token_limit` 值。
        *   **需要扩展 `model_limits.json` 文件，为每个模型添加 `input_token_limit` 字段，其值来源于 Google 官方文档。**
        *   如果模型或 `input_token_limit` 未在 JSON 文件中定义，则使用一个**全局默认的回退 Token 限制**（例如，通过环境变量 `DEFAULT_MAX_CONTEXT_TOKENS` 设置，默认值为 8192）。
    *   确定**截断阈值**: 使用查找到的 `input_token_limit` 或回退限制，并减去一个小的**安全边际**（例如 100-200 Tokens，可通过环境变量 `CONTEXT_TOKEN_SAFETY_MARGIN` 配置）以防止估算误差。
    *   如果估算 Token 超过此**截断阈值**，则从 `contents` 列表的**开头**开始，**成对移除**用户和模型的消息，直到满足限制。
    *   如果移除到最后只剩一个最新的消息对，而这个消息对本身就超过了**截断阈值**，则记录错误，本次交互**不更新**存储的上下文。
*   **TTL 自动清理:**
    *   基于 `contexts.last_used` 时间戳和存储在 `settings` 表中的 `context_ttl_days` 配置值。
    *   默认 TTL 为 7 天（在应用启动时写入 `settings` 表，如果不存在）。
    *   在 `load_context(proxy_key)` 函数中检查 `last_used` 时间戳，如果 `CURRENT_TIMESTAMP - last_used > TTL`，则自动删除该条上下文记录。

## 6. Web 管理界面

*   **访问路径:** `/manage` (需要先通过 `/` 路径使用 `PASSWORD` 环境变量进行密码登录)。
*   **认证:** 复用现有密码登录逻辑，并引入 Session 中间件 (`starlette.middleware.sessions.SessionMiddleware`) 保持登录状态（需要 `SECRET_KEY` 环境变量）。
*   **功能:**
    *   **代理 Key 管理 (`/manage/keys`):** 查看列表、添加新 Key（可自动生成）、编辑描述、启用/禁用 Key、删除 Key。
    *   **上下文管理 (`/manage/context`):**
        *   查看当前 TTL 设置并修改。
        *   按代理 Key 查看上下文记录（显示 Key、大致内容长度、最后使用时间）。
        *   按代理 Key 删除指定的上下文记录。
*   **技术栈:** FastAPI, Jinja2 模板引擎。
*   **安全:**
    *   服务端对所有表单输入进行验证。
    *   **注意:** 当前计划**暂不包含 CSRF 防护**，存在安全风险。建议在后续版本中添加。

## 7. 配置

*   **环境变量 (必需):**
    *   `GEMINI_API_KEYS`: 逗号分隔的 Google Gemini API Key 列表。
    *   `PASSWORD`: 用于登录 Web 管理界面的密码。
    *   `SECRET_KEY`: 用于 Session 中间件加密的强随机密钥。
*   **环境变量 (可选):**
    *   `CONTEXT_DB_PATH`: SQLite 数据库文件的路径 (默认: `app/data/context_store.db`)。
    *   `DEFAULT_MAX_CONTEXT_TOKENS`: 当模型未在 `model_limits.json` 中定义时的回退 Token 限制 (默认: `30000`)。
    *   `CONTEXT_TOKEN_SAFETY_MARGIN`: 从模型 `input_token_limit` 减去的安全边际 (默认: `200`)。
*   **文件配置:**
    *   `app/data/model_limits.json`: **需要扩展**，为每个模型添加 `input_token_limit` 字段。
*   **数据库配置:**
    *   上下文 TTL 默认值在代码中设置 (7 天)，实际值存储在 SQLite `settings` 表中，可通过 Web UI 修改。

## 8. 部署

*   **依赖 (`requirements.txt`):** 需要添加/确认 `fastapi`, `uvicorn[standard]`, `python-dotenv`, `pytz`, `httpx`, `starlette`, `jinja2`, `python-multipart`。
*   **Docker:** 确保应用有权限写入数据库文件所在的目录 (例如 `app/data/`)。
*   **Hugging Face Space:** 配置所需的环境变量 (Secrets)。**注意：** 免费层的文件系统通常不是持久的，会导致 SQLite 数据在重启时丢失（见第 3 节说明）。付费层或特定配置可能提供持久存储选项。

## 9. 用户责任

*   文档需明确强调：用户必须为每个独立的对话/任务使用**不同**的代理 Key，以保证上下文隔离。错误地复用同一个代理 Key 会导致对话历史混淆。

## 10. 文档 (`readme.md`)

*   需要大幅更新，详细说明新的代理 Key 认证方式、上下文管理机制（包括模型感知截断）、Web UI 功能、用户责任以及所有相关的配置选项和 `model_limits.json` 的扩展。