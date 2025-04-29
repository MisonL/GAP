# API Key 智能选择与错误处理优化计划

## 当前问题总结

1. **智能选 Key 逻辑未考虑当前请求的 Token 数:** 现有的 Key 选择逻辑主要依赖于 Key 的健康度评分，该评分考虑了每分钟输入 Token (TPM_Input) 的剩余百分比，但未直接将当前请求的 Token 估算值纳入 Key 可用性判断，可能导致 Key 在处理请求过程中因 Token 超限而失败（触发 429 错误）。
2. **缺乏 Key 筛选原因跟踪:** 程序没有记录 Key 在选择阶段因何种原因（如 Token 超限、RPM 超限等）被跳过，导致用户无法清晰地了解 Key 的使用效率和限制触发情况。
3. **API 调用失败后直接返回错误:** 当使用某个 Key 调用 Gemini API 失败（特别是速率限制错误 429）时，程序直接将错误返回给用户，而不是尝试使用列表中的下一个合适 Key，这降低了用户体验。
4. **自动补全上下文未动态调整:** 自动补全上下文功能未根据 Key 的实时可用 Token 容量（考虑当前请求 Token 数和 Key 已用 Token 数后剩余的 TPM_Input 容量）进行动态调整，可能导致不必要的 Token 浪费或超限。
5. **无法在 Web 页面控制上下文补全:** 用户无法通过 Web 界面方便地针对单个 Key 开关自动补全上下文功能。

## 优化计划

1. **优化 Key 选择逻辑，考虑当前请求的 Token 数:**
    * 修改 `app/core/utils.py` 中的 `APIKeyManager.select_best_key` 方法。
    * 在选择 Key 时，获取当前请求的输入 Token 估算值 (`current_request_tokens`)。
    * 对于每个待评估的 Key，获取其在当前时间窗口内的已用输入 Token 数 (`key_usage.get("tpm_input_count", 0)`)。
    * 计算潜在的总输入 Token 数：`potential_tpm_input = key_usage.get("tpm_input_count", 0) + current_request_tokens`。
    * 获取模型的 `tpm_input` 限制 (`tpm_input_limit`)。
    * 如果 `potential_tpm_input > tpm_input_limit`，则认为该 Key 在 Token 方面不可用，记录原因，并跳过该 Key，尝试下一个。
    * 如果 Key 可用，计算该 Key 在本次请求中可用于上下文的剩余 Token 容量：`剩余 TPM_Input 容量 = 模型 tpm_input 限制 - Key 当前已用 Token - 当前请求 Token 估算值`。将此值传递给后续的上下文处理逻辑。

2. **添加 Key 筛选原因的跟踪和报告:**
    * 在 `app/core/utils.py` 的 `APIKeyManager` 类中添加一个数据结构（例如 `self.key_screening_reasons: Dict[str, List[Dict[str, Any]]]`），用于存储每次请求的 Key 筛选记录。Key 可以是请求 ID，值是 Key 的部分信息和筛选原因的列表。
    * 在 Key 选择逻辑中，当 Key 因任何原因（Token 超限、RPM 超限、健康度评分过低等）被筛选掉时，向 `self.key_screening_reasons` 添加记录，包含 Key 的部分信息和具体的筛选原因。
    * 修改 `app/core/usage_reporter.py` 中的报告生成函数 (`report_usage` 和 `get_structured_report_data`)。
    * 访问 `APIKeyManager` 实例中的筛选记录数据。
    * 聚合筛选原因，例如统计在报告周期内，有多少 Key 因各种原因被跳过，以及跳过的总次数。
    * 在报告中添加新的部分来展示这些统计信息，让用户清晰地看到 Key 的使用效率和问题所在。
    * （待定）在 Web 页面 (`app/web/`) 上添加逻辑，从结构化报告数据中提取 Key 筛选信息并以用户友好的方式展示。

3. **优化错误处理和重试机制:**
    * 修改 `app/api/request_processor.py` 中的 `process_request` 函数。
    * 在尝试调用 Gemini API 的 `try...except` 块中，捕获 `httpx.HTTPStatusError` 异常，特别是状态码为 429 (速率限制)、500 (内部错误)、503 (服务不可用) 等可重试的错误。
    * 当捕获到这些特定错误时，记录详细的错误信息和失败的 Key，但不立即抛出异常。
    * 让外部的 Key 轮询循环继续执行，以便尝试从 `APIKeyManager` 获取下一个合适的 Key。
    * 在循环中，使用 `key_manager.select_best_key` 获取下一个 Key。如果 `select_best_key` 返回 None（表示没有可用 Key 或所有 Key 都已尝试），则结束循环。
    * 设置一个最大重试次数或总超时时间，防止在所有 Key 都无效时导致无限循环。
    * 如果循环结束时仍未成功获取响应，则抛出最后一次尝试的错误或一个综合性的错误消息。

