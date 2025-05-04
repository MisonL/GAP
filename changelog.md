# 更新日志

## v1.7.2

- 核心架构重构，提升性能和并发处理能力。
- 智能 API Key 管理，优化 Key 的使用效率和稳定性。
- 持久化对话上下文存储。
- 新增 Gemini 原生 API (/v2) 支持。
- 引入详细使用情况报告（含 Web UI 页面）。
- 增强流式响应处理和错误处理。
- 代码模块化和解耦改进。
- 增加配置灵活性。
- 优化 OpenAI 兼容性。

## v1.7.1

- **增强与改进**:
  - **使用情况报告 (`app/core/usage_reporter.py`)**:
    - 为控制台报告添加 ANSI 颜色代码，提高可读性。
    - 扩展 RPD 和 TPD 输入容量估算，针对三个主要模型进行报告。
    - 调整每日预估 TPD 输入量的报告逻辑（仅在一天过去 >10% 后显示）。
    - 同步更新结构化报告数据函数。
  - **Web UI 支持 (`app/main.py`)**:
    - 添加对 `/assets` 目录的静态文件服务。
- **文档与开发计划更新**:
  - **开发计划 (`dev_plan/`)**:
    - 细化缓存优化计划 (`caching_optimization_plan.md`)，补充错误处理、并发、失效更新等细节。
    - 更新并细化 Key 选择优化计划 (`key_selection_optimization_plan.md`)，反映当前状态并新增 Key 轮换机制等。
  - **项目说明 (`readme.md`)**:
    - 提高对现有功能（Key 选择、健康评分、预检查、认证模式）的描述清晰度。
    - 新增 Web UI 各页面功能的详细说明。
    - 澄清上下文数据库路径和支持的图片类型。
    - 进行格式清理。

## v1.7.0

- **代码优化与重构**:
  - **异步数据库迁移**: 将同步的 `sqlite3` 迁移到异步的 `aiosqlite`，提升异步处理能力。
  - **代码结构优化**: 拆分大型文件（如 `app/core/utils.py` 和 `app/api/request_processor.py`），按功能模块组织代码，统一使用绝对导入，提高可读性和可维护性。
  - **依赖注入优化**: 利用 FastAPI 依赖注入更好地管理和共享 `APIKeyManager` 和 `httpx.AsyncClient` 实例。
  - **错误处理改进**: 统一异常处理和日志记录，引入结构化日志。
  - **上下文管理优化**: 统一 v1 和 v2 的上下文处理逻辑。
  - **apscheduler 审查**: 确保后台任务调度可靠。
  - **Jinja2 和 python-jose 审查**: 确保 Web UI 模板和 JWT 认证的安全性。
  - **清理冗余注释**: 移除英文注释和不再相关的注释。

## v1.6.1

- **Web UI 改进**:
  - 优化报告页面布局和样式，提升美观度和响应式体验。
  - 在页面底部添加版权信息和项目 GitHub 仓库链接。
  - 将 API 文档链接从登录页移至管理页面底部。

- **修复**:
  - 修复代理 Key 管理页面（`/manage/keys`）中 JavaScript 错误导致的功能异常。

- **其他**:
  - 添加 `/debug/config` 调试接口。

## v1.6.0

- **新增 Gemini 原生 API (v2) 支持**: 引入 `/v2` 前缀的新接口，高保真代理 Gemini 原生功能，目前已实现 `/v2/models/{model}:generateContent` 端点。

- **增强上下文管理**:
  - 支持为每个代理 Key 单独配置是否启用上下文自动补全功能（默认启用）。
  - 更新 Web UI (`/manage/keys`)，允许管理员在文件存储模式下管理 Key 的上下文补全状态。
  - 适配上下文存储 (`app/core/context_store.py`) 和请求处理逻辑 (`app/api/v2_endpoints.py`)，以支持 `/v2` 接口和按 Key 配置的上下文管理。

