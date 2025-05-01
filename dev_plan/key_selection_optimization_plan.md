# API Key 智能选择与错误处理优化计划

## 当前问题总结 (基于当前代码分析)

1. **[问题仍然存在]** **智能选 Key 逻辑未考虑当前请求的 Token 数:** `APIKeyManager.select_best_key` 依据历史使用评分选择 Key，`request_processing.py` 中的速率限制预检查 (`check_rate_limits_and_update_counts`) 也仅检查历史累计值是否达限，均未结合当前请求的 Token 估算值进行判断。这可能导致选中的 Key 在处理当前请求时才发现超出 TPM 限制。
2. **[问题仍然存在]** **缺乏 Key 筛选原因跟踪:** 程序没有记录 Key 在选择阶段因何种原因（如评分低、RPM/TPM 预检查失败等）被跳过。`usage_reporter.py` 中也没有相关报告。用户无法清晰了解 Key 的筛选过程和效率。
3. **[问题部分解决 - 行为有差异]** **API 调用失败后的处理:** `request_processing.py` 中存在 Key 轮询重试机制。当 API 调用发生异常时，会捕获并调用 `handle_gemini_error`。但 `handle_gemini_error` 对于 500/503/401/403 或明确无效的 400 错误会**直接移除** Key，而不是尝试下一个。对于 429 错误，当前依赖通用异常处理触发重试，可以考虑在 `handle_gemini_error` 中明确处理（例如仅记录日志，不改变 Key 状态）。流式请求在传输过程中的 429 等错误似乎不会触发外层重试。
4. **[问题仍然存在]** **上下文截断未动态调整:** `truncate_context` 函数仅根据模型定义的静态 `input_token_limit` 进行截断，未接收或使用基于 Key 实时可用 Token 容量的动态限制。
5. **[问题已解决]** **Web 页面控制上下文补全:** `APIKeyManager` 支持存储 Key 的 `enable_context_completion` 配置，`request_processing.py` 在处理请求时会读取此配置，`routes.py` 提供了更新此配置的 API 端点，并且 `manage_keys.html` 模板中已包含相应的 UI 元素和交互逻辑。

## 优化计划 (状态更新)

1. **[未实现]** **优化 Key 选择逻辑，综合考虑当前请求 Token 数与密钥轮转:**
    * **Token 预检查 (子计划 1.1):**
        * 修改 `app/core/key_manager_class.py` 中的 `APIKeyManager.select_best_key` 方法（或在 `request_processing.py` 的选择逻辑后添加检查）。
        * 在选择 Key 或使用 Key 之前，获取当前请求的输入 Token 估算值 (`current_request_tokens`)。
        * 对于选中的 Key，获取其在当前时间窗口内的已用输入 Token 数 (`key_usage.get("tpm_input_count", 0)`)。
        * 计算潜在的总输入 Token 数：`potential_tpm_input = key_usage.get("tpm_input_count", 0) + current_request_tokens`。
        * 获取模型的 `tpm_input` 限制 (`tpm_input_limit`)。
        * 如果 `potential_tpm_input > tpm_input_limit`，则认为该 Key 在 Token 方面不可用，记录原因，并跳过该 Key，尝试下一个。
        * 如果 Key 可用，计算该 Key 在本次请求中可用于上下文的剩余 Token 容量：`剩余 TPM_Input 容量 = 模型 tpm_input 限制 - Key 当前已用 Token - 当前请求 Token 估算值`。将此值传递给后续的上下文处理逻辑。
    * **密钥轮转机制 (子计划 1.2 - 新增):**
        * **目标:** 避免部分 Key 因评分略低而长期闲置，促进 Key 的均衡使用。
        * **策略:** 在满足基本可用性（未达速率限制、Token 预检查通过、未标记无效）的前提下，调整选择逻辑以引入轮转因素。
        * **实现思路 (可选其一或结合):**
            * **基于上次使用时间:** 在评分相近（例如，在最高分的 X% 范围内）的可用 Key 中，优先选择“上次使用时间” (`last_used_timestamp`) 最早的 Key。
            * **活跃度加分:** 为长时间未使用的 Key（例如，超过 Y 时间未被使用）临时增加一个“活跃度”分数，使其在选择时更具竞争力。
            * **随机选择:** 在评分最高的 K 个可用 Key 中进行一定概率的随机选择，而非总是选择评分最高的那个。
        * **实施:** 修改 `APIKeyManager.select_best_key` 方法，在评分排序后，根据选定的轮转策略调整最终选择的 Key。需要确保 Key 对象包含 `last_used_timestamp` 属性，并在每次使用后更新。

