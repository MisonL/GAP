# GAP 后端认证 / 密钥管理 / 模型校验行为详解

本档案详细说明 GAP 后端当前与 **认证**、**API 密钥管理**、**模型校验** 相关的行为，以及它们和环境变量的对应关系。建议在阅读 `backend/README.md` 快速上手之后，再回来看本文件以理解更完整的运行机制。

## 1. 运行模式与关键环境变量

### 1.1 运行模式

后端目前主要有两类运行模式：

- **内存模式（memory 模式）**

  - 由 `APP_DB_MODE=memory`（或等价配置）控制，内部表现为 `IS_MEMORY_DB=True`；
  - Proxy 密码、API Key、上下文、缓存等均存放在进程内存；
  - 适合本地开发、单机 demo、轻量测试；
  - 数据重启即丢失。

- **数据库模式（非 memory 模式）**
  - `APP_DB_MODE` 为 `postgres`、`sqlite` 等，内部 `IS_MEMORY_DB=False`；
  - Proxy 密码、API Key、上下文、缓存等持久化在数据库；
  - 适合生产环境、多用户长期运行场景。

### 1.2 主要环境变量

与本文件相关的核心环境变量（只列出和认证 / key / 模型相关的部分）：

```bash
# 运行模式
APP_DB_MODE=memory          # memory / postgres / sqlite 等
TESTING=true                # 测试 / 压测场景使用，自动注入内存 key

# 认证相关
USERS_API_KEY=test_key      # 内存模式下平台用户登录密钥
ADMIN_TOKEN=admin_token     # 管理员接口专用 token

# Gemini API 密钥
# 旧字段（单 key），仍被部分代码兼容读取
GEMINI_API_KEY=sk-your-key

# 推荐：多 key 池管理
GEMINI_API_KEYS=sk-your-key-1,sk-your-key-2

# 模型配置
MODEL_LIMITS=...            # 各模型上下文长度、配额等信息，通常由配置文件或环境注入
```

## 2. `/v1/chat/completions` 认证流程

入口：`gap/api/endpoints.py::chat_completions`  
认证依赖：`verify_proxy_key`（`gap/api/middleware.py`）

### 2.1 内存模式下的认证

当 `IS_MEMORY_DB=True`（一般由 `APP_DB_MODE=memory` 决定）时：

1. 启动时读取 `config.USERS_API_KEY`；
2. 将其放入列表 `WEB_UI_PASSWORDS = [USERS_API_KEY, ...]`；
3. 每个进入 `/v1/chat/completions` 的请求都必须携带 HTTP 头：

   ```bash
   Authorization: Bearer <USERS_API_KEY>
   ```

4. `verify_proxy_key` 在内存列表中校验该密钥，匹配则通过认证，否则返回 `401`。

注意：

- 这种模式下**没有单独的用户 / token 表**，完全依赖共享密码；
- 非常适用于单人/小团队测试、内部 demo、开发环境；
- 不适合多租户生产环境（除非有额外的反向代理或网关层做细粒度控制）。

### 2.2 数据库模式下的认证

当 `IS_MEMORY_DB=False`（即 `APP_DB_MODE!=memory`）时：

1. `verify_proxy_key` 不再对比 `USERS_API_KEY`，而是通过：
   - `context_store.is_valid_proxy_key(...)`；
   - 以及 `APIKeyManager` 中的配置；
2. Proxy key 的有效性由数据库中的记录决定，可以与用户 / 组织等实体关联；
3. 典型用法：
   - 通过管理接口创建 / 吊销 proxy key；
   - 通过前端/运维工具向用户发放 key；
   - 后端统一校验并做流控和计费（如有）。

这一条路径本轮改造中保持向后兼容：

- 没有变更数据库模式下的核心认证行为；
- 主要在保证测试 / 内存模式下不会误伤数据库逻辑。

## 3. 管理员 Token 验证

管理员 Token 由单独的 `ADMIN_TOKEN` 环境变量控制，对应依赖为 `verify_admin_token`：

- 仅校验请求头 `X-Admin-Token` 是否与 `ADMIN_TOKEN` 一致；
- 不影响普通 `/v1` / `/v2` API 的认证；
- 适合：
  - 只给少数运维人员一个管理入口，
  - 快速对系统进行健康检查、资源清理、紧急配置查看等操作。

## 4. API Key 管理与默认 key 行为

核心组件：

- `gap/core/keys/manager.py::APIKeyManager`
- `gap/core/dependencies.py::get_key_manager`

### 4.1 正常 Key 加载

在一般（非 TESTING）场景下：

- **内存模式**：

  - `APIKeyManager.reload_keys()` 从 `GEMINI_API_KEYS` 读取多个 key；
  - 为每个 key 创建内存记录，标记为 active，并附带配额信息（RPD/RPM/TPD/TPM）；
  - key 信息通常只在进程生命周期内有效。

- **数据库模式**：
  - Key 信息存储在数据库中，可通过管理界面 / 管理 API 增删改；
  - `APIKeyManager` 从数据库加载 key 列表和配额；
  - 支持更复杂的用量统计、轮换策略等。

### 4.2 TESTING 模式下的兜底行为

