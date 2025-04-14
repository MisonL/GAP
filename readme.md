# 🚀 Gemini API 代理

<!-- 在这里添加徽章 (Badges) -->
<!-- 例如: [![项目状态](https://img.shields.io/badge/status-active-success.svg)](...) -->
<!-- [![许可证](https://img.shields.io/badge/license-TBD-lightgrey.svg)](LICENSE.md) -->

本项目 fork 自 [Mrjwj34](https://github.com/Mrjwj34/Hagemi) 的项目进行二次开发（全程使用 AI 编码，模型主要是 Gemini-2.5-pro-exp-03-25）。

这是一个基于 FastAPI 构建的 Gemini API 代理，旨在提供一个简单、安全且可配置的方式来访问 Google 的 Gemini 模型。适用于在 Hugging Face Spaces 上部署，并支持 OpenAI API 格式的工具集成。

## 目录

- [✨ 主要功能](#-主要功能)
- [🛠️ 使用方式](#️-使用方式)
  - [🚀 部署到 Hugging Face Spaces](#-部署到-hugging-face-spaces)
  - [💻 本地运行](#-本地运行)
  - [🔌 接入其他服务](#-接入其他服务)
- [📝 API 接口说明](#-api-接口说明)
- [⚠️ 注意事项](#️-注意事项)
- [🤝 贡献](#-贡献)
- [📜 版本历史](#-版本历史)

## ✨ 主要功能

<details>
<summary>点击展开/折叠详细功能列表</summary>

### 🔑 API 密钥轮询和管理
*   支持配置多个 Gemini API 密钥，并进行轮询调用。
*   自动检测并移除无效或权限不足的 API 密钥，避免重复尝试 (已修复线程安全问题)。
*   随机化密钥栈，提高负载均衡性能。
*   自动在请求失败时切换到下一个可用密钥。
*   启动时显示所有API密钥状态，方便监控和管理。
*   详细的API密钥使用日志，记录每个密钥的使用情况和错误信息。

### 📊 API 使用情况跟踪与智能选择 (v1.2.0 & v1.2.1 优化)
*   **使用情况跟踪**: 在程序内存中跟踪每个 API Key 对每个已知模型的 RPM (每分钟请求数), RPD (每日请求数), TPD_Input (每日输入 Token 数), TPM_Input (每分钟输入 Token 数) 使用情况。
    *   TPM_Input 计数同时支持流式和非流式响应。
    *   依赖 `app/data/model_limits.json` 文件定义各模型的限制 (已更新以包含输入 Token 限制)。
*   **每日重置**: RPD 和 TPD_Input 计数根据太平洋时间 (PT) 在每日午夜自动重置。
*   **周期性报告与建议**: 定期（默认每 30 分钟，可通过 `USAGE_REPORT_INTERVAL_MINUTES` 环境变量配置）在日志文件中输出各 Key、各模型的使用情况、估算的剩余额度，并根据用量趋势提供 Key 池数量调整建议 (报告内容已更新以包含输入 Token 指标，建议逻辑已调整)。报告的日志级别可通过 `REPORT_LOG_LEVEL` 环境变量配置（默认为 INFO），方便在特定环境（如 Hugging Face Spaces中设为WARNING才能在终端日志中谁出）中查看。
*   **智能 Key 选择**: 基于各 Key 对目标模型的健康度评分（综合 RPD, TPD_Input, RPM, TPM_Input 剩余百分比，权重已调整）进行智能选择，优化 Key 利用率。评分缓存会定期自动更新。
*   **本地速率预检查**: 在请求发送给 Gemini 前，会根据本地跟踪的使用情况和模型限制进行预检查 (RPD, TPD_Input, RPM, TPM_Input)，若判断超限则提前切换 Key，减少对 API 的无效请求。

### 📊 术语解释
*   **RPD (Requests Per Day)**: 指每个 API 密钥每天允许的最大请求次数。这是 Gemini API 对每个密钥设定的日请求总量限制。
*   **RPM (Requests Per Minute)**: 指每个 API 密钥每分钟允许的最大请求次数。这是 Gemini API 对请求频率的限制。
*   **TPD_Input (Input Tokens Per Day)**: 指每个 API 密钥每天允许处理的最大 *输入* Token 总数。
*   **TPM_Input (Input Tokens Per Minute)**: 指每个 API 密钥每分钟允许处理的最大 *输入* Token 总数。

    *本代理程序会跟踪这些指标，用于智能选择可用密钥并进行本地速率预检查。*

###  模型列表接口
*   提供 `/v1/models` 接口，返回可用的 Gemini 模型列表。
*   自动检测并显示当前 API 密钥支持的所有模型。

### 💬 聊天补全接口：
*   提供 `/v1/chat/completions` 接口，支持流式（streaming）和非流式响应，与 OpenAI API 格式兼容。
*   自动将 OpenAI 格式的请求转换为 Gemini 格式。
*   支持多种 Gemini 模型，包括最新的 Gemini 2.5 Pro 系列。
*   自定义安全设置，解除内容限制。可通过 `DISABLE_SAFETY_FILTERING` 环境变量全局禁用安全过滤。

### 🖼️ 图片输入处理 (v1.2.0 优化)
*   支持 OpenAI 格式的多模态消息中的图片输入。
*   **仅接受** Base64 编码的 Data URI 格式 (`data:image/...;base64,...`)。
*   **增强验证**: 使用正则表达式解析 Data URI，并验证 MIME 类型是否为 Gemini 支持的格式 (JPEG, PNG, WebP, HEIC, HEIF)，提高了处理健壮性。

### 📝 日志系统：
*   完善的日志记录系统，包括应用日志、错误日志和访问日志。
*   支持日志轮转功能，防止日志文件过大：
    *   基于大小的轮转：当日志文件达到指定大小时自动创建新文件。
    *   基于时间的轮转：按照指定的时间间隔（如每天午夜）自动创建新文件。
*   自动清理过期日志文件，默认保留30天，减少磁盘空间占用。
*   详细记录API请求、响应和错误信息，便于问题排查。
*   可通过环境变量自定义日志配置：
    *   `MAX_LOG_SIZE`：单个日志文件最大大小（默认10MB）。
    *   `MAX_LOG_BACKUPS`：保留的日志文件备份数量（默认5个）。
    *   `LOG_ROTATION_INTERVAL`：日志轮转间隔（默认每天午夜）。
    *   `DEBUG`：设置为 "true" 启用详细日志记录。

### 🔒 API 密钥保护（可选）：
*   通过 `PASSWORD` 环境变量设置 API 密钥。
*   提供默认 API 密钥 `"123"`。

### 🚦 速率限制和防滥用：
*   通过环境变量自定义限制：
    *   `MAX_REQUESTS_PER_MINUTE`：每分钟最大请求数（默认 30）。
    *   `MAX_REQUESTS_PER_DAY_PER_IP`：每天每个 IP 最大请求数（默认 600）。
*   超过速率限制时返回 429 错误。
*   修复了速率限制逻辑中的缩进错误 (v1.2.0)。

### ⚙️ 安全过滤控制（可选）：
*   通过 `DISABLE_SAFETY_FILTERING` 环境变量控制是否全局禁用 Gemini API 的安全过滤。
*   设置为 `"true"` 将对所有请求禁用安全过滤（使用 `OFF` 阈值）。
*   默认为 `"false"`，不进行全局禁用。
*   **警告：** 禁用安全过滤可能会导致模型生成不当或有害内容，请谨慎使用。

### 🧩 服务兼容
*   提供的接口与 OpenAI API 格式兼容,便于接入各种服务。
*   支持各种基于 OpenAI API 的应用程序和工具。
*   增强的兼容性处理，支持多种客户端（如Chatbox、Roo Code等）：
    *   空消息检查：自动检测并处理空messages数组，返回友好的错误信息。
    *   多模态支持：Message模型支持content字段为字符串或字典列表，兼容图片等多模态输入。
    *   增强的日志记录：详细记录请求体内容，便于调试客户端兼容性问题。
    *   模型名称验证：启动时记录可用模型列表，确保客户端使用正确的模型名称。

</details>

## 🛠️ 使用方式：

### 🚀 部署到 Hugging Face Spaces：

1.  创建一个新的 Space。
2.  将本项目代码上传到 Space。
3.  在 Space 的 `Settings` -> `Secrets` 中设置以下环境变量：
    *   `GEMINI_API_KEYS`：你的 Gemini API 密钥，用逗号分隔（例如：`key1,key2,key3`）。
    *   `PASSWORD`：（可选）设置 API 密钥，留空则使用默认 API 密钥 `"123"`。
    *   `MAX_REQUESTS_PER_MINUTE`：（可选）每分钟最大请求数。
    *   `MAX_REQUESTS_PER_DAY_PER_IP`：（可选）每天每个 IP 最大请求数。
    *   `MAX_LOG_SIZE`：（可选）单个日志文件最大大小（MB）。
    *   `MAX_LOG_BACKUPS`：（可选）保留的日志文件备份数量。
    *   `LOG_ROTATION_INTERVAL`：（可选）日志轮转间隔。
    *   `DEBUG`：（可选）设置为 "true" 启用详细日志记录。
    *   `DISABLE_SAFETY_FILTERING`：（可选）设置为 "true" 将全局禁用 Gemini API 的安全过滤。默认为 "false"。**警告：** 禁用安全过滤可能会导致模型生成不当内容，请谨慎使用。
    *   `USAGE_REPORT_INTERVAL_MINUTES`：（可选）设置周期性使用情况报告的间隔时间（分钟），默认为 30。
    *   `REPORT_LOG_LEVEL`：（可选）设置周期性报告的日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL），默认为 INFO。设置为 WARNING 可以在 Hugging Face Spaces 的 Logs 界面查看报告。
    *   `PROTECT_STATUS_PAGE`：（可选）设置为 "true" 将对根路径 `/` 的状态页面启用密码保护（使用 `PASSWORD` 进行验证）。默认为 "false"。
4.  确保 `requirements.txt` 文件已包含必要的依赖 (`pytz`, `apscheduler` 等)。
5.  确保 `app/data/model_limits.json` 文件存在且配置正确（用于本地速率限制和报告）。
6.  Space 将会自动构建并运行。
7.  URL格式为`https://your-space-url.hf.space`。

### 💻 本地运行：
1.  克隆项目代码到本地。
2.  安装依赖：`pip install -r requirements.txt` (确保包含 `python-multipart` 以支持状态页面登录)
3.  **创建模型限制文件：** 在 `app/data/` 目录下创建 `model_limits.json` 文件，定义模型的 RPM, RPD, TPD_Input, TPM_Input 限制。示例：
    ```json
    {
      "gemini-1.5-flash-latest": {"rpm": 15, "tpm_input": 1000000, "rpd": 1500, "tpd_input": null},
      "gemini-2.5-pro-exp-03-25": {"rpm": 5, "tpm_input": 1000000, "rpd": 25, "tpd_input": 5000000}
      // ... 其他模型
    }
    ```
4.  **配置环境变量：**
    *   **（推荐）** 在项目根目录创建 `.env` 文件，并填入以下内容（根据需要取消注释并修改）：
      ```dotenv
      # 在这里填入你的 Gemini API 密钥。
      # 如果有多个密钥，请用逗号分隔，例如：GEMINI_API_KEYS="key1,key2,key3"
      GEMINI_API_KEYS="YOUR_API_KEY_HERE"

      # （可选）设置 API 密钥。如果留空或注释掉此行，将使用默认 API 密钥 "123"。
      # PASSWORD="your_secure_api_key"

      # （可选）禁用 Gemini API 的安全过滤。设置为 "true" 将对所有请求禁用安全过滤。
      # 警告：禁用安全过滤可能会导致模型生成不当或有害内容。请谨慎使用。
      # 默认值为 "false"。
      # DISABLE_SAFETY_FILTERING=false

      # （可选）设置速率限制。如果留空或注释掉，将使用默认值。
      # MAX_REQUESTS_PER_MINUTE=30
      # MAX_REQUESTS_PER_DAY_PER_IP=600

      # （可选）日志配置
      # MAX_LOG_SIZE=10  # 单个日志文件最大大小（MB）
      # MAX_LOG_BACKUPS=5  # 保留的日志文件备份数量
      # LOG_ROTATION_INTERVAL=midnight  # 日志轮转间隔
      # DEBUG=false  # 是否启用详细日志
      # USAGE_REPORT_INTERVAL_MINUTES=30 # 周期性使用报告间隔（分钟）
      # REPORT_LOG_LEVEL=INFO # 周期性报告的日志级别 (设为 WARNING 可在 HF Logs 显示)
      # PROTECT_STATUS_PAGE=false # 是否对状态页面启用密码保护
      ```
    *   **（或者）** 直接在终端设置环境变量（仅对当前会话有效）：
      ```bash
      export GEMINI_API_KEYS="key1,key2"
      export PASSWORD="your_password"
      export DISABLE_SAFETY_FILTERING="true"
      # ... 其他环境变量
      ```
5.  运行：`uvicorn app.main:app --reload --host 0.0.0.0 --port 7860`


### 🔌 接入其他服务

1.  在连接中选择 OpenAI。
2.  在 API Base URL 中填入 `https://your-space-url.hf.space/v1` 或本地运行地址 `http://localhost:7860/v1`。
3.  在 API Key 中填入 `PASSWORD` 环境变量的值, 如未设置则填入 `123`。

## 📝 API 接口说明

#### 模型列表接口
```
GET /v1/models
```
返回当前可用的所有 Gemini 模型列表。

#### 聊天补全接口
```
POST /v1/chat/completions
```
请求体格式：
```json
{
  "model": "gemini-1.5-pro",  // 或其他支持的模型
  "messages": [
    {"role": "system", "content": "你是一个有用的助手。"},
    {"role": "user", "content": "你好！"}
    // 支持图片输入 (使用 Base64 Data URI)
    // {"role": "user", "content": [
    //   {"type": "text", "text": "描述这张图片"},
    //   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    // ]}
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "stream": false  // 设置为 true 启用流式响应
}
```

## ⚠️ 注意事项：

*   **强烈建议在生产环境中设置 `PASSWORD` 环境变量（作为 API 密钥），并使用强密钥。**
*   根据你的使用情况调整速率限制相关的环境变量。
*   确保你的 Gemini API 密钥具有足够的配额。
*   日志文件存储在项目根目录的 `logs` 文件夹中（如果权限允许，否则在临时目录），定期检查以确保磁盘空间充足。
*   默认情况下，超过30天的日志文件会被自动清理。
*   谨慎使用 `DISABLE_SAFETY_FILTERING` 选项，了解禁用安全过滤的潜在风险。
*   **API 使用情况跟踪功能依赖 `app/data/model_limits.json` 文件，请确保该文件存在且配置正确。**

## 🤝 贡献

欢迎各种形式的贡献！

*   **报告 Bug:** 如果你发现了问题，请在 [Issues](https://github.com/MisonL/Hagemi/issues) 中提交详细的 Bug 报告。
*   **功能请求:** 如果你有新的功能想法，也请在 [Issues](https://github.com/MisonL/Hagemi/issues) 中提出。
*   **代码贡献:** 如果你想贡献代码，请先 Fork 本仓库，在你的分支上进行修改，然后提交 Pull Request。


## 📜 版本历史

<details>
<summary>点击展开/折叠详细版本历史</summary>

### v1.2.2 (本次更新)
*   **修复**: 增加对 Gemini API 请求的读超时时间至 120 秒 (原 `httpx` 默认为 5 秒)，尝试解决处理大型文档或长时生成任务时流式响应可能提前中断的问题 (`app/core/gemini.py`)。

### v1.2.1
*   **优化**: 根据 Gemini API 免费层级限制 (RPD, RPM, TPD_Input, TPM_Input) 优化 Key 选择、评分、跟踪和报告逻辑。
*   **翻译**: 将项目代码中的英文注释和日志信息翻译为中文（简体）。
*   **修复**: 修复了 `gemini.py` 中流式处理 `finish_reason` 的传递问题，以提高 Roo Code 兼容性。
*   **修复**: 修复了 `models.py` 中 `Choice` 模型的类型提示错误。
*   **修复**: 修复了 `endpoints.py` 中多个缺失的导入错误 (`daily_rpd_totals`, `daily_totals_lock`, `ip_daily_counts`, `ip_counts_lock`, `random`, `config`)。
*   **修复**: 修复了 `gemini.py` 中缺失的 `StreamProcessingError` 导入错误。
*   **优化**: 优化了 `Dockerfile`，移除了冗余指令。
*   **现代化**: 将 `main.py` 中的启动/关闭事件处理从弃用的 `@app.on_event` 迁移到推荐的 `lifespan` 上下文管理器。
*   **安全**: 添加 `PROTECT_STATUS_PAGE` 环境变量，允许为根路径 `/` 的状态页面启用密码保护。
*   **美化**: 优化了根路径 `/` 状态页面的 HTML 和 CSS，改善视觉效果。

### v1.2.0
*   **代码重构**:
    *   将 `app/main.py` 按功能拆分为多个模块 (`config`, `key_management`, `reporting`, `error_handlers`, `middleware`, `endpoints`)。
    *   引入新的子目录结构 (`api/`, `core/`, `handlers/`, `data/`) 以更好地组织代码。
    *   更新了所有受影响文件中的导入语句以适应新结构。
*   **Roo Code 兼容性增强**:
    *   修复了 Gemini API 响应缺少助手消息时可能导致 Roo Code 报错的问题（自动补充空助手消息）。
    *   修复了 Gemini 调用 `write_to_file` 工具时缺少 `line_count` 参数可能导致 Roo Code 报错的问题（自动计算并补充）。
    *   增强了 `ResponseWrapper` 以提取工具调用信息。
*   **性能优化**:
    *   将 `app/core/gemini.py` 中的 `complete_chat` 函数改为异步 `httpx` 调用，提高非流式请求效率。
    *   优化了 `app/core/reporting.py` 中 `report_usage` 函数的深拷贝逻辑，减少内存占用。
*   **文档与注释**:
    *   在 `readme.md` 中添加了 RPD, RPM, TPM 的术语解释。
    *   将所有新增和修改的代码文件及计划文件中的注释翻译为简体中文。
    *   术语统一：为减少混淆，文档和代码注释中原先指代服务访问凭证的“密码” (Password) 已统一更名为“API 密钥” (API Key)。相关环境变量名 `PASSWORD` 保持不变，但其作用是设置服务的 API 密钥。
*   **其他**:
    *   API 使用情况跟踪 (RPM, RPD, TPM) 与智能 Key 选择功能。
    *   修复流式请求 TPM 计数不准确的问题。
    *   修复 `APIKeyManager` 中移除无效 Key 时的线程安全问题。
    *   修复 `protect_from_abuse` 函数中的缩进错误。
    *   优化图片处理逻辑。
    *   其他原有修复和改进。

### v1.1.2
*   添加 `DISABLE_SAFETY_FILTERING` 环境变量，允许全局禁用安全过滤。
*   修复流式响应中因安全过滤提前中断导致无助手消息的问题。

### v1.1.1
*   添加日志轮转和清理机制，防止日志文件过大并自动清理过期日志。
*   增强API密钥管理功能，启动时显示所有密钥状态。
*   改进日志系统，提供更详细的API请求和错误信息记录。
*   添加环境变量 `DEBUG` 用于启用详细日志记录。

### v1.1.0
*   增强客户端兼容性：
    *   添加空messages检查，防止422错误。
    *   扩展Message模型支持多模态内容。
    *   增强日志记录，便于调试客户端请求。
    *   启动时记录可用模型列表，确保模型名称兼容性。

### v1.0.0
*   初始版本发布。

</details>