2. **[未实现]** **添加 Key 筛选原因的跟踪和报告:**
    * 在 `app/core/key_manager_class.py` 的 `APIKeyManager` 类中添加一个数据结构（例如 `self.key_screening_reasons: Dict[str, List[Dict[str, Any]]]`），用于存储每次请求的 Key 筛选记录。Key 可以是请求 ID，值是 Key 的部分信息和筛选原因的列表。
    * 在 Key 选择逻辑 (`select_best_key` 或 `request_processing.py` 的循环中) 以及速率限制预检查 (`check_rate_limits_and_update_counts`) 中，当 Key 因任何原因（Token 超限预判、RPM/TPM 预检查失败、评分过低等）被筛选掉时，向该数据结构添加记录。
    * 修改 `app/core/usage_reporter.py` 中的报告生成函数 (`report_usage` 和 `get_structured_report_data`)。
    * 访问 `APIKeyManager` 实例中的筛选记录数据。
    * 聚合筛选原因，例如统计在报告周期内，有多少 Key 因各种原因被跳过，以及跳过的总次数。
    * 在报告中添加新的部分来展示这些统计信息，让用户清晰地看到 Key 的使用效率和问题所在。
    * 在 Web 页面 (`app/web/`) 上添加逻辑，从结构化报告数据中提取 Key 筛选信息并以用户友好的方式展示。

3. **[部分实现 - 行为有差异]** **优化错误处理和重试机制:**
    * 当前 `app/api/request_processing.py` 中的 `process_request` 函数已包含 Key 轮询重试循环。
    * **需要修改**: `app/core/error_helpers.py` 中的 `handle_gemini_error` 函数。对于 500, 503 等可重试的服务器端错误，不应直接调用 `key_manager.remove_key`，而应考虑仅临时降低 Key 的评分或标记，让重试循环继续尝试其他 Key。对于 429 错误，当前依赖通用异常处理触发重试，可以考虑在 `handle_gemini_error` 中明确处理（例如仅记录日志，不改变 Key 状态）。
    * **需要确认**: 流式请求在传输过程中的 429 等错误是否应该触发外层重试。当前实现似乎是直接向客户端报错并结束。
    * 保留最大重试次数（当前等于活跃 Key 数量）或添加总超时时间，防止无限循环。
    * 如果循环结束仍未成功，抛出最后一次尝试的错误或综合性错误。

4. **[未实现]** **实现动态上下文截断:**
    * 修改 `app/api/request_utils.py` 中的 `truncate_context` 函数，使其能够接收一个可选的 `max_tokens_limit` 参数，表示可用于上下文的最大 Token 数。
    * 在 `app/api/request_processing.py` 的 `process_request` 函数中，在选中 Key 并**成功通过 Token 预检查后**（假设计划 1 已实现），将计算出的“剩余 TPM_Input 容量”作为 `max_tokens_limit` 参数传递给 `truncate_context` 函数。
    * `truncate_context` 函数应根据传入的 `max_tokens_limit`（如果提供）和模型的 `input_token_limit`（取两者中的较小值作为实际截断阈值）来截断合并后的上下文。
    * 确保截断逻辑优先保留对话的最新部分，并且在任何情况下都不会截断当前请求本身的消息（除非当前请求的消息本身就超过了计算出的可用容量）。

5. **[已实现]** **实现 Web 页面开关上下文补全:**
    * `app/core/key_manager_class.py` 中的 `APIKeyManager` 已包含 `key_configs` 和更新方法。
    * `app/web/routes.py` 中已包含 `/api/manage/keys/update/{proxy_key}` API 端点，用于接收前端发送的开关状态更新请求。
    * `app/web/templates/manage_keys.html` 中已包含相应的 UI 元素（复选框）和 JavaScript 交互逻辑。

## Key 选择、动态上下文截断和错误处理流程图 (更新后)