- **文档更新**: 更新 `readme.md`，详细说明 `/v1` 和 `/v2` 接口的区别、用途，以及增强的上下文管理功能和 Key 配置方法。

## v1.5.0

- **新增 Web 报告页面**: 引入了一个全新的 Web 界面 (`/report`)，用于美观地展示 API 使用情况报告。

- **结构化报告数据 API**: 添加了后端 API 路由 (`/api/report/data`)，提供结构化 JSON 格式的报告数据，支持前端页面动态加载和展示。

- **报告数据逻辑重构**: 在 `app/core/usage_reporter.py` 中实现了 `get_structured_report_data` 函数，优化了报告数据的获取和处理逻辑。

- **前端报告展示**: 在 `report.html` 页面中实现了前端 JavaScript 逻辑，利用 Chart.js 库绘制图表，并填充 Key 使用概览、容量与使用、Key 数量建议和 Top IP 统计等数据。

- **修复时区导入问题**: 解决了报告数据获取逻辑中 `timezone` 导入相关的错误，确保报告功能正常运行。

## v1.4.2

- **本地化**: 为项目中的主要代码文件补全了中文注释。

- **配置与提示**:
  - 将 `ADMIN_API_KEY` 环境变量标记为 **必需** (`readme.md`)。
  - 在 Web UI (登录页及管理页) 顶部添加横幅警告，提示用户 `ADMIN_API_KEY` 未设置 (`app/web/routes.py`, `app/web/templates/_base.html`, `app/web/templates/login.html`)。
  - 在应用程序启动时，如果 `ADMIN_API_KEY` 未设置或无有效 `GEMINI_API_KEYS`，在终端日志中添加 **红色** 警告/错误信息 (`app/main.py`)。

- **修复**: 修复了 API 使用情况报告中“启动时无效 Key 数量”显示为负数的问题。

- **修复**: 解决了 `app/core/usage_reporter.py` 中 Pylance 报告的 `report_lines` 和 `model_total_rpd` 未定义错误。

- **修复**: 纠正了 `app/core/usage_reporter.py` 中 `TPM_WINDOW_WINDOW_SECONDS` 的拼写错误为 `TPM_SECONDS`。

## v1.4.1

- **许可证**: 添加了知识共享署名-非商业性使用 4.0 国际 (CC BY-NC 4.0) 许可证 ([LICENSE](LICENSE), [LICENSE.zh-CN](LICENSE.zh-CN))，并在 README 中添加了说明。

- **新功能：权限管理 (RBAC) 与 Key 有效期** (基于 `rbac_and_key_expiry_plan.md`):
  - 引入管理员角色 (`ADMIN_API_KEY`)，拥有管理所有上下文和代理 Key (文件模式) 的权限。
  - 普通用户登录 Web UI 后仅能查看和管理自己的上下文记录。
  - 管理员可通过 Web UI (`/manage/keys`) 为代理 Key (文件模式) 设置和管理过期时间 (`expires_at`)。
  - 系统在验证代理 Key 时会检查其是否过期。
  - 增强了 JWT 认证，包含管理员状态标识。

- **代码优化**: 重构 `app/api/request_processor.py`，将工具调用处理、速率限制检查和 Token 计数等辅助逻辑移至 `app/api/request_utils.py`，提高代码模块化和可维护性。

- **TODO 清理**: 检查并确认 `app/core/reporting.py` 中的 `report_usage` 和 `_refresh_all_key_scores` 函数无需改为异步实现，并移除了项目中所有相关的 `TODO` 注释。

- **代码清理**: 移除了项目中未使用的函数和注释掉的代码块，提高了代码整洁度。

## v1.4.0

- **新功能**: 在内存模式下支持通过逗号分隔的 `PASSWORD` 环境变量配置多个中转用户 Key。
  - 每个配置的密码/Key都作为一个独立的用户标识符，拥有独立的上下文。
  - 更新了 Web UI 登录和 API 认证逻辑，以验证用户提供的凭证是否在配置的 `PASSWORD` 列表中。
  - 上下文管理现在在内存模式下与用户提供的密码/Key关联。

