# 项目重构计划 (Project Refactoring Plan)

本文档概述了对 Gemini API Proxy 项目进行结构优化、代码拆分和注释补充的计划。

## 一、 背景与目标 (Background and Goals)

当前项目结构存在一些零散文件，部分核心模块代码行数较多，集成了过多逻辑。本次重构旨在：

1. **优化目录结构**：将文件按功能分类，使结构更清晰、逻辑性更强。
2. **拆分大文件**：对代码行数超过 500 行的文件进行功能拆分，遵循单一职责原则，提高代码可维护性。
3. **代码优化**：在重构过程中评估并实施可能的代码优化，提升程序效率和可读性。
4. **补充中文注释**：为所有 Python 代码添加或完善中文注释，提高代码可理解性。

## 二、 文件分析概要 (File Analysis Summary)

经过初步分析，以下 Python 文件代码行数较多，是本次重构的重点关注对象：

* `app/api/request_processing.py`: ~600+ 行 (核心请求处理逻辑)
* `app/core/context_store.py`: ~480+ 行 (上下文存储与管理)
* `app/core/key_manager_class.py`: ~400+ 行 (API 密钥管理和选择)
* `app/core/usage_reporter.py`: ~400+ 行 (使用情况报告生成)
* `app/web/routes.py`: ~400+ 行 (混合了页面渲染和 API 端点)
* `app/core/cache_manager.py`: ~300+ 行 (缓存管理)
* `app/core/gemini.py`: ~300+ 行 (Gemini SDK 交互)
* `app/core/db_utils.py`: ~280 行 (数据库工具与 ApiKey CRUD)
* `app/core/key_management.py`: ~250 行 (密钥检查逻辑)
* `app/core/reporting.py`: ~240 行 (后台任务调度)
* `app/handlers/log_config.py`: ~200 行 (日志配置)

其他文件行数相对较少。

## 三、 目录结构优化方案 (Directory Structure Optimization Plan)

**核心思想**：将 `app/core/` 目录按功能领域细分，将 `app/api/` 和 `app/web/` 中的非核心逻辑移至相应的功能模块。

**新目录结构提议 (Proposed New Structure):**

```text
app/
├── __init__.py
├── config.py
├── main.py
├── api/                     # API 端点定义
│   ├── __init__.py
│   ├── endpoints.py         # v1 OpenAI 兼容端点
│   ├── v2_endpoints.py      # v2 Gemini 原生端点
│   ├── models.py            # API 请求/响应模型
│   ├── middleware.py        # API 认证中间件/依赖
│   └── admin/               # 管理相关的 API 端点
│       ├── __init__.py
│       ├── key_endpoints.py
│       ├── context_endpoints.py
│       └── report_endpoints.py
├── core/                    # 核心业务逻辑与功能模块
│   ├── __init__.py
│   ├── database/            # 数据库相关
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── settings.py
│   │   └── utils.py
│   ├── keys/                # API 密钥管理
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   ├── checker.py
│   │   ├── utils.py
│   │   └── db_ops.py        # (可选) ApiKey CRUD
│   ├── cache/               # 缓存管理
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   └── cleanup.py
│   ├── context/             # 上下文管理
│   │   ├── __init__.py
│   │   ├── store.py
│   │   └── converter.py
│   ├── services/            # 外部服务交互
│   │   ├── __init__.py
│   │   └── gemini.py
│   ├── processing/          # 请求处理核心逻辑
│   │   ├── __init__.py
│   │   ├── main_handler.py
│   │   ├── stream_handler.py
│   │   ├── error_handler.py # API 调用错误处理
│   │   └── utils.py         # Token, Rate Limit 等辅助函数
│   ├── reporting/           # 报告与后台任务
│   │   ├── __init__.py
│   │   ├── reporter.py
│   │   ├── scheduler.py
│   │   └── daily_reset.py
│   ├── security/            # 安全相关 (JWT, Auth)
│   │   ├── __init__.py
│   │   ├── jwt.py
│   │   └── auth_dependencies.py
│   ├── utils/               # 通用工具函数
│   │   ├── __init__.py
│   │   ├── request_helpers.py
│   │   └── response_wrapper.py
│   ├── tracking.py          # 全局跟踪变量
│   └── dependencies.py      # FastAPI 依赖注入
├── data/                    # 数据文件 (数据库, 配置等)
│   ├── context_store.db
│   └── model_limits.json
├── handlers/                # 应用级别的处理器 (日志, 全局错误)
│   ├── __init__.py
│   ├── error_handlers.py    # FastAPI 全局错误处理
│   └── log_config.py
├── web/                     # Web UI 页面渲染
│   ├── __init__.py
│   ├── routes.py            # 仅包含页面渲染路由
│   └── templates/           # Jinja2 模板
│       ├── _base.html
│       ├── login.html
│       ├── manage_caches.html
│       ├── manage_context.html
│       ├── manage_keys.html
│       ├── manage.html
│       └── report.html
└── assets/                  # 静态资源
    ├── favicon.ico
    └── images/
        └── web-manage-context.png

tools/                       # (新增) 项目开发辅助工具
└── ApiKey逗号拼接&强密钥生成工具.html
```

