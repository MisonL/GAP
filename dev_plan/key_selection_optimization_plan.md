# API Key 智能选择与错误处理优化计划

## 当前问题总结 (基于当前代码分析)

1. **[问题仍然存在]** **智能选 Key 逻辑未考虑当前请求的 Token 数:** 当前代码 (`APIKeyManager.select_best_key`, `request_processing.py`) 依据历史使用评分和速率限制历史累计值选择 Key，**未**结合当前请求的 Token 估算值进行预检查。这可能导致选中的 Key 在处理当前请求时才发现超出 TPM 限制。
2. **[问题仍然存在]** **缺乏 Key 筛选原因跟踪:** 当前代码**没有**记录 Key 在选择阶段因何种原因（如评分低、RPM/TPM 预检查失败等）被跳过。`usage_reporter.py` 中也**没有**相关报告。
3. **[问题部分解决 - 行为仍需优化]** **API 调用失败后的处理:** `request_processing.py` 中存在 Key 轮询重试机制。`app/core/error_helpers.py` 中的 `handle_gemini_error` 函数在捕获到 500/503/401/403 或明确无效的 400 错误时，**仍然会直接移除 Key** (`key_manager.remove_key`)，这与期望的“避免直接移除，考虑临时降权”**不符**。对于 429 错误，当前依赖通用异常处理触发重试，`handle_gemini_error` 中**没有**明确处理逻辑。流式请求在传输过程中的 429 等错误处理方式**仍需确认**是否会触发外层重试。
4. **[问题仍然存在]** **上下文截断未动态调整:** `app/api/request_utils.py` 中的 `truncate_context` 函数仅根据模型定义的静态 `input_token_limit` 进行截断，**未**接收或使用基于 Key 实时可用 Token 容量的动态限制。
5. **[问题已解决]** **Web 页面控制上下文补全:** 相关功能已在 `APIKeyManager`, `request_processing.py`, `routes.py`, `manage_keys.html` 中实现。

## 优化计划 (状态更新 - 基于当前版本)

1. **[未实现]** **优化 Key 选择逻辑，综合考虑当前请求 Token 数与密钥轮转:**
    * **Token 预检查 (子计划 1.1):**
        * **目标:** 在 Key 被选中用于 API 调用前，预估本次请求的 Token 消耗，判断是否会超出该 Key 的 TPM 限制。
        * **当前状态:** 未实现。
        * **计划:** 修改 `app/core/key_manager_class.py` 中的 `APIKeyManager.select_best_key` 方法（或在 `request_processing.py` 的选择逻辑后添加检查）。
        * 在选择 Key 或使用 Key 之前，获取当前请求的输入 Token 估算值 (`current_request_tokens`)。
        * 对于选中的 Key，获取其在当前时间窗口内的已用输入 Token 数 (`key_usage.get("tpm_input_count", 0)`)。
        * 计算潜在的总输入 Token 数：`potential_tpm_input = key_usage.get("tpm_input_count", 0) + current_request_tokens`。
        * 获取模型的 `tpm_input` 限制 (`tpm_input_limit`)。
        * 如果 `potential_tpm_input > tpm_input_limit`，则认为该 Key 在 Token 方面不可用，记录原因，并跳过该 Key，尝试下一个。
        * 如果 Key 可用，计算该 Key 在本次请求中可用于上下文的剩余 Token 容量：`剩余 TPM_Input 容量 = 模型 tpm_input 限制 - Key 当前已用 Token - 当前请求 Token 估算值`。将此值传递给后续的上下文处理逻辑。
            * **密钥轮转机制 (子计划 1.2):**
                * **目标:** 避免部分 Key 因评分略低而长期闲置，促进 Key 的均衡使用。
                * **当前状态:** 未实现。
                * **计划:** 在满足基本可用性（未达速率限制、Token 预检查通过、未标记无效）的前提下，调整选择逻辑以引入轮转因素。
        * **实现思路 (可选其一或结合):**
            * **基于上次使用时间:** 在评分相近（例如，在最高分的 X% 范围内）的可用 Key 中，优先选择“上次使用时间” (`last_used_timestamp`) 最早的 Key。
            * **活跃度加分:** 为长时间未使用的 Key（例如，超过 Y 时间未被使用）临时增加一个“活跃度”分数，使其在选择时更具竞争力。
            * **随机选择:** 在评分最高的 K 个可用 Key 中进行一定概率的随机选择，而非总是选择评分最高的那个。
        * **实施:** 修改 `APIKeyManager.select_best_key` 方法，在评分排序后，根据选定的轮转策略调整最终选择的 Key。需要确保 Key 对象包含 `last_used_timestamp` 属性，并在每次使用后更新。