- **文档更新**: 更新了 `readme.md`，说明了内存模式下多中转用户 Key 的配置和使用方法。

## v1.3.1

- **修复**: 解决了在内存数据库模式下，Web UI 删除上下文后应用可能意外关闭的问题。通过为共享内存数据库连接引入 `asyncio.Lock`，并更新相关数据库操作函数为异步，避免了并发访问冲突。

## v1.3.0

- **Web UI 认证重构**: 使用 JWT (JSON Web Token) 替代 Session Cookie 进行 Web UI 认证，解决登录持久性问题，特别是 Hugging Face Spaces 环境。
  - 新增 `/login` API 端点处理密码验证和 JWT 签发。
  - 新增 `login.html` 模板及前端 JavaScript 实现异步登录和 Token 存储 (`localStorage`)。
  - 更新 `/manage/context` 等受保护路由，使用新的 JWT 依赖项 (`verify_jwt_token`) 进行验证。
  - 基础模板 (`_base.html`) 添加登出按钮和逻辑。

- **功能调整**: 添加了 `/manage/keys` Web UI 用于在**文件存储模式**下管理代理 Key。API 客户端认证方式保持不变（内存模式使用 `PASSWORD`，文件模式使用数据库 `proxy_keys`）。

- **核心上下文管理功能实现**: 完善并最终确定了基于认证凭证的上下文管理机制，包括：SQLite 存储（支持内存/文件模式切换）、基于模型 Token 限制的自动截断、TTL 自动清理、内存模式记录数限制、以及通过 `STREAM_SAVE_REPLY` 控制流式响应保存行为。

- **代码结构优化**:
  - 将认证逻辑拆分到 `app/core/security.py` 和 `app/web/auth.py`。
  - 将数据库设置管理从 `context_store.py` 拆分到 `app/core/db_settings.py`。
  - 将报告和后台任务逻辑从 `reporting.py` 拆分到 `app/core/daily_reset.py`, `app/core/usage_reporter.py`, 并将 Key 分数刷新移至 `app/core/key_management.py`。
  - 确保核心 Python 文件行数大致控制在 300 行以内。

- **本地化**: 将核心 Python 代码中剩余的英文注释和日志消息更新为简体中文。

- **依赖更新**: 添加 `python-jose[cryptography]` 依赖；移除 `SessionMiddleware` 和 `fastapi-csrf-protect`。

- **安全增强**: (CSRF 防护已移除)。

- **模型限制更新**: 更新 `app/data/model_limits.json` 以符合最新的 Google Gemini API 速率限制政策 (Free Tier)，包括调整现有模型 (`gemini-2.5-pro-exp-03-25`) 限制和添加新模型 (`gemini-2.5-flash-preview-04-17`)。

- **(旧版本信息更新)**: 更新了 README 中关于上下文管理和 API 认证的说明，以反映 JWT 认证的变化（例如，Web UI 不再需要代理 Key，API 认证方式不变）。

- **修复**: 修复了状态页面“启动时无效密钥数”显示不正确的问题 (此问题在 v1.3.0 重构前已修复，此处保留记录)。

## v1.2.2

- **修复**: 增加对 Gemini API 请求的读超时时间至 120 秒 (原 `httpx` 默认为 5 秒)，尝试解决处理大型文档或长时生成任务时流式响应可能提前中断的问题 (`app/core/gemini.py`)。

## v1.2.1

