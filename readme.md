# 🚀 Gemini API 代理

<!-- 在这里添加徽章 (Badges) -->
<!-- 例如: [![项目状态](https://img.shields.io/badge/status-active-success.svg)](...) -->
[![许可证: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)

本项目 fork 自 [Mrjwj34](https://github.com/Mrjwj34/Hagemi) 的项目进行二次开发（全程使用 AI 编码，模型主要是 Gemini-2.5-pro-exp-03-25、gemini-2.5-flash-preview-04-17、gemini-2.0-flash-thinking-exp-01-21）。

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
      - [🔄 上下文管理](#-上下文管理)
      - [⚠️ 重要提醒 (上下文管理)](#️-重要提醒-上下文管理)
      - [📝 日志系统](#-日志系统)
      - [🔒 API 密钥保护（可选）](#-api-密钥保护可选)
      - [🚦 速率限制和防滥用](#-速率限制和防滥用)
      - [⚙️ 安全过滤控制（可选）](#️-安全过滤控制可选)
      - [🧩 服务兼容](#-服务兼容)
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
    - [API 认证 (适用于 `/v1` 和 `/v2`)](#api-认证-适用于-v1-和-v2)
    - [Web UI 认证](#web-ui-认证)
  - [⚠️ 注意事项](#️-注意事项)
  - [🤝 贡献](#-贡献)
  - [📜 许可证](#-许可证)

<!-- TOC end -->

## ✨ 主要功能

### 点击展开/折叠详细功能列表

#### 🔑 API 密钥轮询和管理

- 支持配置多个 Gemini API 密钥，并进行轮询调用。
- 自动检测并移除无效或权限不足的 API 密钥，避免重复尝试 (已修复线程安全问题)。
- 随机化密钥栈，提高负载均衡性能。
- 自动在请求失败时切换到下一个可用密钥。
- 启动时显示所有API密钥状态，方便监控和管理。
- 详细的API密钥使用日志，记录每个密钥的使用情况和错误信息。

#### 📊 API 使用情况跟踪与智能选择

- **使用情况跟踪**: 在程序内存中跟踪每个 API Key 对每个已知模型的 RPM (每分钟请求数), RPD (每日请求数), TPD_Input (每日输入 Token 数), TPM_Input (每分钟输入 Token 数) 使用情况。
- TPM_Input 计数同时支持流式和非流式响应。
- 依赖 `app/data/model_limits.json` 文件定义各模型的限制 (已更新以包含输入 Token 限制)。
- **每日重置**: RPD 和 TPD_Input 计数根据太平洋时间 (PT) 在每日午夜自动重置。
- **周期性报告与建议**: 定期（默认每 30 分钟，可通过 `USAGE_REPORT_INTERVAL_MINUTES` 环境变量配置）在日志文件中输出各 Key、各模型的使用情况、估算的剩余额度，并根据用量趋势提供 Key 池数量调整建议 (报告内容已更新以包含输入 Token 指标，建议逻辑已调整)。报告的日志级别可通过 `REPORT_LOG_LEVEL` 环境变量配置（默认为 INFO），方便在特定环境（如 Hugging Face Spaces中设为WARNING才能在终端日志中谁出）中查看。
- **智能 Key 选择**: 基于各 Key 对目标模型的健康度评分（综合 RPD, TPD_Input, RPM, TPM_Input 剩余百分比，权重已调整）进行智能选择，优化 Key 利用率。评分缓存会定期自动更新。
- **本地速率预检查**: 在请求发送给 Gemini 前，会根据本地跟踪的使用情况和模型限制进行预检查 (RPD, TPD_Input, RPM, TPM_Input)，若判断超限则提前切换 Key，减少对 API 的无效请求。

#### 📊 术语解释

- **RPD (Requests Per Day)**: 指每个 API 密钥每天允许的最大请求次数。这是 Gemini API 对每个密钥设定的日请求总量限制。
- **RPM (Requests Per Minute)**: 指每个 API 密钥每分钟允许的最大请求次数。这是 Gemini API 对请求频率的限制。
- **TPD_Input (Input Tokens Per Day)**: 指每个 API 密钥每天允许处理的最大 *输入* Token 总数。
- **TPM_Input (Input Tokens Per Minute)**: 指每个 API 密钥每分钟允许处理的最大 *输入* Token 总数。

  *本代理程序会跟踪这些指标，用于智能选择可用密钥并进行本地速率预检查。*

#### 💬 多接口支持 (v1 & v2)

- 提供 `/v1/chat/completions` 接口，与 OpenAI API 格式兼容，支持流式和非流式响应。
- 提供 `/v2/models/{model}:generateContent` 接口，代理 Gemini 原生 API。
- 自动将 OpenAI 格式的请求转换为 Gemini 格式 (v1)。
- 支持多种 Gemini 模型，包括最新的 Gemini 1.5 系列。

#### 🖼️ 图片输入处理 (多模态)

- 支持 OpenAI 格式 (`/v1`) 和 Gemini 原生格式 (`/v2`) 的多模态消息中的图片输入。
- **仅接受** Base64 编码的数据。
  - `/v1`: 使用 Data URI 格式 (`data:image/...;base64,...`)。
  - `/v2`: 使用 `inline_data` 字段 (包含 `mime_type` 和 `data`)。
- **增强验证**: 使用正则表达式解析 Data URI (v1)，并验证 MIME 类型是否为 Gemini 支持的格式 (JPEG, PNG, WebP, HEIC, HEIF)，提高了处理健壮性。

#### 🔄 上下文管理

- 支持基于认证凭证 (`Authorization: Bearer <credential>`) 的多轮对话上下文保持。在内存模式下，此凭证是 `PASSWORD` 环境变量中的某个值；在文件模式下，是数据库中的代理 Key。
- **上下文补全功能同时适用于 `/v1` (OpenAI 兼容) 和 `/v2` (Gemini 原生) 接口。**
- **按 Key 配置:** 支持为每个代理 Key 单独配置是否启用上下文补全功能（默认启用）。在文件存储模式下，可通过 `/manage/keys` Web 界面进行管理。
- 使用 SQLite 进行上下文存储。**默认使用内存模式** (`:memory:`)，适用于 HF Spaces 免费层（重启丢失数据）。可通过 `CONTEXT_DB_PATH` 环境变量启用**文件持久化存储**。
- 根据模型 `input_token_limit` (在 `model_limits.json` 中配置) 自动截断过长的上下文。
- 内存模式下，会定期自动清理超过 TTL 设置的旧上下文，防止内存溢出。
- 提供 Web 管理界面 (`/manage`) 用于管理上下文（查看、删除、配置 TTL）。
- **新增 (文件模式):** 提供 `/manage/keys` 界面，用于在**文件存储模式** (`CONTEXT_DB_PATH` 已设置) 下管理代理 Key (添加、启用/禁用、删除，**以及配置上下文补全状态**)。
- **清除上下文:** 可在 `/manage/context` Web 界面中选择并删除特定 Key 关联的对话历史。

#### ⚠️ 重要提醒 (上下文管理)

上下文与 `Authorization` Header 中提供的凭证严格绑定。

- 在**内存模式**下，此凭证是 `PASSWORD` 环境变量中配置的**某个**值。
- 在**文件模式**下，此凭证是数据库中有效的代理 Key。

**为不同的对话或任务使用相同的凭证会导致上下文混淆！请务必为每个独立的对话/任务使用不同的凭证 (即在内存模式下使用不同的密码，或在文件模式下使用不同的代理 Key)。**

![Web UI 上下文管理界面截图](assets/images/web-manage-context.png)

#### 📝 日志系统

- 完善的日志记录系统，包括应用日志、错误日志和访问日志。
- 支持日志轮转功能，防止日志文件过大：
  - 基于大小的轮转：当日志文件达到指定大小时自动创建新文件。
  - 基于时间的轮转：按照指定的时间间隔（如每天午夜）自动创建新文件。
- 自动清理过期日志文件，默认保留30天，减少磁盘空间占用。
- 详细记录API请求、响应和错误信息，便于问题排查。
- 可通过环境变量自定义日志配置：
  - `MAX_LOG_SIZE`：单个日志文件最大大小（默认10MB）。
  - `MAX_LOG_BACKUPS`：保留的日志文件备份数量（默认5个）。
  - `LOG_ROTATION_INTERVAL`：日志轮转间隔（默认每天午夜）。
  - `DEBUG`：设置为 "true" 启用详细日志记录。

#### 🔒 API 密钥保护（可选）

- 通过 `PASSWORD` 环境变量设置服务的认证凭证（用于内存模式和 Web UI 登录）。
- 支持逗号分隔配置多个凭证，每个凭证对应独立的上下文。
- 提供默认 API 密钥 `"123"`。

#### 🚦 速率限制和防滥用

- 通过环境变量自定义限制：
  - `MAX_REQUESTS_PER_MINUTE`：每分钟最大请求数（默认 30）。
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
- 增强的兼容性处理，支持多种客户端（如Chatbox、Roo Code等）：
  - 空消息检查：自动检测并处理空messages数组，返回友好的错误信息。
  - 多模态支持：Message模型支持content字段为字符串或字典列表，兼容图片等多模态输入。
  - 增强的日志记录：详细记录请求体内容，便于调试客户端兼容性问题。
  - 模型名称验证：启动时记录可用模型列表，确保客户端使用正确的模型列表，确保客户端使用正确的模型名称。

## 🛠️ 使用方式

### 🚀 部署到 Hugging Face Spaces

1. 创建一个新的 Space。
2. 将本项目代码上传到 Space。
3. 在 Space 的 `Settings` -> `Secrets` 中设置以下环境变量：

    | 环境变量                                | 说明                                                                                                                               | 默认值/示例                               |
    | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
    | `GEMINI_API_KEYS`                       | **（必需）** 你的 Gemini API 密钥，用逗号分隔。                                                                                       | `key1,key2,key3`                          |
    | `ADMIN_API_KEY`                         | **（必需）** 中转服务管理员 API Key，用于管理所有上下文和 Key（文件模式）。拥有最高权限。 | `your_admin_api_key_here`                 |
    | `PASSWORD`                              | （可选）设置服务的 API 密钥（用于内存模式认证和 Web UI 登录）。**在内存模式下，支持逗号分隔配置多个 Key，每个 Key 对应一个独立的用户和上下文。** | `"123,password2,password3"`               |
    | `SECRET_KEY`                            | **（必需）** 用于 Web UI Session 和 JWT 加密的密钥。请设置一个长而随机的字符串。                                                          |                                           |
    | `MAX_REQUESTS_PER_MINUTE`               | （可选）每分钟最大请求数。                                                                                                           | `30`                                      |
    | `MAX_REQUESTS_PER_DAY_PER_IP`           | （可选）每天每个 IP 最大请求数（默认 600）。                                                                                                       | `600`                                     |
    | `MAX_LOG_SIZE`                          | （可选）单个日志文件最大大小（MB）。                                                                                                   | `10`                                      |
    | `MAX_LOG_BACKUPS`                       | （可选）保留的日志文件备份数量（默认5个）。                                                                                                       | `5`                                       |
    | `LOG_ROTATION_INTERVAL`                 | （可选）日志轮转间隔。                                                                                                               | `midnight`                                |
    | `DEBUG`                                 | （可选）设置为 `"true"` 启用详细日志记录。                                                                                             | `false`                                   |
    | `DISABLE_SAFETY_FILTERING`              | （可选）设置为 `"true"` 将全局禁用 Gemini API 的安全过滤。**警告：** 可能导致不当内容。                                                    | `false`                                   |
    | `USAGE_REPORT_INTERVAL_MINUTES`         | （可选）周期性使用情况报告的间隔时间（分钟）。                                                                                         | `30`                                      |
    | `REPORT_LOG_LEVEL`                      | （可选）周期性报告的日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）。设为 `WARNING` 可在 HF Logs 显示。                               | `INFO`                                    |
    | `PROTECT_STATUS_PAGE`                   | （可选）设置为 `"true"` 将对根路径 `/` 的状态页面启用密码保护（使用 `PASSWORD`）。                                                       | `false`                                   |
    | `CONTEXT_DB_PATH`                       | （可选）设置此路径以启用基于文件的 SQLite 存储。**未设置则使用内存数据库 (`:memory:`)。**                                                |                                           |
    | `DEFAULT_MAX_CONTEXT_TOKENS`            | （可选）当模型未在 `model_limits.json` 中定义时的回退 Token 限制。                                                                     | `30000`                                   |
    | `CONTEXT_TOKEN_SAFETY_MARGIN`           | （可选）从模型 `input_token_limit` 减去的安全边际。                                                                                    | `200`                                     |
    | `MEMORY_CONTEXT_CLEANUP_INTERVAL_SECONDS` | （可选）内存数据库模式下，后台清理任务的运行间隔（秒）。                                                                                 | `3600`                                    |
    | `MAX_CONTEXT_RECORDS_MEMORY`            | （可选）内存数据库模式下，允许存储的最大上下文记录条数。                                                                                 | `5000`                                    |
    | `JWT_ALGORITHM`                         | （可选）JWT 签名算法。                                                                                                               | `HS256`                                   |
    | `ACCESS_TOKEN_EXPIRE_MINUTES`           | （可选）Web UI 登录 JWT 的有效期（分钟）。                                                                                             | `30`                                      |
    | `CACHE_REFRESH_INTERVAL_SECONDS`        | （可选）Key 分数缓存刷新间隔（秒）。                                                                                                   | `10`                                      |
    | `STREAM_SAVE_REPLY`                     | （可选）设置为 `"true"` 时，流式响应结束后会尝试保存包含模型回复的完整上下文。                                                              | `false`                                   |

4. **（重要）扩展 `app/data/model_limits.json`**: 确保此文件存在，并且为需要进行上下文截断的模型添加了 `"input_token_limit"` 字段（参考 Google 官方文档）。
5. 确保 `requirements.txt` 文件已包含必要的依赖 (`jinja2`, `starlette[full]` 等)。
6. Space 将会自动构建并运行。
7. URL格式为`https://your-space-url.hf.space`。

### 💻 本地运行

1. 克隆项目代码到本地。
2. 安装依赖：`pip install -r requirements.txt` (确保包含 `python-multipart` 等以支持所有功能)
3. **（重要）创建并扩展模型限制文件：** 在 `app/data/` 目录下创建 `model_limits.json` 文件。定义模型的 RPM, RPD, TPD_Input, TPM_Input 限制，并且**为需要进行上下文截断的模型添加 `"input_token_limit"` 字段**（参考 Google 官方文档）。示例：

    ```json
    {
      "gemini-1.5-flash-latest": {"rpm": 15, "tpm_input": 1000000, "rpd": 1500, "tpd_input": null, "input_token_limit": 1048576},
      "gemini-1.5-pro-latest": {"rpm": 2, "tpm_input": 32000, "rpd": 50, "tpd_input": null, "input_token_limit": 2097152}
      // ... 其他模型
    }
    ```

4. **配置环境变量：**
    - **（推荐）** 在项目根目录创建 `.env` 文件，并填入以下内容（根据需要取消注释并修改）：
      下面是一个 `.env` 文件内容的示例。请根据需要取消注释并修改值。**详细的环境变量说明请参考上方“部署到 Hugging Face Spaces”部分的表格。**

      ```dotenv
      # .env 文件示例

      # (必需) Gemini API 密钥，逗号分隔
      GEMINI_API_KEYS=YOUR_API_KEY_1,YOUR_API_KEY_2

      # (必需) Web UI 和 JWT 密钥
      SECRET_KEY=your_very_strong_random_secret_key_here

      # (可选) 服务 API 密钥 (内存模式认证 & Web UI 登录)
      # 在内存模式下，支持逗号分隔配置多个 Key，每个 Key 对应一个独立的用户和上下文。
      PASSWORD="123,password2,password3"

      # (可选) 启用文件存储上下文 (否则使用内存)
      # CONTEXT_DB_PATH=app/data/context_store.db

      # (可选) 启用调试日志
      # DEBUG=true

      # (可选) 禁用安全过滤 (谨慎使用!)
      # DISABLE_SAFETY_FILTERING=true

      # ... 其他可选环境变量参考上方表格 ...
      ```

    - **（或者）** 直接在终端设置环境变量（仅对当前会话有效）：

      ```bash
      export GEMINI_API_KEYS="key1,key2"
      export SECRET_KEY="your_secret"
      export PASSWORD="your_password"
      # ... 其他环境变量

      ```

5. 运行：`uvicorn app.main:app --reload --host 0.0.0.0 --port 7860`

## 🌐 API 接口说明

本项目提供两套 API 接口，以满足不同的使用场景：

- **`/v1` (OpenAI 兼容接口):** 旨在最大程度兼容 OpenAI API，方便接入现有生态工具。
- **`/v2` (Gemini 原生接口):** 提供对 Gemini 原生 API 功能的直接代理。

### 接口版本对比 (v1 vs v2)

| 特性         | `/v1` (OpenAI 兼容)                     | `/v2` (Gemini 原生)                      |
| ------------ | --------------------------------------- | ---------------------------------------- |
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
  "model": "gemini-1.5-pro-latest",  // 或其他支持的模型
  "messages": [
    {"role": "system", "content": "你是一个有用的助手。"}, // system 角色的内容会被合并到第一个 user 消息中
    {"role": "user", "content": "你好！"}
    // 支持图片输入 (使用 Base64 Data URI)
    // {"role": "user", "content": [
    //   {"type": "text", "text": "描述这张图片"},
    //   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    // ]}
  ],
  "temperature": 0.7,
  "max_tokens": 1024, // 注意：Gemini 使用 max_output_tokens，这里会做转换
  "stream": false  // 设置为 true 启用流式响应
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
        // 支持多模态输入，例如图片 (使用 Base64 Data URI)
        // {"inline_data": {"mime_type": "image/jpeg", "data": "/9j/4AAQSkZJRg..."}}
      ]
    }
  ],
  "generation_config": {
    "temperature": 0.9,
    "top_p": 1.0,
    "max_output_tokens": 800
  },
  "safety_settings": [
    // 根据需要配置安全设置
    // {
    //   "category": "HARM_CATEGORY_HARASSMENT",
    //   "threshold": "BLOCK_MEDIUM_AND_ABOVE"
    // }
  ]
}
```

**注意:** `/v2` 接口目前仅实现了 `generateContent` 端点。其他原生 API 功能（如嵌入、计数 Token 等）将在未来版本中逐步支持。

### API 认证 (适用于 `/v1` 和 `/v2`)

所有对 `/v1` 和 `/v2` API 端点的请求都需要通过 HTTP `Authorization` Header 进行认证：

```text
Authorization: Bearer <YOUR_AUTH_CREDENTIAL>
```

`<YOUR_AUTH_CREDENTIAL>` 的值取决于你的部署模式：

- **内存模式 (默认, 如 HF Spaces):** 凭证是 `PASSWORD` 环境变量中配置的**某个**值。例如，如果 `PASSWORD="123,abc"`，则可以使用 `Bearer 123` 或 `Bearer abc`。
- **文件模式 (`CONTEXT_DB_PATH` 已设置):** 凭证是数据库 `proxy_keys` 表中有效的代理 Key (可通过 `/manage/keys` Web UI 管理)。

### Web UI 认证

访问 Web 管理界面 (`/`, `/manage/context`, `/manage/keys`, `/report`) 需要进行登录认证：

1. 访问 `/login` 页面。
2. 使用 `PASSWORD` 环境变量中配置的**某个**值作为密码进行登录。
3. 登录成功后，浏览器会存储一个 JWT (JSON Web Token) 用于后续的会话认证。
4. **此功能需要设置 `SECRET_KEY` 环境变量**，用于 JWT 的签名和加密。

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
- **存储模式:** 默认使用内存数据库 (`file::memory:?cache=shared`)，上下文在重启时丢失。可通过 `CONTEXT_DB_PATH` 环境变量启用文件存储（在支持持久文件系统的环境中可实现持久化）。
- **多进程/Worker 注意:** 在使用内存数据库（包括共享内存模式）且部署环境使用多个工作进程（如默认的 Uvicorn 或 Gunicorn 配置）时，为确保数据库状态一致性，**建议配置为仅使用单个工作进程** (例如 `uvicorn ... --workers 1`)。否则，不同进程可能无法看到一致的数据库状态。
- **⚠️ 上下文管理关键点:** 上下文与认证凭证 (API Key/代理 Key) 绑定。**切勿对不同的对话/任务使用相同的 Key，否则会导致上下文错乱！** 请为每个独立上下文分配唯一的 Key。**上下文补全的启用/禁用状态也与 Key 绑定，可在文件模式下通过 `/manage/keys` 界面配置。**

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
