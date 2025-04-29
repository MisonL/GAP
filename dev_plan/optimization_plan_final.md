# Gemini API 代理 * 项目优化计划 (最终版)

## 重要约束

在进行以下优化时，必须遵守以下核心原则：

1. **保留核心认证机制:** 细粒度访问控制 (RBAC) 的实现将在现有的 `ADMIN_API_KEY` (管理员) 和 `PASSWORD`/代理 Key (用户) 认证机制基础上进行扩展，不会引入全新的用户账户体系来替代它们。
2. **保持客户端兼容性:** 所有优化，特别是 API 相关的修改，都必须确保对 Chatbox, Roo Code, Cline 等现有客户端的兼容性，并通过专门的测试用例进行验证。

## 1. 安全性增强 (Security Enhancements)

### 1.1 细粒度访问控制 (RBAC) * 基于现有认证

* **目标:** 在不改变核心认证方式的前提下，实现更细致的权限区分。
* **思路:**
  * `ADMIN_API_KEY` 拥有所有管理权限（管理所有 Key、上下文、系统设置等）。
  * 使用 `PASSWORD` 中的不同 Key 或文件模式下的代理 Key 来区分不同的“用户”上下文和权限范围（例如，普通用户 Key 只能管理自己的上下文，访问自己的使用报告）。
  * Web UI 根据登录时使用的 Key 类型（Admin Key 或 User Key）动态展示不同的功能选项和可访问的数据范围。
* **Mermaid (概念图):**

```mermaid
graph TD
    subgraph "认证主体"
        AdminKey(ADMIN_API_KEY)
        UserKey1(PASSWORD Key 1 / Proxy Key 1)
        UserKey2(PASSWORD Key 2 / Proxy Key 2)
    end
    subgraph "权限范围"
        Perm_ManageAllKeys["管理所有 Key (文件模式)"]
        Perm_ManageAllContexts["管理所有上下文"]
        Perm_ManageSettings["管理系统设置"]
        Perm_ManageOwnKeys["管理自己的 Key (文件模式)"]
        Perm_ManageOwnContexts["管理自己的上下文"]
        Perm_ViewUsageReport["查看使用报告"]
        Perm_ViewGlobalConfig["查看全局配置 (非敏感)"]
    end
    AdminKey ** Grants **> Perm_ManageAllKeys
    AdminKey ** Grants **> Perm_ManageAllContexts
    AdminKey ** Grants **> Perm_ManageSettings
    AdminKey ** Grants **> Perm_ViewGlobalConfig
    UserKey1 ** Grants **> Perm_ManageOwnContexts
    UserKey1 ** Grants **> Perm_ViewUsageReport
    UserKey2 ** Grants **> Perm_ManageOwnContexts
    UserKey2 ** Grants **> Perm_ViewUsageReport
    UserKey1 ** Grants **> Perm_ManageOwnKeys
    UserKey2 ** Grants **> Perm_ManageOwnKeys
```

* **兼容性说明:** 主要影响后端权限判断和 Web UI 界面，不直接修改 API 请求/响应格式，应保持客户端兼容。

### 1.2 输入验证与清理 (Pydantic & Filtering)

* **目标:** 使用 Pydantic 对所有 API 请求体进行严格的数据类型和格式校验。对用户输入的内容进行必要的清理和过滤，防范潜在的安全风险（如注入攻击）。
* **兼容性说明:** 严格的验证可能拒绝之前可以接受的格式错误的请求，需要谨慎实施并测试对现有客户端的影响。清理过程不应改变合法输入的语义。

## 2. 性能与算法优化 (Performance & Algorithm Optimization)

### 2.1 智能 Key 选择算法优化

* **目标:** 在现有评分基础上（RPD, TPD_Input, RPM, TPM_Input 剩余百分比），引入更多因素，如 Key 的历史请求成功率、平均响应延迟、特定错误类型（如配额错误 vs 无效 Key 错误）等，进行更智能的选择。考虑更复杂的负载均衡策略（如加权轮询、基于健康评分的动态选择等）。
* **Mermaid (流程图):**

```mermaid
graph LR
    A[接收请求] **> B{获取可用 Key 列表};
    B **> C{计算每个 Key 的健康 Score};
    subgraph "Score 计算因素"
        direction LR
        Factor1[剩余 RPD/TPD]
        Factor2[剩余 RPM/TPM]
        Factor3[历史成功率]
        Factor4[平均响应延迟]
        Factor5[近期错误类型/频率]
    end
    C **> D[根据 Score 选择最佳 Key];
    D **> E{尝试 API 请求};
    E ** 成功 **> F[记录成功 & 更新统计];
    F **> G[返回响应];
    E ** 失败 **> H{记录失败 & 更新统计/评分};
    H **> I{尝试下一个可用 Key 或返回错误};
    I **> B;
    I **> G;
```

* **兼容性说明:** 此优化主要影响后端 Key 选择逻辑，不改变 API 接口，对客户端透明。

## 3. 功能增强 (Feature Enhancements)

### 3.1 完善 Gemini 原生 API 支持 (`/v2`)

* **目标:** 逐步实现 Gemini API 的其他核心功能，例如：
  * 获取模型信息 (`GET /v2/models/{model}`)
  * 文本嵌入 (`POST /v2/models/{model}:embedContent`)
  * 批量文本嵌入 (`POST /v2/models/{model}:batchEmbedContents`)
  * 计算 Token (`POST /v2/models/{model}:countTokens`)
