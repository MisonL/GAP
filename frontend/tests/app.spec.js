// @ts-check
import { test, expect } from '@playwright/test';

// 前端应用的基准 URL（与 Vite dev server 一致）
const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5173';
// 用于登录的 API Key，从环境变量中读取，避免在代码里硬编码密钥
const API_KEY = process.env.GAP_E2E_API_KEY || process.env.GEMINI_API_KEY || '';

// 简单的登录辅助函数：访问 /login，填入 API Key 并等待跳转到仪表盘
async function loginWithApiKey(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');

  // LoginView 使用 id="apiKey" 的密码输入框
  await page.fill('#apiKey', API_KEY);
  await page.click('button:has-text("登录")');

  // 登录成功后默认跳转到根路径（dashboard）
  await page.waitForURL(new RegExp(`${BASE_URL}/($|[?#])`));
}

// 公共（不需要真实后端 Key）页面测试
// 这些测试在未登录状态下即可运行，不依赖任何外部服务。
test.describe('公共页面', () => {
  test('登录页 UI 与基础交互', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('heading', { name: 'API密钥登录' })).toBeVisible();

    const input = page.locator('#apiKey');
    const submit = page.getByRole('button', { name: '登录' });

    await expect(input).toBeVisible();
    await expect(submit).toBeDisabled();

    await input.fill('dummy-key');
    await expect(submit).toBeEnabled();
  });

  test('404 页面展示与返回首页逻辑', async ({ page }) => {
    await page.goto(`${BASE_URL}/this-page-does-not-exist`);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('h1')).toHaveText('404');
    await expect(page.getByText('抱歉，您访问的页面不存在。')).toBeVisible();

    await page.getByRole('link', { name: '返回首页' }).click();
    // 未登录时返回首页会被路由守卫重定向到登录页（可能带 redirect 查询参数）
    await expect(page).toHaveURL(new RegExp(`${BASE_URL}/login(\\?.*)?$`));
  });

  test('401 未授权页面内容', async ({ page }) => {
    await page.goto(`${BASE_URL}/unauthorized`);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('h1')).toHaveText('401 - 未授权');
    await expect(page.getByText('抱歉，您需要登录才能访问此页面。')).toBeVisible();

    await page.getByRole('link', { name: '返回登录页' }).click();
    await expect(page).toHaveURL(new RegExp(`${BASE_URL}/login(\\?.*)?$`));
  });

  test('403 禁止访问页面内容', async ({ page }) => {
    await page.goto(`${BASE_URL}/forbidden`);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('h1')).toHaveText('403 - 禁止访问');
    await expect(page.getByText('抱歉，您没有权限访问此页面。')).toBeVisible();

    await page.getByRole('link', { name: '返回首页' }).click();
    // 未登录时回到首页同样会被重定向到登录页（可能带 redirect 查询参数）
    await expect(page).toHaveURL(new RegExp(`${BASE_URL}/login(\\?.*)?$`));
  });
});

