# 权限隔离与 Key 有效期改造计划

**目标:**

1. **权限隔离:** 普通用户只能查看和管理自己的上下文。
2. **管理员角色:** 引入管理员 Key，拥有管理所有上下文和（在本地模式下）管理代理 Key 的权限。
3. **本地模式 Key 管理:**

* 仅管理员可管理代理 Key（增删改查、启用/禁用）。
* 为代理 Key 增加有效期配置功能（仅管理员可设置）。

**核心问题分析:**

* 当前的 Web UI 和 API 在获取上下文列表 (`/api/manage/context/data`) 和删除上下文 (`/api/manage/context/delete/{proxy_key}`) 时，没有根据当前登录用户的身份进行区分和权限检查。
* 本地模式下的 Key 管理 API (`/api/manage/keys/*`) 同样没有管理员权限校验。
* 数据库 `proxy_keys` 表缺少 Key 有效期字段。
* 配置中缺少专门指定管理员 Key 的方式。

**改造计划:**

1. **引入管理员 Key 配置:**

* 在 `.env` 文件和 `app/config.py` 中增加一个新的环境变量 `ADMIN_API_KEY`，用于指定管理员的 Key。

1. **增强认证与授权:**

* **JWT 签发 (`app/web/routes.py` - `/login`):** 登录时检查 `password` 是否等于 `ADMIN_API_KEY`。如果是，在 JWT 载荷中添加 `{"admin": true}`。
* **JWT 验证 (`app/web/auth.py` - `verify_jwt_token`):** 修改验证函数，解析出 `admin` 标识，并将用户 Key (`sub`) 和管理员状态 (`admin`) 返回或存入 `request.state`。

1. **改造上下文管理:**

* **数据层 (`app/core/context_store.py`):**
  * 修改 `list_all_context_keys_info` 或创建新函数 `list_contexts_for_user`，接收用户 Key 和管理员状态。
  * 管理员返回所有上下文，普通用户仅返回自己的上下文。
* **API 层 (`app/web/routes.py`):**
  * 修改 `/api/manage/context/data`：根据 JWT 获取用户信息，调用改造后的数据层函数。
  * 修改 `/manage/context/delete/{proxy_key}`：增加权限检查（管理员或 Key 拥有者）。
  * 修改 `/manage/context/update_ttl`：增加管理员权限检查。

1. **改造本地模式 Key 管理 (仅文件数据库模式):**

* **数据库 Schema (`app/core/db_utils.py` - `initialize_database`):**
  * 为 `proxy_keys` 表增加 `expires_at` 字段 (DATETIME, NULL)。
* **数据层 (`app/core/db_utils.py`):**
  * 修改 `add/update_proxy_key`，增加可选的 `expires_at` 参数。
  * 修改 `get/is_valid_proxy_key`，增加有效期检查。
  * 修改 `get_all_proxy_keys`，返回 `expires_at`。
* **API 层 (`app/web/routes.py`):**
  * 在所有 `/api/manage/keys/*` 接口增加管理员权限检查（文件模式下）。
  * 修改 `add/update` 接口，允许请求体包含 `expires_at`。
  * 修改 `data` 接口，返回 `expires_at`。

1. **更新前端界面 (`app/web/templates/manage_context.html`, `app/web/templates/manage_keys.html`):**

* **上下文管理:** 后端 API 会自动处理权限，前端可根据管理员状态隐藏/禁用 TTL 更新表单。
* **Key 管理 (本地模式):**
  * 对非管理员隐藏页面或功能。
  * 显示 `expires_at` 字段。
  * 在添加/编辑表单中增加 `expires_at` 输入（仅管理员可见/可用）。

**计划概览 (Mermaid 图):**

```mermaid
graph TD
    A[用户请求 Web UI / API] --> B{认证 (Middleware/JWT)};
    B -- Valid Key/Token --> C{获取用户信息 (Key, IsAdmin?)};
    C --> D{路由处理};

    subgraph Context Management
        D -- /api/manage/context/data --> E[获取上下文列表];
        E -- IsAdmin? --> F1[数据层: 获取所有 Context];
        E -- Not Admin --> F2[数据层: 获取用户 Context (key=user_key)];
        F1 --> G[返回所有上下文];
        F2 --> H[返回用户上下文];
        G --> I[前端显示];
        H --> I;

        D -- /manage/context/delete/{key} --> J[删除上下文];
        J -- IsAdmin? OR UserOwnsKey? --> K[数据层: 删除 Context];
        K --> L[返回结果/重定向];
        J -- No Permission --> M[返回 403 Forbidden];

        D -- /manage/context/update_ttl --> N[更新 TTL];
        N -- IsAdmin? --> O[数据层: 更新 TTL];
        O --> P[返回结果/重定向];
        N -- Not Admin --> Q[返回 403 Forbidden];
    end

    subgraph Key Management (File Mode)
        D -- /api/manage/keys/* --> R{Key 管理操作};
        R -- IsAdmin? AND IsFileMode? --> S[执行 Key 操作 (数据层)];
        S -- Add/Update --> T[处理 expires_at];
        S -- Get/Validate --> U[检查 expires_at];
        T --> V[返回结果];
        U --> V;
        R -- Not Admin OR Not FileMode --> W[返回 403/404];
    end

    subgraph Database Schema
        X[proxy_keys Table] -- Add Column --> Y[expires_at DATETIME NULL];
    end

    subgraph Configuration
        Z[.env / config.py] -- Add Variable --> AA[ADMIN_API_KEY];
    
    end
