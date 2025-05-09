# 🚀 Gemini API 代理

<!-- 在这里添加徽章 (Badges) -->
<!-- 例如: [![项目状态](https://img.shields.io/badge/status-active-success.svg)](...) -->

[![许可证: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)

本项目 fork 自 [Mrjwj34](https://github.com/Mrjwj34/Hagemi) 的项目进行二次开发（全程使用 AI 编码，模型主要是 gemini-2.5-pro-exp-03-25、gemini-2.5-flash-preview-04-17、gemini-2.0-flash-thinking-exp-01-21）。

这是一个基于 FastAPI 构建的 Gemini API 代理，旨在提供一个简单、安全且可配置的方式来访问 Google 的 Gemini 模型。适用于在 Hugging Face Spaces 上部署，并支持 OpenAI API 格式的工具集成，同时提供 Gemini 原生 API 的直接代理。

## 目录

<!-- TOC start -->

- [🚀 Gemini API 代理](#-gemini-api-代理)
  - [目录](#目录)
  - [✨ 主要功能](#-主要功能)
    - [点击展开/折叠详细功能列表](#点击展开折叠详细功能列表)
      - [🔑 API 密钥轮询和管理](#-api-密钥轮询和管理)
      - [📊 API 使用情况跟踪与智能选择](#-api-使用情况跟踪与智能选择)
      - [📊 术语解释](#-术语解释)
      - [💬 多接口支持 (v1 \& v2)](#-多接口支持-v1--v2)
      - [🖼️ 图片输入处理 (多模态)](#️-图片输入处理-多模态)
      - [🔄 上下文管理与原生缓存](#-上下文管理与原生缓存)
      - [⚠️ 重要提醒 (上下文与缓存)](#️-重要提醒-上下文与缓存)
      - [📝 日志系统](#-日志系统)
      - [🔒 API 密钥保护（可选）](#-api-密钥保护可选)
      - [🚦 速率限制和防滥用](#-速率限制和防滥用)
      - [⚙️ 安全过滤控制（可选）](#️-安全过滤控制可选)
      - [🧩 服务兼容](#-服务兼容)
      - [✨ 代码优化与重构](#-代码优化与重构)
  - [🛠️ 使用方式](#️-使用方式)
    - [🚀 部署到 Hugging Face Spaces](#-部署到-hugging-face-spaces)
    - [💻 本地运行](#-本地运行)
  - [🌐 API 接口说明](#-api-接口说明)
    - [接口版本对比 (v1 vs v2)](#接口版本对比-v1-vs-v2)
    - [OpenAI 兼容接口 (`/v1`)](#openai-兼容接口-v1)
      - [模型列表 (`GET /v1/models`)](#模型列表-get-v1models)
      - [聊天补全 (`POST /v1/chat/completions`)](#聊天补全-post-v1chatcompletions)
      - [如何接入 `/v1` 接口](#如何接入-v1-接口)
    - [Gemini 原生接口 (`/v2`)](#gemini-原生接口-v2)
      - [生成内容 (`POST /v2/models/{model}:generateContent`)](#生成内容-post-v2modelsmodelgeneratecontent)
    - [用户缓存管理接口 (`/api/v1/caches`)](#用户缓存管理接口-apiv1caches)
    - [API 认证 (适用于 `/v1` 和 `/v2`)](#api-认证-适用于-v1-和-v2)
    - [Web UI 认证](#web-ui-认证)
    - [Web UI 功能详情](#web-ui-功能详情)
  - [⚠️ 注意事项](#️-注意事项)
  - [🤝 贡献](#-贡献)
  - [📜 许可证](#-许可证)

<!-- TOC end -->

## ✨ 主要功能

### 点击展开/折叠详细功能列表

#### 🔑 API 密钥轮询和管理

- 支持配置多个 Gemini API 密钥，并进行轮询调用。
- **API Key 存储模式**:
  - 通过 `KEY_STORAGE_MODE` 环境变量支持两种存储模式：
    - `'memory'` (默认): API Key 列表在应用启动时从 `GEMINI_API_KEYS` 环境变量加载到内存。通过 Web UI (`/manage/keys`) 的管理操作仅影响当前会话，重启后会从环境变量重新加载。
    - `'database'`: API Key 及其配置（如上下文补全状态、是否启用等）存储在 SQLite 数据库中，通过 Web UI (`/manage/keys`) 进行持久化管理。
- 自动检测并移除无效或权限不足的 API 密钥。
- 随机化密钥栈，提高负载均衡性能。
- 自动在请求失败时切换到下一个可用密钥。
- **智能选择与切换策略**: 代理会根据 Key 的实时健康度评分（综合考虑 RPD, TPD_Input, RPM, TPM_Input 等指标的剩余量）智能选择最佳 Key。当一个 Key 请求失败或被标记为有问题时，会自动尝试下一个得分最高的可用 Key。引入基于“上次使用时间”的密钥轮转机制，在评分相近的 Key 中优先选择最近最少使用的。
- 启动时显示所有API密钥状态，方便监控和管理。
- 详细的API密钥使用日志，记录每个密钥的使用情况和错误信息。`APIKeyManager` 增加 Key 筛选原因的详细跟踪，并在报告页面 (`/manage/report`) 展示。

#### 📊 API 使用情况跟踪与智能选择

- **使用情况跟踪**: 在程序内存中跟踪每个 API Key 对每个已知模型的 RPM (每分钟请求数), RPD (每日请求数), TPD_Input (每日输入 Token 数), TPM_Input (每分钟输入 Token 数) 使用情况。
- TPM_Input 计数同时支持流式和非流式响应。
- 依赖 `app/data/model_limits.json` 文件定义各模型的限制。
- **每日重置**: RPD 和 TPD_Input 计数根据太平洋时间 (PT) 在每日午夜自动重置。
- **周期性报告与建议**: 定期（默认每 30 分钟，可通过 `USAGE_REPORT_INTERVAL_MINUTES` 环境变量配置）在日志文件中输出各 Key、各模型的使用情况、估算的剩余额度，并根据用量趋势提供 Key 池数量调整建议。报告的日志级别可通过 `REPORT_LOG_LEVEL` 环境变量配置。
- **智能 Key 选择**: 基于各 Key 对目标模型的健康度评分（综合 RPD, TPD_Input, RPM, TPM_Input 剩余百分比）进行智能选择。评分缓存会定期自动更新。
- **健康度评分计算**: 评分综合考虑了 Key 在 RPD, TPD_Input, RPM, TPM_Input 四个维度的剩余额度百分比。
- **本地速率预检查与 Token 预检查**: 在请求发送给 Gemini 前，会根据本地跟踪的使用情况和模型限制进行预检查 (RPD, TPD_Input, RPM, TPM_Input)，并结合当前请求的 Token 数与 Key 的 TPM 限制进行 **Token 预检查**，若判断超限则提前切换 Key。
- **错误处理优化**: 优化了对 5xx、429（区分每日配额和普通速率限制）、401/403/400 (Key 无效) 等错误的临时标记和重试逻辑。流式请求的错误处理不触发外层 Key 重试。

#### 📊 术语解释

- **RPD (Requests Per Day)**: 指每个 API 密钥每天允许的最大请求次数。
- **RPM (Requests Per Minute)**: 指每个 API 密钥每分钟允许的最大请求次数。
- **TPD_Input (Input Tokens Per Day)**: 指每个 API 密钥每天允许处理的最大 *输入* Token 总数。
- **TPM_Input (Input Tokens Per Minute)**: 指每个 API 密钥每分钟允许处理的最大 *输入* Token 总数。

#### 💬 多接口支持 (v1 & v2)

- 提供 `/v1/chat/completions` 接口，与 OpenAI API 格式兼容。
- 提供 `/v2/models/{model}:generateContent` 接口，代理 Gemini 原生 API。
- 自动将 OpenAI 格式的请求转换为 Gemini 格式 (v1)。
- 支持多种 Gemini 模型。
- **模型名称检查**: `app/core/processing/main_handler.py` 中存在模型名称的使用逻辑，但其鲁棒性和对所有支持模型的覆盖情况需结合具体配置评估。

#### 🖼️ 图片输入处理 (多模态)

- 支持 OpenAI 格式 (`/v1`) 和 Gemini 原生格式 (`/v2`) 的多模态消息中的图片输入 (`inline_data`)。
- **仅接受** Base64 编码的数据。
- **支持的图片 MIME 类型**: `image/jpeg`, `image/png`, `image/webp`, `image/heic`, `image/heif`。
- **增强验证**: 使用正则表达式解析 Data URI (v1)，并验证 MIME 类型。
- 上下文存储 (`app/core/context/store.py`) 在存储和加载层面兼容 `inline_data`，但其内部的格式转换函数对 `inline_data` 的处理尚不明确或不完整。

#### 🔄 上下文管理与原生缓存

- **传统上下文管理**:
  - 支持基于认证凭证 (`Authorization: Bearer <credential>`) 的多轮对话上下文保持。
  - **按 Key 配置**: 支持为每个代理 Key 单独配置是否启用上下文补全功能（默认启用）。在数据库存储模式下，可通过 `/manage/keys` Web 界面进行管理。
  - 使用 SQLite 进行上下文存储 (内存模式或文件持久化模式由 `CONTEXT_DB_PATH` 控制)。
  - **动态上下文截断**: 根据 Key 的实时可用 Token 容量和模型静态限制中的较小值进行上下文截断 (`app/core/processing/utils.py`)。
  - 内存模式下定期清理旧上下文。
  - Web 管理界面 (`/manage/context`) 用于查看、删除上下文和配置 TTL。
- **Gemini API 原生缓存支持**:
  - 通过 `ENABLE_NATIVE_CACHING` 环境变量全局启用/禁用 (默认为 `false`)。
  - **与传统上下文互斥**: 如果启用原生缓存，则通常会忽略传统的上下文补全。
  - **缓存查找与创建**: 请求处理流程 (`app/core/processing/main_handler.py`, `app/core/processing/stream_handler.py`) 集成缓存查找和创建逻辑。
  - **Key 与缓存关联**: `CachedContent` 数据库模型 (`app/core/database/models.py`) 包含 `user_id` 和 `key_id` 字段，用于将缓存条目与特定的用户和 API Key 关联起来。在 `APIKeyManager` (`app/core/keys/manager.py`) 的 `select_best_key` 方法中，当启用原生缓存且提供了缓存内容 ID 时，会优先尝试查找并使用与该缓存条目关联的 API Key（通过 `app/core/database/utils.py` 中的 `get_key_id_by_cached_content_id` 和 `get_key_string_by_id` 函数实现）。
  - **用户侧缓存管理**:
    - 提供 API 端点 (`/api/v1/caches`) 允许用户列出和删除自己的缓存条目。
    - 提供 Web UI 页面 (`/manage/caches`) 供用户管理自己的缓存。
  - **后台清理**: 包含缓存清理调度逻辑 (`app/core/cache/cleanup.py`)，该任务会定期自动清理过期的和无效的缓存条目。数据库会话类型不匹配问题已在近期版本中修复。
  - 报告系统 (`app/core/reporting/reporter.py`) 和追踪模块 (`app/core/tracking.py`) 已更新以记录和报告缓存命中、节省 Token 等信息。

#### ⚠️ 重要提醒 (上下文与缓存)

- **传统上下文**与 `Authorization` Header 中提供的凭证严格绑定。
- **原生缓存**也与用户标识和内容相关联。
- **为不同的对话或任务使用相同的凭证可能导致上下文混淆！**
- **原生缓存与传统上下文补全通常是互斥的。**

![Web UI 上下文管理界面截图](assets/images/web-manage-context.png)
*(截图可能需要更新以反映缓存管理界面)*

#### 📝 日志系统

- 完善的日志记录系统，包括应用主日志 (`app.log`) 和错误日志 (`error.log`)。访问日志目前暂未独立配置。
- **日志轮转与清理**:
  - **应用主日志 (`app.log`)**: 采用基于文件大小的轮转 (`RotatingFileHandler`)。当文件达到 `MAX_LOG_SIZE` 时，会创建新的日志文件。
  - **错误日志 (`error.log`)**: 采用基于时间的轮转 (`TimedRotatingFileHandler`)。默认在 `LOG_ROTATION_INTERVAL`（如每天午夜）进行轮转。
  - **备份数量**: `MAX_LOG_BACKUPS` 控制两种日志轮转时保留的备份文件数量。
  - **自动清理**: `LOG_CLEANUP_DAYS` 控制自动清理多少天之前的旧日志文件（包括主日志和错误日志及其备份），以减少磁盘空间占用。
- 详细记录API请求、响应和错误信息，便于问题排查。
- **日志目录**: 优先尝试在项目根目录创建 `logs` 文件夹。如果失败（如权限不足），会尝试系统临时目录，最后尝试当前工作目录。如果均失败，文件日志将被禁用（控制台日志仍然可用）。
- **可通过环境变量自定义日志配置**:
  - `DEBUG`: (布尔值, `true`/`false`) 设置为 `"true"` 时，启用更详细的日志级别 (DEBUG) 和日志格式。默认为 `"false"` (基础日志级别 WARNING, 控制台 INFO)。
  - `MAX_LOG_SIZE`: (整数, 单位 MB) 单个应用主日志文件 (`app.log`) 的最大大小。默认 `10` (MB)。
  - `MAX_LOG_BACKUPS`: (整数) 为 `app.log` 和 `error.log` 保留的轮转备份文件数量。默认 `5`。
  - `LOG_ROTATION_INTERVAL`: (字符串) `error.log` 的轮转时间间隔单位。可选值如 `'midnight'`, `'D'`, `'H'` 等。默认 `'midnight'`。
  - `LOG_CLEANUP_DAYS`: (整数) 日志文件（包括备份）的最大保留天数。默认 `30`。

#### 🔒 API 密钥保护（可选）

- **服务认证凭证**: 通过 `PASSWORD` 环境变量设置。这些凭证用于：
  - **API 请求认证 (内存模式)**: 当 `KEY_STORAGE_MODE` 设置为 `'memory'` 时，API 请求 (`/v1`, `/v2`) 需要使用 `PASSWORD` 中定义的某个值作为 `Bearer` Token 进行认证。
  - **Web UI 登录**: 访问 Web 管理界面 (`/manage/*`, `/report`) 需要使用 `PASSWORD` 中定义的某个值进行登录。
- **多凭证支持**: `PASSWORD` 环境变量支持配置多个凭证，用逗号分隔。每个凭证在内存模式下可以关联独立的对话上下文。
- **重要**: 如果 `KEY_STORAGE_MODE='memory'` 且 `PASSWORD` 未设置，则 API 请求将无法通过认证。如果 `PASSWORD` 未设置，Web UI 登录功能也将无法使用。

#### 🚦 速率限制和防滥用

- 通过环境变量自定义限制：
  - `MAX_REQUESTS_PER_MINUTE`：每分钟最大请求数（默认 60）。
  - `MAX_REQUESTS_PER_DAY_PER_IP`：每天每个 IP 最大请求数（默认 600）。
- 超过速率限制时返回 429 错误。
- 修复了速率限制逻辑中的缩进错误 (v1.2.0)。

#### ⚙️ 安全过滤控制（可选）

- 通过 `DISABLE_SAFETY_FILTERING` 环境变量控制是否全局禁用 Gemini API 的安全过滤。
- 设置为 `"true"` 将对所有请求禁用安全过滤（使用 `OFF` 阈值）。
- 默认为 `"false"`，不进行全局禁用。
- **警告：** 禁用安全过滤可能会导致模型生成不当或有害内容，请谨慎使用。

#### 🧩 服务兼容

- `/v1` 接口与 OpenAI API 格式兼容,便于接入各种服务。
- 支持各种基于 OpenAI API 的应用程序和工具。
- 增强的兼容性处理，支持多种客户端（如Chatbox、Cline、Roo Code等）：
  - 空消息检查：自动检测并处理空messages数组，返回友好的错误信息。
  - 多模态支持：Message模型支持content字段为字符串或字典列表，兼容图片等多模态输入。
  - 增强的日志记录：详细记录请求体内容，便于调试客户端兼容性问题。
  - 模型名称验证：启动时记录可用模型列表，确保客户端使用正确的模型列表，确保客户端使用正确的模型名称。

#### ✨ 代码优化与重构

- **大规模重构**: 核心业务逻辑已迁移到新的 `app/core/` 子目录结构下 (包括 `database`, `keys`, `cache`, `context`, `services`, `processing`, `reporting`, `security`, `utils`)。
- **文件拆分与整合**: 原 `app/api/request_processing.py` 等大型模块已被拆分为更小、更专注的模块。
- **工具函数整合**: 分散的辅助函数已统一到相关的工具模块中 (`app/core/processing/utils.py`)。
- 全面更新了项目中的 `import` 语句。
- 清理了已迁移或废弃的旧文件。
- **本地化**: 为重构过程中涉及的核心 Python 文件添加了全面的中文注释。
- **错误修复**: 修复了重构过程中的 `ImportError`, `NameError` 以及与 SQLAlchemy 2.0 相关的问题。数据库默认路径已调整。
- **文件创建**: 创建了 `app/data/model_limits.json` 文件。

## 🛠️ 使用方式

### 🚀 部署到 Hugging Face Spaces

1. 创建一个新的 Space。
2. 将本项目代码上传到 Space。
3. 在 Space 的 `Settings` -> `Secrets` 中设置以下环境变量：

    | 环境变量                                | 说明                                                                                                                               | 默认值/示例                               |
    | :-------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------- |
    | 环境变量                                | 说明                                                                                                                               | 默认值/示例                               |
    | :-------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------- |

    | `GEMINI_API_KEYS`                       | **（内存模式必需）** 你的 Gemini API 密钥，逗号分隔。仅在 `KEY_STORAGE_MODE='memory'` 时从此加载初始 Key。数据库模式下此变量可选。             | `key1,key2`                               |
    | `ADMIN_API_KEY`                         | （可选）中转服务管理员 API Key，用于访问管理界面和执行管理操作。                                                                         | `your_admin_api_key_here`                 |
    | `SECRET_KEY`                            | **（必需）** 用于 Web UI Session 和 JWT 加密的密钥。**请务必设置一个强随机且唯一的字符串！**                                                 | `a_very_strong_and_random_secret_key`     |
    | `PASSWORD`                              | （可选）用于 Web UI 登录的密码。支持逗号分隔配置多个。如果未设置，Web UI 登录功能将受限。                                                       | `"web_ui_password1,another_password"`     |
    | `KEY_STORAGE_MODE`                      | （可选）控制 **API Key** 的存储方式。可选值：`database` (持久化) 或 `memory` (临时, 重启丢失)。                                       | `memory`                                  |
    | `CONTEXT_DB_PATH`                       | （可选）SQLite **上下文、缓存元数据及 API Key (数据库模式下)** 数据库文件路径。未设置则相关功能使用内存模式。                                | `app/data/gemini_proxy.db`                |
    | `ENABLE_NATIVE_CACHING`                 | （可选）全局默认是否启用 Gemini API 的原生缓存功能。                                                                                         | `false`                                   |
    | `ENABLE_CONTEXT_COMPLETION`             | （可选）全局默认是否启用传统上下文补全功能。若 `ENABLE_NATIVE_CACHING` 为 `true`，此设置通常被忽略。                                          | `true`                                    |
    | `ENABLE_STICKY_SESSION`                 | （可选）Key 选择器是否优先尝试用户上次使用的 Key。                                                                                       | `false`                                   |
    | `DISABLE_SAFETY_FILTERING`              | （可选）是否全局禁用 Gemini API 的安全内容过滤。                                                                                           | `false`                                   |
    | `JWT_ALGORITHM`                         | （可选）用于签名 JWT 的算法。                                                                                                            | `HS256`                                   |
    | `ACCESS_TOKEN_EXPIRE_MINUTES`           | （可选）JWT 访问令牌的有效时间（分钟）。                                                                                                 | `30`                                      |
    | `USAGE_REPORT_INTERVAL_MINUTES`         | （可选）生成使用情况报告的间隔时间（分钟）。                                                                                               | `30`                                      |
    | `REPORT_LOG_LEVEL`                      | （可选）使用情况报告输出到日志的级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)。                                                            | `INFO`                                    |
    | `CACHE_REFRESH_INTERVAL_SECONDS`        | （可选）Key 健康度评分缓存的刷新间隔时间（秒）。                                                                                           | `600`                                     |
    | `DEFAULT_MAX_CONTEXT_TOKENS`            | （可选）默认的最大上下文 Token 数量，用于截断对话历史。                                                                                    | `30000`                                   |
    | `CONTEXT_TOKEN_SAFETY_MARGIN`           | （可选）在截断上下文时保留的安全边际 Token 数。                                                                                            | `200`                                     |
    | `DEFAULT_CONTEXT_TTL_DAYS`              | （可选）上下文记录的默认生存时间（天）。                                                                                                   | `7`                                       |
    | `MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS` | （可选）内存数据库模式下，上下文清理任务的运行间隔（秒）。                                                                                 | `3600`                                    |
    | `MAX_CONTEXT_RECORDS_MEMORY`            | （可选）内存数据库模式下，允许存储的最大上下文记录数量。                                                                                   | `5000`                                    |
    | `CONTEXT_STORAGE_MODE`                  | （可选）控制对话上下文的存储方式 (`database` 或 `memory`)。若为 `database` 但 `CONTEXT_DB_PATH` 未设置，则强制为 `memory`。                 | `memory`                                  |
    | `MAX_REQUESTS_PER_MINUTE`               | （可选，可能已废弃）基于 IP 的每分钟最大请求数限制。                                                                                       | `60`                                      |
    | `MAX_REQUESTS_PER_DAY_PER_IP`           | （可选，可能已废弃）基于 IP 的每日最大请求数限制。                                                                                         | `600`                                     |
    | `PROTECT_STATUS_PAGE`                   | （可选，可能已废弃）是否为状态页面启用密码保护。                                                                                           | `false`                                   |
    | `STREAM_SAVE_REPLY`                     | （可选，可能已废弃）是否在流式响应结束后尝试保存模型回复到上下文。                                                                           | `false`                                   |

4. **（重要）扩展 `app/data/model_limits.json`**: 此文件定义了各个模型的速率限制和 Token 限制，对于 API 使用情况跟踪和上下文截断功能至关重要。请根据你使用的模型和官方文档进行配置。文件结构示例：

    ```json
    {
      "gemini-1.5-pro-latest": {
        "rpd": 1000, // 每日请求数
        "rpm": 60,   // 每分钟请求数
        "tpd_input": 2000000, // 每日输入 Token 数
        "tpm_input": 32000,   // 每分钟输入 Token 数
        "input_token_limit": 1048576, // 模型最大输入 Token
        "output_token_limit": 8192   // 模型最大输出 Token
      },
      "gemini-1.0-pro": {
        "rpd": 1500,
        "rpm": 100,
        "tpd_input": 3000000,
        "tpm_input": 60000,
        "input_token_limit": 30720,
        "output_token_limit": 2048
      }
      // ... 其他模型
    }
    ```

5. 确保 `requirements.txt` 文件已包含必要的依赖。
6. Space 将会自动构建并运行。

### 💻 本地运行

1. 克隆项目代码到本地。
2. 安装依赖：`pip install -r requirements.txt`
3. **（重要）创建并扩展模型限制文件 `app/data/model_limits.json`**: ... (保持不变) ...
4. **配置环境变量：**
    - **（推荐）** 在项目根目录创建 `.env` 文件，并填入以下内容（根据需要取消注释并修改）：

        ```dotenv
        # .env 文件示例

        # --- 必需 ---
        # (必需) Web UI 和 JWT 密钥 - 请替换为一个强随机字符串！
        SECRET_KEY=your_very_strong_random_secret_key_here

        # --- API Key 相关 ---
        # (内存模式必需) Gemini API 密钥, 逗号分隔。仅当 KEY_STORAGE_MODE=memory 时使用。
        # GEMINI_API_KEYS=YOUR_API_KEY_1,YOUR_API_KEY_2

        # (可选) API Key 存储模式 ('database' 或 'memory')
        KEY_STORAGE_MODE=memory # 或 database

        # --- 数据库路径 (如果使用 'database' 模式或需要持久化上下文/缓存) ---
        # (可选) SQLite 数据库文件路径。用于上下文、缓存元数据，以及 KEY_STORAGE_MODE=database 时的 API Key。
        # CONTEXT_DB_PATH="app/data/gemini_proxy.db"

        # --- 认证与授权 ---
        # (可选) 管理员 API Key (用于管理接口)
        # ADMIN_API_KEY=your_admin_api_key_here

        # (可选) Web UI 登录密码, 逗号分隔
        # PASSWORD="web_ui_password1,another_password"

        # --- 功能开关 ---
        # (可选) 全局启用原生缓存 (true/false)
        # ENABLE_NATIVE_CACHING=false
        # (可选) 全局启用传统上下文补全 (true/false)
        # ENABLE_CONTEXT_COMPLETION=true
        # (可选) 启用粘性会话 (true/false)
        # ENABLE_STICKY_SESSION=false
        # (可选) 全局禁用安全过滤 (true/false) - 谨慎使用!
        # DISABLE_SAFETY_FILTERING=false

        # --- 速率与报告 ---
        # (可选) Key 健康度评分缓存刷新间隔 (秒)
        # CACHE_REFRESH_INTERVAL_SECONDS=600
        # (可选) 使用情况报告间隔 (分钟)
        # USAGE_REPORT_INTERVAL_MINUTES=30
        # (可选) 报告日志级别 (INFO, DEBUG, WARNING, etc.)
        # REPORT_LOG_LEVEL=INFO

        # --- 上下文管理 ---
        # (可选) 上下文存储模式 ('database' 或 'memory')
        # CONTEXT_STORAGE_MODE=memory
        # (可选) 默认最大上下文 Token
        # DEFAULT_MAX_CONTEXT_TOKENS=30000
        # (可选) 上下文 Token 安全边际
        # CONTEXT_TOKEN_SAFETY_MARGIN=200
        # (可选) 默认上下文 TTL (天)
        # DEFAULT_CONTEXT_TTL_DAYS=7
        # (可选) 内存上下文清理间隔 (秒)
        # MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS=3600
        # (可选) 内存上下文最大记录数
        # MAX_CONTEXT_RECORDS_MEMORY=5000

        # --- JWT 配置 ---
        # (可选) JWT 算法
        # JWT_ALGORITHM=HS256
        # (可选) JWT 访问令牌过期时间 (分钟)
        # ACCESS_TOKEN_EXPIRE_MINUTES=30

        # --- 可能已废弃的旧版速率限制 ---
        # MAX_REQUESTS_PER_MINUTE=60
        # MAX_REQUESTS_PER_DAY_PER_IP=600
        ```

    - **（或者）** 直接在终端设置环境变量。

5. 运行：

    ```bash
    uvicorn app.main:app --reload --host 0.0.0.0 --port 7860
    ```

## 🌐 API 接口说明

本项目提供两套 API 接口，以满足不同的使用场景：

- **`/v1` (OpenAI 兼容接口):** 旨在最大程度兼容 OpenAI API，方便接入现有生态工具。
- **`/v2` (Gemini 原生接口):** 提供对 Gemini 原生 API 功能的直接代理。

### 接口版本对比 (v1 vs v2)

| 特性         | `/v1` (OpenAI 兼容)                     | `/v2` (Gemini 原生)                      |
| :----------- | :-------------------------------------- | :--------------------------------------- |
| **目标**     | 兼容 OpenAI 生态，易于集成现有工具        | 提供 Gemini 原生功能，更直接的访问方式     |
| **主要端点** | `/v1/models`, `/v1/chat/completions`    | `/v2/models/{model}:generateContent`     |
| **请求格式** | OpenAI Chat Completion 格式             | Gemini `generateContent` 格式            |
| **响应格式** | OpenAI Chat Completion 格式             | Gemini `generateContent` 响应格式        |
| **多模态**   | 支持 `image_url` (Base64 Data URI)      | 支持 `inline_data` (Base64)              |
| **上下文**   | 支持 (与认证凭证绑定)                   | 支持 (与认证凭证绑定)                    |
| **适用场景** | 接入 Chatbox, Roo Code 等 OpenAI 工具   | 需要直接调用 Gemini 特定功能的场景         |

### OpenAI 兼容接口 (`/v1`)

这套接口主要用于兼容需要 OpenAI API 格式的客户端或服务。

#### 模型列表 (`GET /v1/models`)

```bash
GET /v1/models
```

返回当前配置的 Gemini API 密钥可访问的所有模型列表，格式符合 OpenAI `/v1/models` 接口规范。

#### 聊天补全 (`POST /v1/chat/completions`)

```bash
POST /v1/chat/completions
```

接收 OpenAI Chat Completion 格式的请求，将其转换为 Gemini API 请求，并将 Gemini 的响应转换回 OpenAI 格式。支持流式 (`stream: true`) 和非流式响应。

**请求体示例:**

```json
{
  "model": "gemini-1.5-pro-latest",
  "messages": [
    {"role": "system", "content": "你是一个有用的助手。"},
    {"role": "user", "content": "你好！"}
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "stream": false
}
```

#### 如何接入 `/v1` 接口

在需要配置 OpenAI API 的客户端或服务中：

1. **API Base URL / API 端点:** 填入你的代理服务地址，并**必须**以 `/v1` 结尾。
    - Hugging Face Spaces: `https://your-space-url.hf.space/v1`
    - 本地运行: `http://localhost:7860/v1` (或其他你配置的地址和端口)
2. **API Key:** 填入你的认证凭证 (详见下方的 [API 认证](#api-认证-适用于-v1-和-v2) 部分)。

### Gemini 原生接口 (`/v2`)

这套接口旨在提供对 Gemini 原生 API 功能的直接代理，请求和响应格式与 Google AI Gemini API 基本一致。

#### 生成内容 (`POST /v2/models/{model}:generateContent`)

```bash
POST /v2/models/{model}:generateContent
```

代理 Gemini API 的 `generateContent` 方法。`{model}` 部分需要替换为具体的模型 ID，例如 `gemini-1.5-pro-latest`。

**请求体示例 (基于 Gemini 原生 API 规范):**

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {"text": "你好！"}
      ]
    },
    {
      "role": "model",
      "parts": [
        {"text": "你好！有什么可以帮助你的吗？"}
      ]
    },
    {
      "role": "user",
      "parts": [
        {"text": "请写一首关于人工智能的诗。"}
      ]
    }
  ],
  "generation_config": {
    "temperature": 0.9,
    "top_p": 1.0,
    "max_output_tokens": 800
  }
}
```

**注意:** `/v2` 接口目前仅实现了 `generateContent` 端点。其他原生 API 功能（如嵌入、计数 Token 等）将在未来版本中逐步支持。

### 用户缓存管理接口 (`/api/v1/caches`)

- **`GET /api/v1/caches`**: 列出当前认证用户的所有缓存条目。
- **`DELETE /api/v1/caches/{cache_id}`**: 删除当前认证用户指定的缓存条目。

    *这两个接口需要通过 API 认证。*

### API 认证 (适用于 `/v1` 和 `/v2`)

所有对 `/v1` 和 `/v2` API 端点的请求都需要通过 HTTP `Authorization` Header 进行认证：

```text
Authorization: Bearer <YOUR_AUTH_CREDENTIAL>
```

`<YOUR_AUTH_CREDENTIAL>` 的值取决于你的部署模式：

- **数据库模式 (`KEY_STORAGE_MODE='database'`):** 凭证是数据库 `apikeys` 表中有效的、已启用的 API Key。
- **内存模式 (`KEY_STORAGE_MODE='memory'`):** 凭证是 `PASSWORD` 环境变量中配置的某个值。

### Web UI 认证

访问 Web 管理界面 (`/`, `/manage/context`, `/manage/keys`, `/report`) 需要进行登录认证：

1. 访问 `/login` 页面。
2. 使用 `PASSWORD` 环境变量中配置的**某个**值作为密码进行登录。
3. 登录成功后，浏览器会存储一个 JWT (JSON Web Token) 用于后续的会话认证。
4. **此功能需要设置 `SECRET_KEY` 环境变量**，用于 JWT 的签名和加密。

### Web UI 功能详情

- **`/manage/context` 页面**: 管理对话上下文。
- **`/manage/keys` 页面**:
  - **数据库模式**: 管理持久化的代理 Key (添加、删除、启用/禁用、配置上下文补全)。
  - **内存模式**: 临时管理从环境变量加载的 Key (操作不持久)。
- **`/manage/caches` 页面**: 查看和删除当前登录用户自己的缓存条目。
- **`/manage/report` 报告页**: 展示详细的 API 使用情况报告，包括 Key 使用统计和缓存命中信息。

## ⚠️ 注意事项

- **强烈建议在生产环境中设置 `PASSWORD` 环境变量（作为 API 密钥），并使用强密钥。**
- 根据你的使用情况调整速率限制相关的环境变量。
- 确保你的 Gemini API 密钥具有足够的配额。
- 日志文件存储在项目根目录的 `logs` 文件夹中（如果权限允许，否则在临时目录），定期检查以确保磁盘空间充足。
- 默认情况下，超过30天的日志文件会被自动清理。
- 谨慎使用 `DISABLE_SAFETY_FILTERING` 选项，了解禁用安全过滤的潜在风险。
- **API 使用情况跟踪和上下文截断功能依赖 `app/data/model_limits.json` 文件，请确保该文件存在且为相关模型配置了 `input_token_limit`。**
- **Web UI 认证需要设置 `SECRET_KEY` 环境变量。**
- **API 上下文管理 (文件模式):** 需要通过 `/manage/keys` Web UI 管理代理 Key 的添加、删除、启用/禁用，**以及配置每个 Key 的上下文补全状态**。
- **存储模式:**
  - **上下文存储:** 默认使用内存数据库，上下文在重启时丢失。可通过 `CONTEXT_DB_PATH` 环境变量启用基于 SQLite 文件的持久化存储。
  - **API Key 存储:** 通过 `KEY_STORAGE_MODE` 环境变量控制。
    - `'memory'` (默认): Key 列表在启动时从 `GEMINI_API_KEYS` 环境变量加载。通过 `/manage/keys` 界面的添加、编辑、删除操作仅影响当前内存状态，**不会被持久化**，应用重启后会从环境变量重新加载。
    - `'database'`: Key 信息存储在 SQLite 数据库中，所有通过 `/manage/keys` 界面的更改都会被持久化。
- **多进程/Worker 注意:** 在使用内存数据库（包括共享内存模式）且部署环境使用多个工作进程（如默认的 Uvicorn 或 Gunicorn 配置）时，为确保数据库状态一致性，**建议配置为仅使用单个工作进程** (例如 `uvicorn ... --workers 1`)。否则，不同进程可能无法看到一致的数据库状态。
- **⚠️ 上下文管理关键点:** 上下文与认证凭证 (API Key/代理 Key) 绑定。**切勿对不同的对话/任务使用相同的 Key，否则会导致上下文错乱！** 请为每个独立上下文分配唯一的 Key。**上下文补全的启用/禁用状态也与 Key 绑定，可在数据库模式下通过 `/manage/keys` 界面配置，内存模式下默认为启用且临时修改无效。**

## 🤝 贡献

欢迎各种形式的贡献！

- **报告 Bug:** 如果你发现了问题，请在 [Issues](https://github.com/MisonL/GAP/issues) 中提交详细的 Bug 报告。
- **功能请求:** 如果你有新的功能想法，也请在 [Issues](https://github.com/MisonL/GAP/issues) 中提出。
- **代码贡献:** 如果你想贡献代码，请先 Fork 本仓库，在你的分支上进行修改，然后提交 Pull Request。

## 📜 许可证

本项目采用 **知识共享署名-非商业性使用 4.0 国际许可协议 (Creative Commons Attribution-NonCommercial 4.0 International License)** 进行许可。

这意味着您可以自由地：

- **共享** — 在任何媒介以任何形式复制、发行本作品
- **演绎** — 修改、转换或以本作品为基础进行创作

只要你遵守许可协议条款，许可人就无法收回你的这些权利。

惟须遵守下列条件：

- **署名 (BY)** — 您必须给出适当的署名，提供指向本许可协议的链接，同时标明是否（对原始作品）作了修改。您可以用任何合理的方式来署名，但是不得以任何方式暗示许可人为您或您的使用背书。
- **非商业性使用 (NC)** — 您不得将本作品用于商业目的。

没有附加限制 — 您不得适用法律术语或者技术措施从而限制其他人做许可协议允许的事情。

**注意:**

- 您不必因为公共领域的作品要素而遵守许可协议，或者您的使用被可适用的例外或限制所允许。
- 不提供担保。许可协议可能不会给与您意图使用的所必须的所有许可。例如，其他权利比如形象权、隐私权或人格权可能限制您如何使用作品。

完整的许可证文本可以在 [LICENSE](LICENSE) (英文) 和 [LICENSE.zh-CN](LICENSE.zh-CN) (简体中文) 文件中找到，或者访问 [Creative Commons 网站](https://creativecommons.org/licenses/by-nc/4.0/legalcode.zh-CN)。

作为本项目的原始作者，我保留将此项目用于商业目的或以其他不同许可证授权的权利。