2. **[未实现]** **添加 Key 筛选原因的跟踪和报告:**
    * **目标:** 记录 Key 在选择过程中因各种原因被跳过的情况，并在报告中展示，帮助用户了解 Key 的使用效率。
    * **当前状态:** 未实现。
    * **计划:**
        * 在 `APIKeyManager` 类中添加数据结构存储筛选记录。
        * 在 Key 选择和预检查逻辑中添加记录点。
        * 修改 `usage_reporter.py` 以聚合和展示筛选数据。
        * 在 Web 页面上展示筛选信息。

3. **[部分实现 - 行为仍需优化]** **优化错误处理和重试机制:**
    * **目标:** 改进 API 调用失败后的处理逻辑，特别是对于可重试的服务器错误，避免不必要地移除 Key。
    * **当前状态:** `request_processing.py` 有重试循环。`error_helpers.py` 的 `handle_gemini_error` 对于 500/503/401/403/无效400 错误**仍会直接移除 Key**，与期望不符。429 错误无特殊处理。流式请求错误处理待确认。
    * **计划:**
        * **修改 `handle_gemini_error`:** 对于 500, 503 等可重试错误，改为临时降权或标记，而不是直接移除 Key。考虑为 429 错误添加明确处理逻辑（如仅记录日志）。
        * **确认流式请求错误处理:** 检查流式请求失败时是否能正确触发重试循环。
        * **保留重试限制:** 确保有最大重试次数或超时限制。

4. **[未实现]** **实现动态上下文截断:**
    * **目标:** 根据 Key 的实时可用 Token 容量动态调整上下文截断长度，最大化利用 Token。
    * **当前状态:** 未实现。`truncate_context` 仅使用静态模型限制。
    * **计划:**
        * 修改 `truncate_context` 函数，使其接收可选的 `max_tokens_limit` 参数。
        * 在 `process_request` 中，在 Key 通过 Token 预检查后（依赖计划 1.1 实现），计算并传递动态限制给 `truncate_context`。
        * `truncate_context` 使用动态限制和静态限制中的较小值进行截断。

5. **[已实现]** **实现 Web 页面开关上下文补全:**
    * **当前状态:** 功能已完成。相关代码已存在于 `key_manager_class.py`, `routes.py`, `manage_keys.html`。

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

## 实施步骤 (状态更新 - 基于当前版本)

1. **[未完成]** 实现**考虑当前请求 Token 数的 Key 选择/预检查逻辑** (修改 `key_manager_class.py` 或 `request_processing.py`, 对应计划 1.1)。
2. **[未完成]** **引入密钥轮转机制** (修改 `key_manager_class.py`, 对应计划 1.2)。
3. **[未完成]** 添加**Key 筛选原因的跟踪功能** (修改 `key_manager_class.py`, `request_processing.py`, 对应计划 2 前半部分)。
4. **[未完成]** **优化错误处理逻辑** (修改 `error_helpers.py` 避免直接移除 Key，确认流式重试, 对应计划 3)。
5. **[未完成]** 实现**动态上下文截断** (修改 `request_utils.py`, `request_processing.py`, 对应计划 4)。
6. **[未完成]** 将**Key 筛选跟踪数据整合到报告**中 (修改 `usage_reporter.py`, 对应计划 2 后半部分)。
7. **[已完成]** Key 上下文补全配置的后端逻辑 (位于 `key_manager_class.py`)。
8. **[已完成]** Key 上下文补全配置的 API 端点 (位于 `routes.py`)。
9. **[已完成]** Key 上下文补全配置的前端 UI 和交互 (位于 `manage_keys.html`)。
10. **[未完成]** 在 Web 页面上**展示 Key 筛选信息** (修改 `app/web/`, 对应计划 2 Web 展示部分)。