4. **实现动态上下文截断:**
    * 修改 `app/api/request_utils.py` 中的 `truncate_context` 函数，使其能够接收一个可选的 `max_tokens_limit` 参数，表示可用于上下文的最大 Token 数。
    * 在 `app/api/request_processor.py` 的 `process_request` 函数中，在选中 Key 并计算出“剩余 TPM_Input 容量”后，将这个值作为 `max_tokens_limit` 参数传递给 `truncate_context` 函数。
    * `truncate_context` 函数应根据传入的 `max_tokens_limit`（如果提供）和模型的 `input_token_limit`（取两者中的较小值作为实际截断阈值）来截断合并后的上下文。
    * 确保截断逻辑优先保留对话的最新部分，并且在任何情况下都不会截断当前请求本身的消息（除非当前请求的消息本身就超过了计算出的可用容量）。

5. **实现 Web 页面开关上下文补全:**
    * 在 `app/core/utils.py` 的 `APIKeyManager` 中添加方法来获取和设置单个 Key 的上下文补全配置。
    * 添加新的 API 端点（例如 `/api/key/{key_id}/context_completion`）或修改现有端点，用于接收前端发送的开关状态更新请求。
    * 在 Web 页面（可能在管理页面 `app/web/templates/manage_keys.html` 或相关路由 `app/web/routes.py` 中）添加一个 UI 元素（如开关或复选框）。
    * 编写前端 JavaScript 代码，在页面加载时获取当前 Key 的上下文补全设置并初始化 UI 状态。
    * 编写前端 JavaScript 代码，监听 UI 元素的变化，并在状态改变时调用后端 API 更新 Key 的配置。

## Key 选择、动态上下文截断和错误处理流程图

```mermaid
graph TD
    A[接收到新的API请求] --> B{获取当前请求输入Token估算};
    B --> C[生成请求ID];
    C --> D[重置已尝试Key列表];
    D --> E{循环尝试Key (最多N次)};
    E --> F[调用APIKeyManager选择最佳Key<br>(传入请求Token和请求ID)];
    F --> G{Key是否可用?};
    G -- 是 --> H[计算该Key剩余TPM_Input容量];
    H --> I{当前Key是否启用上下文补全?};
    I -- 是 --> J[加载历史上下文];
    I -- 否 --> K[跳过加载历史上下文];
    J --> L[合并历史和新消息];
    K --> L;
    L --> M[调用truncate_context<br>(传入剩余TPM_Input容量)];
    M --> N{上下文是否超限?};
    N -- 否 --> O[尝试使用选定Key调用Gemini API];
    N -- 是 --> P[记录上下文超限原因];
    P --> Q{所有Key都已尝试或达到最大重试次数?};
    Q -- 是 --> R[返回错误: 所有Key均不可用];
    Q -- 否 --> E;
    G -- 否 --> S[记录Key筛选原因(Token超限等)];
    S --> Q;
    O --> T{API调用成功?};
    O --> U{API调用失败?};
    T --> V[更新Token计数];
    V --> W[保存上下文];
    W --> X[返回成功响应];
    U -- 捕获到特定错误(如429, 500, 503) --> Y[记录Key失败原因];
    U -- 其他错误 --> R;
    Y --> Q;
```

## 实施步骤

1. 阅读并分析 `app/api/request_utils.py` 和 `app/core/utils.py` 中与 Key 选择和速率限制相关的现有代码。
2. 修改 `app/core/utils.py` 中的 `APIKeyManager` 类，实现考虑当前请求 Token 数的 Key 选择逻辑，并添加 Key 筛选原因的跟踪功能。
3. 修改 `app/api/request_processor.py` 中的 `process_request` 函数，实现 Key 轮询重试机制，并在 API 调用失败时捕获特定错误并尝试下一个 Key。
4. 修改 `app/api/request_utils.py` 中的 `truncate_context` 函数，使其支持根据可用 Token 容量进行动态截断。
5. 修改 `app/core/usage_reporter.py`，将 Key 筛选跟踪数据整合到使用情况报告中。
6. 修改 `app/core/utils.py` 中的 `APIKeyManager` 类，添加获取和设置 Key 上下文补全配置的方法。
7. 在 `app/api/endpoints.py` 或 `app/api/request_processor.py` 中添加或修改 API 端点，处理 Key 上下文补全设置的更新请求。
8. 修改 `app/web/routes.py` 和 `app/web/templates/manage_keys.html`（或其他相关文件），实现 Web 页面上的开关 UI 和前后端交互逻辑。
9. （待定）修改 `app/web/` 目录下的相关文件，在 Web 页面上展示 Key 筛选信息。