```mermaid
graph TD
    A[接收到新的API请求] --> B{获取当前请求输入Token估算};
    B --> C[生成请求ID];
    C --> D[重置已尝试Key列表];
    D --> E{循环尝试Key (最多N次)};
    E --> F[调用APIKeyManager选择最佳Key<br>(基于历史评分, 考虑轮换机制)]; %% <-- 修改点: 提示考虑轮换
    F --> G{Key是否可用? (未找到或已尝试)};
    G -- 否 --> S[记录Key筛选原因(未找到/已试)];
    S --> Q{所有Key都已尝试或达到最大重试次数?};
    G -- 是 --> G1{预检查: Key是否达到RPM/RPD限制?};
    G1 -- 是 --> S1[记录筛选原因(RPM/RPD超限)];
    S1 --> Q;
    G1 -- 否 --> G2{预检查: Key历史TPM/TPD是否已达限?};
    G2 -- 是 --> S2[记录筛选原因(历史TPM/TPD超限)];
    S2 --> Q;
    G2 -- 否 --> G3{预检查: 考虑当前请求Token后是否超TPM限制? (计划1.1)}; %% <-- 修改点: 明确Token预检查
    G3 -- 是 --> S3[记录筛选原因(Token预检查超限)]; %% <-- 新增原因
    S3 --> Q;
    G3 -- 否 --> H[计算该Key剩余TPM_Input容量<br>(计划1.1)]; %% <-- 修改点: 对应计划1.1
    H --> I{当前Key是否启用上下文补全?};
    I -- 是 --> J[加载历史上下文];
    I -- 否 --> K[跳过加载历史上下文];
    J --> L[合并历史和新消息];
    K --> L;
    L --> M[调用truncate_context<br>(基于模型静态限制或动态限制 - 计划4)]; %% <-- 修改点: 提示动态限制
    M --> N{上下文是否超限?};
    N -- 否 --> O[尝试使用选定Key调用Gemini API];
    N -- 是 --> P[记录上下文超限原因];
    P --> Q;
    O --> T{API调用成功?};
    O --> U{API调用失败?};
    T --> V[更新Token计数和Key上次使用时间]; %% <-- 修改点: 更新上次使用时间
    V --> W[保存上下文 (如果启用)];
    W --> X[返回成功响应];
    U -- 捕获到异常 --> U1[调用 handle_gemini_error];
    U1 --> U2{错误类型?};
    U2 -- 429 (速率限制) --> Y[记录Key失败原因, 可能临时降权]; %% <-- 修改点: 提示可能降权
    U2 -- 500/503/401/403/无效400 --> Z[临时标记/降权 Key (计划3)]; %% <-- 修改点: 避免直接移除
    U2 -- 其他错误 --> R[返回错误: API调用失败];
    Y --> Q;
    Z --> Q;
    Q -- 是 --> R;
    Q -- 否 --> E;

```

## 实施步骤 (更新后)

1. **[未完成]** 修改 `app/core/key_manager_class.py` 或 `app/api/request_processing.py`，实现**考虑当前请求 Token 数的 Key 选择/预检查逻辑** (对应计划 1.1)。
2. **[未完成]** 修改 `app/core/key_manager_class.py` 中的 `APIKeyManager.select_best_key` 方法，**引入密钥轮转机制** (对应计划 1.2)。确保 Key 对象包含并更新 `last_used_timestamp` 属性。
3. **[未完成]** 在 `app/core/key_manager_class.py` 和 `app/api/request_processing.py` 中添加**Key 筛选原因的跟踪功能** (对应计划 2 前半部分)。
4. **[未完成]** 修改 `app/core/error_helpers.py` 中的 `handle_gemini_error` 函数，调整对 500/503 等错误的处理方式，**避免直接移除 Key**，考虑临时降权或标记 (对应计划 3 修改)。确认流式请求中 429 错误的重试逻辑。
5. **[未完成]** 修改 `app/api/request_utils.py` 中的 `truncate_context` 函数，使其支持接收并使用**动态的 `max_tokens_limit` 参数**进行截断 (对应计划 4)。
6. **[未完成]** 修改 `app/core/usage_reporter.py`，将**Key 筛选跟踪数据整合到使用情况报告**中 (对应计划 2 后半部分)。
7. **[已完成]** `app/core/key_manager_class.py` 中已包含获取和设置 Key 上下文补全配置的方法。
8. **[已完成]** `app/web/routes.py` 中已包含处理 Key 上下文补全设置更新请求的 API 端点。
9. **[已完成]** `app/web/templates/manage_keys.html` 中已包含 Web 页面上的开关 UI 和前后端交互逻辑。
10. **[未完成]** 修改 `app/web/` 目录下的相关文件（可能需要新的 API 端点和模板修改），在 Web 页面上**展示 Key 筛选信息** (对应计划 2 Web 展示部分)。
