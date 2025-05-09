# 未来增强计划

## 任务概述

本开发文档描述了如何实现以下功能：

1. 将缓存管理 API 添加到主路由或 v1/v2 路由
2. 添加对 inline_data (图像等) 的支持
3. 确认模型名称检查逻辑
4. 更新 Key 与缓存的关联

## 详细步骤

### 1. 将缓存管理 API 添加到主路由或 v1/v2 路由

1. 确定要将缓存管理 API 添加到哪个路由（主路由或 v1/v2 路由）。
2. 修改相应的路由文件（例如 `app/api/endpoints.py` 或 `app/api/v2_endpoints.py`），导入 `app/api/cache_endpoints.py` 中的 `router`，并将其添加到路由中。

### 2. 添加对 inline_data (图像等) 的支持

1. 修改 `app/api/models.py` 中的 `ChatMessage` 模型，添加对 `inline_data` 字段的支持。
2. 修改 `app/core/context_store.py`，使其能够存储和加载包含 `inline_data` 的上下文。
3. 修改 `app/core/gemini.py`，使其能够处理包含 `inline_data` 的请求。
4. 修改 `app/core/cache_manager.py`，使其能够缓存和检索包含 `inline_data` 的内容。

### 3. 确认模型名称检查逻辑

1. 审查 `app/api/request_processing.py` 中使用模型名称的逻辑，确保其正确处理各种模型名称。

### 4. 更新 Key 与缓存的关联

1. 修改 `app/core/db_models.py`，在 `CachedContent` 模型中添加 `key_id` 字段。
2. 修改 `app/core/key_manager_class.py`，实现 `get_key_for_cache(cache_id)` 方法，该方法应返回与指定缓存关联的 Key。
3. 修改 `app/api/request_processing.py`，在选择 Key 时，优先选择与缓存关联的 Key。