* **兼容性说明:** 新增 `/v2` 端点不影响现有 `/v1` 接口。

### 3.2 动态模型限制管理 (Web UI)

* **目标:** 提供 Web UI 界面（仅管理员可见），允许动态添加、更新或删除 `model_limits.json` 中的模型及其限制（RPM, RPD, TPM_Input, TPD_Input, input_token_limit），无需手动修改文件和重启服务。更改应实时生效或在短时间内生效。
* **兼容性说明:** 主要为 Web UI 功能，不影响 API 客户端。

### 3.3 增强的用量统计与可视化 (Web UI & API)

* **目标:**
  * 在 Web UI 的 `/report` 页面增加更丰富的图表（使用 Chart.js 或类似库），可视化展示：
    * 每个 Key (或所有 Key 汇总) 的 RPM/RPD/TPM/TPD 使用趋势（按小时/天）。
    * 不同模型的调用次数和 Token 消耗分布（饼图/柱状图）。
    * API 请求成功率和错误类型分布。
    * 允许按时间范围过滤统计数据。
  * 提供 API 端点（例如 `/manage/stats`，需认证）以编程方式获取结构化的用量统计数据。
* **兼容性说明:** Web UI 改进不影响客户端。新增的统计 API 是可选的，不影响现有 API。

### 3.4 Key 配额与有效期管理

* **目标:** （仅文件模式）允许管理员在 `/manage/keys` 界面为代理 Key 设置：
  * 总 Token 配额（输入/输出或总和）。
  * 总请求次数配额。
  * 有效期（日期）。
  * 当 Key 达到配额或过期时，自动禁用该 Key。
  * 在 Key 接近配额或有效期时，在日志中提供警告信息，并在 Web UI 中进行提示。
* **兼容性说明:** 主要影响文件模式下的 Key 管理和认证逻辑，需要确保不影响使用有效 Key 的客户端请求。

### 3.5 Web UI 显示全局配置

* **目标:** 在 Web UI 中添加一个页面或区域（例如 `/manage/config`，仅管理员可见），显示当前服务加载的全局配置参数。
* **要求:** **必须隐藏** `GEMINI_API_KEYS`, `PASSWORD`, `ADMIN_API_KEY`, `SECRET_KEY` 等敏感信息，只显示如速率限制、日志设置、数据库路径（如果设置）、报告间隔等非敏感配置。
* **兼容性说明:** Web UI 功能，不影响 API 客户端。

## 4. 开发者体验与易用性 (Developer Experience & Usability)

### 4.1 交互式 API 文档 (Swagger/ReDoc)

* **目标:** 利用 FastAPI 的内置功能，自动生成 `/docs` (Swagger UI) 和 `/redoc` (ReDoc) 页面，提供详细的、可交互的 API 文档。确保 Pydantic 模型和路由函数有清晰的描述。
* **兼容性说明:** 提供文档，不影响 API 功能。

### 4.2 测试覆盖 (含兼容性测试)

* **目标:** 使用 `pytest` 框架编写单元测试和集成测试，覆盖核心逻辑（Key 管理、上下文处理、API 转换、速率限制、RBAC 等）。
* **要求:** **必须包含针对 Chatbox, Roo Code, Cline 等已知客户端请求格式和行为的兼容性测试用例**，确保优化不破坏现有集成。
* **兼容性说明:** 测试本身不影响功能，但有助于保证兼容性。

### 4.3 配置向导 (独立 HTML 文件)

* **目标:** 创建一个独立的、纯前端的 HTML 文件（例如 `config_helper.html`），包含表单和 JavaScript 逻辑。用户可以在浏览器中打开此文件，填写必要的配置项（如 API Keys, 密码等），然后该页面可以：
  * 生成可以直接复制粘贴到 `.env` 文件的内容。
  * 生成可以在终端执行的 `export` 命令。
  * 对输入的配置进行基本的格式检查（例如，检查 Key 是否为空）。
* **兼容性说明:** 辅助工具，不影响核心服务。

### 4.4 优化 API 错误信息

* **目标:** 统一 API 返回的错误信息格式。提供更清晰、标准化的错误代码（可以是自定义代码或沿用 HTTP 状态码）和更具描述性的错误消息，帮助用户和客户端开发者快速定位问题。
* **兼容性说明:** 改进错误响应格式时需谨慎，确保客户端能够正确解析。优先在错误消息文本中提供更多信息，而不是大幅改变现有错误响应的 JSON 结构。

### 4.5 Web UI 优化

* **目标:** 持续改进 Web UI 的布局、导航、表单交互和视觉设计，使其更加直观易用。考虑使用更现代的前端框架或组件库（如果时间和资源允许）。
* **兼容性说明:** 不影响 API 客户端。

### 4.6 详细部署指南 (多平台)

* **目标:** 在 `readme.md` 或单独的文档文件中，提供针对不同部署环境的更详细、逐步的部署指南和最佳实践：
  * 本地 Python 虚拟环境 (区分 Windows, macOS, Linux 的细微差别)。
  * Docker (提供 Dockerfile 和 docker*compose.yml 示例)。
  * Hugging Face Spaces (更新现有指南，包含新配置和注意事项)。
  * （可选）其他云平台或 Kubernetes。
* **兼容性说明:** 文档改进，不影响服务本身。
