# 开发计划：代理 Key 管理模式区分 (v2)

## 1. 项目目标

在代理 Key 管理页面中，明确区分并支持两种 Key 存储和管理模式，由新的配置项 `KEY_STORAGE_MODE` 控制：

* **数据库模式 (`KEY_STORAGE_MODE='database'`)**: API Key 及其相关信息通过 SQLite 数据库进行持久化存储和管理。所有更改都会被保存。

* **内存模式 (`KEY_STORAGE_MODE='memory'`)**: API Key 列表在应用启动时从环境变量 (`GEMINI_API_KEYS`) 加载到内存。用户可以在运行时通过管理页面临时调整内存中的 Key 信息，但这些更改不会被永久保存，应用重启后会丢失并重新从环境变量加载。

## 2. 核心配置 (`app/config.py`) - 已完成

* 已添加新配置项 `KEY_STORAGE_MODE: str = os.environ.get("KEY_STORAGE_MODE", "memory").lower()`。
  * 默认值已更新为 `'memory'`。
  * 确保该值只能是 `'database'` 或 `'memory'` 之一，否则记录错误并回退到默认值。

* 已添加 `GEMINI_API_KEYS: Optional[str] = os.environ.get("GEMINI_API_KEYS")` 用于内存模式加载。

## 3. 数据库模式 (`KEY_STORAGE_MODE='database'`) 详细逻辑

* **数据模型 (`app/core/db_models.py`) - 已完成**:
  * 已定义 `ApiKey` SQLAlchemy 模型。实际字段根据 `app/core/db_models.py` 实现（例如：`id`, `key_string`, `description`, `created_at`, `last_used_at`, `is_active`, `is_system`, `enable_context_management`, `context_window`, `max_tokens_per_day`, `current_tokens_used_today`, `rate_limit_per_minute`, `proxy_key_type`, `user_id` 等）。
  * 数据库初始化逻辑已能创建 `ApiKey` 表。

* **数据库操作 (`app/core/db_utils.py`) - 已完成**:
  * 已实现 `ApiKey` 模型的新增、读取、更新、删除 (CRUD) 函数。

* **Key 管理器 (`app/core/key_manager_class.py`) - 已完成**:
  * 初始化时，从数据库加载 Key 及其配置。
  * 所有 Key 操作均通过 `db_utils` 更新数据库，并通过调用 `self.reload_keys()` 同步更新内存状态。

* **Web API (`app/web/routes.py`) - 已完成**:
  * Key 管理相关 API 在数据库模式下调用相应的数据库操作函数，并在修改后调用 `key_manager.reload_keys()` 来确保 `APIKeyManager` 的内存状态与数据库同步。

* **前端模板 (`app/web/templates/manage_keys.html`) - 已完成**:
  * 标题显示“管理代理 Key (数据库存储模式)”。
  * 所有操作持久化，无需特殊提示。

## 4. 内存模式 (`KEY_STORAGE_MODE='memory'`) 详细逻辑

* **Key 管理器 (`app/core/key_manager_class.py`) - 已完成**:
  * 初始化时，从环境变量 `GEMINI_API_KEYS` (逗号分隔) 加载 Key 字符串列表。
  * 为每个 Key 初始化默认配置。
  * Key 的添加、编辑、删除操作通过 `add_key_memory`, `update_key_memory`, `delete_key_memory` 等方法仅修改内存中的 `self.api_keys` 和 `self.key_configs`。

* **Web API (`app/web/routes.py`) - 已完成**:
  * Key 管理相关 API 直接操作 `APIKeyManager` 内存中的数据。

* **前端模板 (`app/web/templates/manage_keys.html`) - 已完成**:
  * 标题显示“管理代理 Key (内存存储模式)”。
  * 在页面显著位置添加全局警告：“**警告：当前为内存存储模式。所有对代理 Key 的添加、编辑或删除操作均为临时性调整，不会被永久保存，应用重启后将丢失并从环境变量重新加载初始 Key 列表。**”
  * 在添加、编辑、删除操作的相应位置也添加简短的临时性提示。

## 5. 通用调整

* **Web 路由 (`app/web/routes.py`) - 已完成**:
  * `/manage/keys` 页面路由已传递 `config.KEY_STORAGE_MODE` 给模板。
  * 已移除 `/api/manage/keys/data` 对 `require_file_db_mode` 的依赖。

* **前端模板 (`app/web/templates/manage_keys.html`) - 已完成**:
  * JavaScript 逻辑已根据 `KEY_STORAGE_MODE` 调整行为和显示。

* **认证与授权 - 已完成**:
  * 已保持对 Key 管理 API 的管理员权限控制。

## 6. 开发步骤与时间估算 (已完成)

1. **配置与模型 (已完成)**

2. **数据库工具函数 (已完成)**

3. **Key 管理器核心逻辑 (已完成)**

4. **后端 API 调整 (已完成)**

5. **前端模板与 JS 调整 (已完成)**

6. **测试与调试 (已完成)**

7. 文档更新 (已完成)**:

* 已更新 `readme.md`，说明了新的 `KEY_STORAGE_MODE` 和 `GEMINI_API_KEYS` 环境变量。
* 已解释两种模式的行为差异和配置方法。

**所有计划任务已完成。**