当设置 `TESTING=true` 时：

- `get_key_manager` 在第一次被依赖注入访问时，如果发现 `app.state.key_manager` 还没初始化，会：
  1. 创建一个在内存中的 `APIKeyManager` 实例；
  2. 自动注入至少一个默认 key（如 `test_gemini_key_1`）；
  3. 标记为 active，以保证 key 池**不为空**。

这样做的目的：

- 避免在测试 / 压测时因“忘了配置 key”导致所有请求直接 `503`；
- 性能 / 并发测试可以专注于应用逻辑本身，而不被 key 初始化问题干扰；
- 生产环境不会启用该行为（通常不会设置 `TESTING=true`）。

## 5. 模型列表与模型名校验

相关组件：

- `/v1/chat/completions` → `processing` → `validate_model_name`
- `/v2/models/{model}:generateContent`（`gap/api/v2_endpoints.py`）进入核心逻辑前也调用相同校验逻辑

### 5.1 `/v1/models` 的行为

`/v1/models` 的模型列表生成策略按以下优先级：

1. **优先使用 `MODEL_LIMITS`**

   - 若 `MODEL_LIMITS` 已成功加载，直接以其中的模型为准；
   - 适合在配置中显式限定可用模型列表和其配额。

2. **尝试通过 Gemini API 动态拉取**

   - 当 `MODEL_LIMITS` 为空但有可用 key 时；
   - 调用下游列出模型，适合较“开放”的环境。

3. **使用内置兜底列表**
   - 当前两步均失败时；
   - 保证 `/v1/models` 至少不会完全空列表。

### 5.2 模型名校验与 alias

`validate_model_name` 提供统一的模型名处理：

- 所有传入模型名都会经过：

  - 合法性检查（是否在受支持列表中）；
  - 别名转换（如 `gemini-pro` → 具体版本模型名 `gemini-*-pro`）。

- `/v1/chat/completions` 与 `/v2/models/{model}:generateContent` 使用同一实现：

  - 修改 alias 规则时只需改一处；
  - 确保 v1 / v2 行为一致。

- 对无效模型名：
  - 返回 400 或 404；
  - 不会下钻到外部 Gemini API 调用。

## 6. `/cache` 与 `/api/v1/caches` 的职责分离

当前存在两套与“缓存”相关的接口，职责不同：

1. `/cache` 系列（轻量实现）

   - 返回简单的 `list[dict]` 或 `dict` 结构；
   - 主要用于当前集成测试、运行状态观测和轻量验证；
   - 与真实 DB 缓存的 schema 解耦，便于演进。

2. `/api/v1/caches` 系列（完整 DB 缓存接口）
   - 保留完整的数据库 schema 和缓存策略实现；
   - 负责真正的业务级缓存读写；
   - 适用于生产流量的缓存管理。

## 7. 不依赖 pytest 的最小手工验证流程

在当前阶段，如果暂时不追究 pytest 异步运行器 / fixture 导致的挂起问题，可以用以下步骤做 sanity check。

### 7.1 启动后端

```bash
# 在 backend 目录下，准备基本环境变量
export USERS_API_KEY=test_key
export ADMIN_TOKEN=admin_token_value
export GEMINI_API_KEYS=sk-your-key-1,sk-your-key-2  # 如无真实 key，可留空但部分请求会失败

uvicorn src.gap.main:app --reload --host 0.0.0.0 --port 8000
```

### 7.2 健康检查

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/health/basic
curl http://localhost:8000/config/memory-warning
```

预期：

- `/healthz` 返回 `{"status": "ok", ...}`；
- `/health/basic` 带有 `status`、`checks` 字段；
- `/config/memory-warning` 返回包含 `memory_mode` 等信息的字典。

### 7.3 模型列表

```bash
curl -H "Authorization: Bearer test_password" \
  http://localhost:8000/v1/models
```

预期：

- 状态码 200；
- 响应体中有 `data` 数组，包含若干模型 `id`；
- 模型列表来源取决于 `MODEL_LIMITS` / 下游 Gemini / 内置 fallback。

### 7.4 最小 `/v1/chat/completions` 调用

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer test_password" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-pro",
    "messages": [
      {"role": "user", "content": "ping"}
    ]
  }'
```

说明：

- 在无真实 Gemini key 时，该请求可能返回 5xx 或外部 API 错误；
- 但只要不是立刻 401/503，就说明认证和 key 选择逻辑基本工作正常；
- 在测试环境中通过 mock `GeminiClient.complete_chat`，可以验证 200 + 正常 `choices` 结构。

### 7.5 `/cache` 与资源清理端点

```bash
curl -H "Authorization: Bearer test_password" \
  http://localhost:8000/cache

curl -H "Authorization: Bearer test_password" \
  http://localhost:8000/api/v1/resources/cleaners
```

预期：

- `/cache` 返回 `[]` 或 `list[dict]`；
- `/api/v1/resources/cleaners` 返回 `{"grouped_cleaners": ...}` 结构的 `dict`。

---

当后续重新治理 pytest 异步测试基础设施时，可以以本文件为行为基准，对照确认改动前后的路径和环境变量语义保持一致。
