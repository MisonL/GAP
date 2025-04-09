# 🚀 Gemini API Proxy

本项目基于某论坛上一位大佬[@Moonfanzp](https://github.com/Moonfanz)的代码修改而来,~~但鉴于本人能力水平有限,所以项目可能出现一些bug,请谨慎使用~~bug修的差不多了!下面是介绍:
这是一个基于 FastAPI 构建的 Gemini API 代理，旨在提供一个简单、安全且可配置的方式来访问 Google 的 Gemini 模型。适用于在 Hugging Face Spaces 上部署，并支持openai api格式的工具集成。

## ✨ 主要功能：

### 🔑 API 密钥轮询和管理
*   支持配置多个 Gemini API 密钥，并进行轮询调用。
*   自动检测并移除无效或权限不足的 API 密钥，避免重复尝试。
*   随机化密钥栈，提高负载均衡性能。
*   自动在请求失败时切换到下一个可用密钥。
*   启动时显示所有API密钥状态，方便监控和管理。
*   详细的API密钥使用日志，记录每个密钥的使用情况和错误信息。

### 📑 模型列表接口
*   提供 `/v1/models` 接口，返回可用的 Gemini 模型列表。
*   自动检测并显示当前 API 密钥支持的所有模型。

### 💬 聊天补全接口：

*   提供 `/v1/chat/completions` 接口，支持流式（streaming）和非流式响应，与 OpenAI API 格式兼容。
*   自动将 OpenAI 格式的请求转换为 Gemini 格式。
*   支持多种 Gemini 模型，包括最新的 Gemini 2.5 Pro 系列。
*   自定义安全设置，解除内容限制。可通过 `DISABLE_SAFETY_FILTERING` 环境变量全局禁用安全过滤。

### 📊 日志系统：

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

### 🔒 密码保护（可选）：

*   通过 `PASSWORD` 环境变量设置密码。
*   提供默认密码 `"123"`。

### 🚦 速率限制和防滥用：

*   通过环境变量自定义限制：
    *   `MAX_REQUESTS_PER_MINUTE`：每分钟最大请求数（默认 30）。
    *   `MAX_REQUESTS_PER_DAY_PER_IP`：每天每个 IP 最大请求数（默认 600）。
*   超过速率限制时返回 429 错误。

### ⚙️ 安全过滤控制（可选）：

*   通过 `DISABLE_SAFETY_FILTERING` 环境变量控制是否全局禁用 Gemini API 的安全过滤。
*   设置为 `"true"` 将对所有请求禁用安全过滤（使用 `OFF` 阈值）。
*   默认为 `"false"`，仅对特定模型（如 `gemini-2.0-flash-exp`）禁用过滤。
*   **警告：** 禁用安全过滤可能会导致模型生成不当或有害内容，请谨慎使用。

### 🧩 服务兼容

*   提供的接口与 OpenAI API 格式兼容,便于接入各种服务。
*   支持各种基于 OpenAI API 的应用程序和工具。
*   增强的兼容性处理，支持多种客户端（如Chatbox、Roo Code等）：
    *   空消息检查：自动检测并处理空messages数组，返回友好的错误信息。
    *   多模态支持：Message模型支持content字段为字符串或字典列表，兼容图片等多模态输入。
    *   增强的日志记录：详细记录请求体内容，便于调试客户端兼容性问题。
    *   模型名称验证：启动时记录可用模型列表，确保客户端使用正确的模型名称。

## 🛠️ 使用方式：

### 🚀 部署到 Hugging Face Spaces：

1.  创建一个新的 Space。
2.  将本项目代码上传到 Space。
3.  在 Space 的 `Settings` -> `Secrets` 中设置以下环境变量：
    *   `GEMINI_API_KEYS`：你的 Gemini API 密钥，用逗号分隔（例如：`key1,key2,key3`）。
    *   `PASSWORD`：（可选）设置访问密码，留空则使用默认密码 `"123"`。
    *   `MAX_REQUESTS_PER_MINUTE`：（可选）每分钟最大请求数。
    *   `MAX_REQUESTS_PER_DAY_PER_IP`：（可选）每天每个 IP 最大请求数。
    *   `MAX_LOG_SIZE`：（可选）单个日志文件最大大小（MB）。
    *   `MAX_LOG_BACKUPS`：（可选）保留的日志文件备份数量。
    *   `LOG_ROTATION_INTERVAL`：（可选）日志轮转间隔。
    *   `DEBUG`：（可选）设置为 "true" 启用详细日志记录。
    *   `DISABLE_SAFETY_FILTERING`：（可选）设置为 "true" 将全局禁用 Gemini API 的安全过滤。默认为 "false"。**警告：** 禁用安全过滤可能会导致模型生成不当内容，请谨慎使用。
4.  确保 `requirements.txt` 文件已包含必要的依赖。
5.  Space 将会自动构建并运行。
6.  URL格式为`https://your-space-url.hf.space`。

### 💻 本地运行：
1.  克隆项目代码到本地。
2.  安装依赖：`pip install -r requirements.txt`
3.  **配置环境变量：**
    *   **（推荐）** 在项目根目录创建 `.env` 文件，并填入以下内容（根据需要取消注释并修改）：
      ```dotenv
      # 在这里填入你的 Gemini API 密钥。
      # 如果有多个密钥，请用逗号分隔，例如：GEMINI_API_KEYS="key1,key2,key3"
      GEMINI_API_KEYS="YOUR_API_KEY_HERE"

      # （可选）设置访问密码。如果留空或注释掉此行，将使用默认密码 "123"。
      # PASSWORD="your_secure_password"

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
      ```
    *   **（或者）** 直接在终端设置环境变量（仅对当前会话有效）：
      ```bash
      export GEMINI_API_KEYS="key1,key2"
      export PASSWORD="your_password"
      export DISABLE_SAFETY_FILTERING="true"
      # ... 其他环境变量
      ```
4.  运行：`uvicorn app.main:app --reload --host 0.0.0.0 --port 7860`


### 🔌 接入其他服务

1.  在连接中选择OpenAI
2.  在API Base URL中填入`https://your-space-url.hf.space/v1`
3.  在API Key中填入`PASSWORD`环境变量的值,如未设置则填入`123`

### 📝 API 接口说明

#### 模型列表接口
```
GET /v1/models
```
返回当前可用的所有Gemini模型列表。

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
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "stream": false  // 设置为true启用流式响应
}
```

## ⚠️ 注意事项：

*   **强烈建议在生产环境中设置 `PASSWORD` 环境变量，并使用强密码。**
*   根据你的使用情况调整速率限制相关的环境变量。
*   确保你的 Gemini API 密钥具有足够的配额。
*   日志文件存储在项目根目录的 `logs` 文件夹中，定期检查以确保磁盘空间充足。
*   默认情况下，超过30天的日志文件会被自动清理。
*   谨慎使用 `DISABLE_SAFETY_FILTERING` 选项，了解禁用安全过滤的潜在风险。

## 📋 版本历史

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