- **优化**: 根据 Gemini API 免费层级限制 (RPD, RPM, TPD_Input, TPM_Input) 优化 Key 选择、评分、跟踪和报告逻辑。
- **翻译**: 将项目代码中的英文注释和日志信息翻译为中文（简体）。
- **修复**: 修复了 `gemini.py` 中流式处理 `finish_reason` 的传递问题，以提高 Roo Code 兼容性。
- **修复**: 修复了 `models.py` 中 `Choice` 模型的类型提示错误。
- **修复**: 修复了 `endpoints.py` 中多个缺失的导入错误 (`daily_rpd_totals`, `daily_totals_lock`, `ip_daily_counts`, `ip_counts_lock`, `random`, `config`)。
- **修复**: 修复了 `gemini.py` 中缺失的 `StreamProcessingError` 导入错误。
- **优化**: 优化了 `Dockerfile`，移除了冗余指令。
- **现代化**: 将 `main.py` 中的启动/关闭事件处理从弃用的 `@app.on_event` 迁移到推荐的 `lifespan` 上下文管理器。
- **安全**: 添加 `PROTECT_STATUS_PAGE` 环境变量，允许为根路径 `/` 的状态页面启用密码保护。
- **美化**: 优化了根路径 `/` 状态页面的 HTML 和 CSS，改善视觉效果。

## v1.2.0

- **代码重构**:
  - 将 `app/main.py` 按功能拆分为多个模块 (`config`, `key_management`, `reporting`, `error_handlers`, `middleware`, `endpoints`)。
  - 引入新的子目录结构 (`api/`, `core/`, `handlers/`, `data/`) 以更好地组织代码。
  - 更新了所有受影响文件中的导入语句以适应新结构。

- **Roo Code 兼容性增强**:
  - 修复了 Gemini API 响应缺少助手消息时可能导致 Roo Code 报错的问题（自动补充空助手消息）。
  - 修复了 Gemini 调用 `write_to_file` 工具时缺少 `line_count` 参数可能导致 Roo Code 报错的问题（自动计算并补充）。
  - 增强了 `ResponseWrapper` 以提取工具调用信息。

- **性能优化**:
  - 将 `app/core/gemini.py` 中的 `complete_chat` 函数改为异步 `httpx` 调用，提高非流式请求效率。
  - 优化了 `app/core/reporting.py` 中 `report_usage` 函数的深拷贝逻辑，减少内存占用。

- **文档与注释**:
  - 在 `readme.md` 中添加了 RPD, RPM, TPM 的术语解释。
  - 将所有新增和修改的代码文件及计划文件中的注释翻译为简体中文。
  - 术语统一：为减少混淆，文档和代码注释中原先指代服务访问凭证的“密码” (Password) 已统一更名为“API 密钥” (API Key)。相关环境变量名 `PASSWORD` 保持不变，其作用是设置服务的 API 密钥。

- **其他**:
  - API 使用情况跟踪 (RPM, RPD, TPM) 与智能 Key 选择功能。
  - 修复流式请求 TPM 计数不准确的问题。
  - 修复 `APIKeyManager` 中移除无效 Key 时的线程安全问题。
  - 修复 `protect_from_abuse` 函数中的缩进错误。
  - 优化图片处理逻辑。
  - 其他原有修复和改进。

## v1.1.2

- **新增**: 添加 `DISABLE_SAFETY_FILTERING` 环境变量，允许全局禁用安全过滤。

- **修复**: 修复流式响应中因安全过滤提前中断导致无助手消息的问题。

## v1.1.1

- **新增**: 添加日志轮转和清理机制，防止日志文件过大并自动清理过期日志。

- **增强**: 增强API密钥管理功能，启动时显示所有密钥状态。

- **改进**: 改进日志系统，提供更详细的API请求和错误信息记录。

- **新增**: 添加环境变量 `DEBUG` 用于启用详细日志记录。

## v1.1.0

- **增强客户端兼容性**:
  - 添加空messages检查，防止422错误。
  - 扩展Message模型支持多模态内容。
  - 增强日志记录，便于调试客户端请求。
  - 启动时记录可用模型列表，确保模型名称兼容性。

## v1.0.0

- **初始版本发布**。