**主要变动说明:**

* `app/core/` 按功能细分为多个子目录。
* `app/api/request_processing.py` 被拆分到 `app/core/processing/`。
* `app/web/routes.py` 中的 API 端点移到 `app/api/admin/`。
* `app/web/auth.py` 移到 `app/core/security/auth_dependencies.py`。
* 根目录的 HTML 工具文件移到 `tools/`。

## 四、 大文件拆分方案 (Large File Splitting Plan)

**重点：`app/api/request_processing.py` (约 600+ 行)**

将拆分到 `app/core/processing/` 目录下：

1. **`main_handler.py`**: 包含简化的 `process_request`，负责协调流程。
2. **`api_caller.py`** (或在 `main_handler.py` 内): 包含 `_attempt_api_call`，负责单次 API 调用尝试。
3. **`stream_handler.py`**: 包含 `stream_generator` 和 `_handle_stream_end`，负责流式响应处理。
4. **`error_handler.py`**: 包含 API 调用错误处理函数 (`_format_api_error` 等)。
5. **`utils.py`**: 包含请求处理相关的辅助函数 (Token 估算/截断, 速率限制, 上下文保存等)。

**其他大文件优化建议:**

* **`app/core/context_store.py`**: 分离格式转换逻辑到 `context/converter.py`。
* **`app/core/key_manager_class.py`**: 将 `select_best_key` 按策略拆分为多个私有方法。
* **`app/core/usage_reporter.py`**: 将 `report_usage` 按报告部分拆分为多个辅助函数。
* **`app/web/routes.py`**: 移除 API 端点。
* **`app/core/db_utils.py`**: 考虑分离 ApiKey CRUD 到 `keys/db_ops.py`，统一数据库交互方式。
* **`app/core/cache_manager.py`**: 考虑封装数据库/SDK 交互细节。
* **`app/core/gemini.py`**: 考虑分离格式转换/响应处理逻辑。
* **`app/core/key_management.py`**: 考虑将部分逻辑移入 `keys/manager.py` 或 `keys/checker.py`。

## 五、 中文注释补充计划 (Chinese Comments Plan)

在完成结构调整和代码拆分后，将对项目中的所有 `.py` 文件进行系统性的中文注释补充，确保：

* 模块、类、函数/方法都有清晰的中文文档字符串 (docstring)。
* 复杂或关键的代码逻辑有行内中文注释解释。

## 六、 下一步行动 (Next Steps)

1. **确认方案**: 等待用户确认此计划。
2. **切换模式**: 用户确认后，切换到 **ACT MODE**。
3. **分步实施**:
    * 创建新目录结构。
    * 移动文件到新位置。
    * 修改 `import` 语句以适应新结构。
    * 逐步拆分 `app/api/request_processing.py` 到 `app/core/processing/`。
    * 根据优化建议重构其他文件。
    * 全面补充中文注释。
    * 进行测试验证。