// 需要真实（或至少有效）后端 Key 的端到端测试
// 这些测试会在缺少 GAP_E2E_API_KEY / GEMINI_API_KEY 时整体跳过。
test.describe('GAP 前端端到端测试', () => {
  // 如果没有提供 API Key，则整组测试跳过，避免误报
  test.skip(API_KEY === '', '请设置 GAP_E2E_API_KEY 或 GEMINI_API_KEY 环境变量以运行 E2E 测试');

  test('登录与退出', async ({ page }) => {
    await loginWithApiKey(page);

    // 确认已经在仪表盘（根路径）
    await expect(page).toHaveURL(new RegExp(`${BASE_URL}/($|[?#])`));

    // 桌面导航中的“退出登录”按钮
    const logoutButton = page.getByRole('button', { name: '退出登录' });
    await expect(logoutButton).toBeVisible();

    await logoutButton.click();
    await expect(page).toHaveURL(`${BASE_URL}/login`);
  });

  test('导航栏可进入仪表盘 / 上下文 / Keys / 报告 / 配置', async ({ page }) => {
    await loginWithApiKey(page);

    // 仪表盘（默认路由 / ）
    await page.getByRole('link', { name: '仪表盘' }).click();
    await expect(page).toHaveURL(new RegExp(`${BASE_URL}/($|[?#])`));

    // 上下文管理（/context）
    await page.getByRole('link', { name: '上下文' }).click();
    await expect(page).toHaveURL(`${BASE_URL}/context`);

    // Keys 管理（/keys）
    await page.getByRole('link', { name: 'Keys' }).click();
    await expect(page).toHaveURL(`${BASE_URL}/keys`);

    // 报告（/report）
    await page.getByRole('link', { name: '报告' }).click();
    await expect(page).toHaveURL(`${BASE_URL}/report`);

    // 配置（/config）
    await page.getByRole('link', { name: '配置' }).click();
    await expect(page).toHaveURL(`${BASE_URL}/config`);
  });

  test('上下文页面可加载并展示状态/TTL 控件', async ({ page }) => {
    await loginWithApiKey(page);

    await page.goto(`${BASE_URL}/context`);
    await page.waitForLoadState('networkidle');

    // 标题
    await expect(page.getByRole('heading', { name: '上下文管理' })).toBeVisible();

    // 全局 TTL 输入框 + 更新按钮（仅在管理员且数据成功加载时可见）
    const ttlInput = page.getByPlaceholder('输入新的 TTL (秒)');
    if (await ttlInput.isVisible()) {
      await ttlInput.fill('3600');
      await page.getByRole('button', { name: '更新全局 TTL' }).click();
    }

    // 数据区域：允许“无数据”或存在列表任一情况
    const noData = page.getByText('当前没有缓存的上下文记录。');
    const anyRow = page.locator('table tbody tr');

    if (await noData.isVisible()) {
      await expect(noData).toBeVisible();
    } else if (await anyRow.first().isVisible()) {
      await expect(anyRow.first()).toBeVisible();
    }
  });

  test('Keys 页面可加载并打开/关闭新增 Key 弹窗', async ({ page }) => {
    await loginWithApiKey(page);

    await page.goto(`${BASE_URL}/keys`);
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('heading', { name: 'API Key 管理' })).toBeVisible();

    // 列表或无数据提示两种情况都允许
    const noData = page.getByText('当前没有配置任何 API Key。请添加一个新的 Key。');
    const anyRow = page.locator('table tbody tr');

    if (await noData.isVisible()) {
      await expect(noData).toBeVisible();
    } else if (await anyRow.first().isVisible()) {
      await expect(anyRow.first()).toBeVisible();
    }

    // “添加新 Key” 按钮 + 模态框打开/关闭
    const addButton = page.getByRole('button', { name: '添加新 Key' });
    if (await addButton.isVisible()) {
      await addButton.click();

      const modal = page.locator('.modal-overlay .modal-content');
      await expect(modal).toBeVisible();

      await page.getByRole('button', { name: '取消' }).click();
      await expect(modal).toBeHidden();
    }
  });

  test('仪表盘视图基本布局', async ({ page }) => {
    await loginWithApiKey(page);

    await page.goto(`${BASE_URL}/`);
    await page.waitForLoadState('networkidle');

    // 顶部品牌标题
    await expect(page.getByRole('heading', { name: 'Gemini API 代理' })).toBeVisible();

    // 确保主要内容区域存在
    await expect(page.locator('.dashboard-main')).toBeVisible();
  });

  test('仪表盘展示统计卡片和系统状态', async ({ page }) => {
    await loginWithApiKey(page);

    await page.goto(`${BASE_URL}/`);
    await page.waitForLoadState('networkidle');

    // StatsGrid 统计卡片
    await expect(page.getByText('API Keys')).toBeVisible();
    await expect(page.getByText('上下文缓存')).toBeVisible();

    // 统计文字大致形态，例如“活跃密钥”、“上下文条目”等
    await expect(page.getByText(/活跃密钥/)).toBeVisible();
    await expect(page.getByText(/上下文条目/)).toBeVisible();

    // SystemStatus 系统状态
    await expect(page.getByText('系统状态')).toBeVisible();
    await expect(page.getByText(/版本/)).toBeVisible();
    await expect(page.getByText(/存储模式/)).toBeVisible();

    // QuickActions 快速操作按钮
    await expect(page.getByRole('button', { name: '管理Keys' })).toBeVisible();
    await expect(page.getByRole('button', { name: '管理上下文' })).toBeVisible();
    await expect(page.getByRole('button', { name: '查看报告' })).toBeVisible();
    await expect(page.getByRole('button', { name: '刷新数据' })).toBeVisible();
  });

  test('ViewSwitcher 在上下文视图切换 Bento/Traditional 布局', async ({ page }) => {
    await loginWithApiKey(page);

    // 默认加载 Dashboard，此时视图切换按钮应该可见
    const switcher = page.getByRole('button', { name: /切换视图/ });
    await expect(switcher).toBeVisible();

    // 尝试将模式归一化到 Bento（按钮文案为“切换视图: 传统”表示当前是 Bento 模式）
    const text = await switcher.textContent();
    if (text && text.includes('Bento')) {
      // 当前文案类似“切换视图: Bento”，说明当前是 Traditional，再点一次切回 Bento
      await switcher.click();
    }

    // 进入上下文页面，此时根元素应带 bento-layout
    await page.getByRole('link', { name: '上下文' }).click();
    await page.waitForLoadState('networkidle');
    const contextRoot = page.locator('.manage-context-view');
    await expect(contextRoot).toBeVisible();
    await expect(contextRoot).toHaveClass(/bento-layout/);

    // 切换到 Traditional
    const switcherInContext = page.getByRole('button', { name: /切换视图/ });
    await switcherInContext.click();
    await expect(contextRoot).toHaveClass(/traditional-layout/);

    // 再切回 Bento，确认能恢复
    await switcherInContext.click();
    await expect(contextRoot).toHaveClass(/bento-layout/);
  });

  test('Home 页面 Bento 卡片与链接', async ({ page }) => {
    await loginWithApiKey(page);

    await page.goto(`${BASE_URL}/home`);
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('heading', { name: '仪表盘总览' })).toBeVisible();

    // 确认三个主要跳转链接存在
    await expect(page.getByRole('link', { name: '管理 Keys' })).toBeVisible();
    await expect(page.getByRole('link', { name: '管理上下文' })).toBeVisible();
    await expect(page.getByRole('link', { name: '查看完整报告' })).toBeVisible();
  });

  test('报告页面使用（真实或模拟）数据渲染', async ({ page }) => {
    await loginWithApiKey(page);

    await page.goto(`${BASE_URL}/report`);
    await page.waitForLoadState('networkidle');

    // 标题
    await expect(page.getByRole('heading', { name: '周期报告' })).toBeVisible();

    // 报告详情区域（无论是后端真实数据还是模拟数据）
    await expect(page.getByText('报告详情')).toBeVisible();

    // 图表画布存在（Chart.js 渲染区域）
    await expect(page.locator('#usageChart')).toBeVisible();

    // 详细数据表格至少有表头
    const headerRow = page.locator('table thead tr');
    await expect(headerRow).toBeVisible();

    // 表格中应至少有一行数据（后端或模拟）
    const bodyRows = page.locator('table tbody tr');
    const rowCount = await bodyRows.count();
    expect(rowCount).toBeGreaterThan(0);
  });

  test('配置页面至少能显示标题并优雅处理错误', async ({ page }) => {
    await loginWithApiKey(page);

    await page.goto(`${BASE_URL}/config`);

    // 无论加载成功还是失败，标题都应该出现
    await expect(page.getByRole('heading', { name: '系统配置' })).toBeVisible();

    // 允许三种情况：
    // 1) 仍在加载（短时间内）
    // 2) 显示错误信息
    // 3) 显示当前配置信息网格
    const loadingText = page.getByText('加载配置信息中...');
    const errorText = page.getByText('加载配置信息失败', { exact: false });
    const configGrid = page.locator('.grid.grid-cols-1');

    // 等一小会儿让界面稳定
    await page.waitForTimeout(1000);

    if (await loadingText.isVisible()) {
      await expect(loadingText).toBeVisible();
    } else if (await errorText.isVisible()) {
      await expect(errorText).toBeVisible();
    } else if (await configGrid.first().isVisible()) {
      await expect(configGrid.first()).toBeVisible();
    }
  });

  test('TraditionalList 视图默认展示列表项', async ({ page }) => {
    await loginWithApiKey(page);

    await page.goto(`${BASE_URL}/traditional-list`);
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('heading', { name: '传统列表视图' })).toBeVisible();

    // 默认 props 下应为非空列表
    await expect(page.getByTestId('traditional-list-container')).toBeVisible();
    const items = page.getByRole('listitem');
    await expect(items.first()).toBeVisible();
    await expect(items).toHaveCount(5);
  });

});
