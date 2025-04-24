# Web 报告页面开发计划

## 目标

优化周期性报告的展示方式，创建一个需要登录才能访问的、包含图表的美观 Web 报告页面。终端报告的优化为次要目标。

## 计划详情

1.  **创建并优化 Web 报告页面模板 (`app/web/templates/report.html`)**:
    *   创建新的 HTML 文件 `app/web/templates/report.html`。
    *   继承基础模板 `_base.html` 以保持风格统一。
    *   设计页面布局，包含以下部分：
        *   **容量与使用:** 仪表盘/环形图展示 RPD/TPD 输入容量、已用量、预估量，并在图表中心显示百分比。包含关键统计数据列表。
        *   **Key 使用概览:** 卡片/小部件展示各模型 Key 状态分布（饼图），并提供详细状态文本。
        *   **Key 数量建议:** 清晰展示建议文本。
        *   **Top IP 统计:** 表格展示今日/本周/本月 Top 5 请求 IP 和输入 Token IP，表格改为上下堆叠布局，并增加鼠标悬停效果。
    *   **布局优化**: 调整整体布局，将容量指标和 Key 状态放在更突出的位置。为卡片添加阴影效果，增加页面层次感。
    *   引入 Chart.js 图表库 (CDN)。
    *   预留 `<canvas>` 元素用于图表。
    *   添加基础 JavaScript 框架。

2.  **重构报告数据获取逻辑**:
    *   在 `app/core/usage_reporter.py` 中创建新函数 `get_structured_report_data(key_manager)`。
    *   该函数执行类似 `report_usage` 的数据收集和计算。
    *   返回包含所有报告数据的结构化 Python 字典。

3.  **添加后端 API 路由 (`/api/report/data`)**:
    *   在 `app/web/routes.py` 中添加 GET 路由 `/api/report/data`。
    *   使用 `Depends(verify_jwt_token)` 保护，需要登录。
    *   调用 `get_structured_report_data` 获取数据。
    *   通过 `JSONResponse` 返回数据。

4.  **添加 Web 页面路由 (`/report`)**:
    *   在 `app/web/routes.py` 中添加 GET 路由 `/report`。
    *   使用 `Depends(verify_jwt_token)` 保护，需要登录。
    *   仅渲染 `report.html` 页面骨架。

5.  **实现前端 JavaScript 逻辑**:
    *   在 `report.html` 中编写 JS 代码：
        *   页面加载后，`fetch` 调用 `/api/report/data` (携带 `Authorization: Bearer <token>`)。
        *   获取 JSON 数据。
        *   使用 Chart.js 绘制图表。
        *   填充非图表数据。
        *   添加错误处理。

6.  **（次要）优化终端报告**: Web 页面完成后根据需要调整。详细计划如下：
    *   **增强分隔符:** 使用更明显的行分隔符（例如 `---` 或 `===`）来区分报告的不同部分。
    *   **对齐与格式化:**
        *   在 "Key 使用情况聚合" 部分，尝试对齐 `RPD=`, `RPM=`, `TPD_In=`, `TPM_In=`, `Score=` 等指标，使状态信息更易于垂直比较。
        *   保持数字的千位分隔符。
    *   **简化 Key 状态:** 评估是否可以简化状态字符串或调整布局（如 Score 单独一行）。
    *   **调整间距:** 优化各部分之间的空行。

## Mermaid 图表示例 (高级流程)

```mermaid
graph TD
    A[用户访问 /report] -->|需要登录| B(验证 JWT Token);
    B -- 验证通过 --> C{渲染 report.html 骨架};
    C --> D[前端 JS 加载];
    D -->|调用 API /api/report/data| E(验证 JWT Token);
    E -- 验证通过 --> F{调用 get_structured_report_data};
    F --> G[获取并处理报告数据];
    G --> H{返回 JSON 数据};
    D -- 收到 JSON 数据 --> I[使用 Chart.js 渲染图表];
    D -- 收到 JSON 数据 --> J[填充其他页面内容];

    style F fill:#f9f,stroke:#333,stroke-width:2px
    style H fill:#ccf,stroke:#333,stroke-width:2px
    style I fill:#cfc,stroke:#333,stroke-width:2px
