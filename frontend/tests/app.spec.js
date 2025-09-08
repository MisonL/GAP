// @ts-check
import { test, expect } from '@playwright/test';

// 定义前端应用的基准 URL
const BASE_URL = 'http://localhost:5173'; // 请根据实际运行的开发服务器地址修改

test.describe('前端应用端到端测试', () => {

  // 在所有测试之前执行一次登录，并保存认证状态
  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`${BASE_URL}/login`);

    // 填写用户名和密码
    // 假设输入框有 placeholder 或 name 属性
    await page.fill('input[placeholder="用户名"]', 'testuser'); // 根据实际的输入框选择器修改
    await page.fill('input[placeholder="密码"]', 'testpassword'); // 根据实际的输入框选择器修改

    // 点击登录按钮
    // 假设登录按钮有 data-test-id 或 class
    await page.click('button:has-text("登录")'); // 根据实际的登录按钮选择器修改

    // 等待页面跳转到 Dashboard
    await page.waitForURL(`${BASE_URL}/dashboard`);

    // 保存认证状态
    await context.storageState({ path: 'playwright/.auth/user.json' });
    await context.close();
  });

  // 在每个测试之前使用已保存的认证状态创建新的上下文
  test.use({ storageState: 'playwright/.auth/user.json' });

  // 在每个测试之前导航到应用的根目录
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
  });

  test('应能成功登录和登出', async ({ page }) => {
    // 已经通过 beforeAll 登录，直接验证是否在 Dashboard 页面
    await expect(page).toHaveURL(`${BASE_URL}/dashboard`);

    // 验证页面上是否存在登出按钮或其他登录成功标识
    await expect(page.locator('button:has-text("登出")')).toBeVisible(); // 根据实际的登出按钮选择器和文本修改

    // 点击登出按钮
    await page.click('button:has-text("登出")'); // 根据实际的登出按钮选择器和文本修改

    // 验证是否跳转回登录页面或其他登出后的页面
    await expect(page).toHaveURL(`${BASE_URL}/login`); // 根据实际的登出后页面 URL 修改
  });

  test('应能通过导航栏导航到主要页面', async ({ page }) => {
    // 假设导航栏链接有 data-test-id 或 class
    // 导航到 Manage Context
    await page.click('nav a:has-text("Manage Context")'); // 根据实际的导航链接选择器和文本修改
    await expect(page).toHaveURL(`${BASE_URL}/manage-context`); // 根据实际的 Manage Context 页面 URL 修改
    await page.waitForLoadState('networkidle'); // 等待页面加载完成

    // 导航到 Manage Keys
    await page.click('nav a:has-text("Manage Keys")'); // 根据实际的导航链接选择器和文本修改
    await expect(page).toHaveURL(`${BASE_URL}/manage-keys`); // 根据实际的 Manage Keys 页面 URL 修改
    await page.waitForLoadState('networkidle'); // 等待页面加载完成

    // 导航到 Report
    await page.click('nav a:has-text("Report")'); // 根据实际的导航链接选择器和文本修改
    await expect(page).toHaveURL(`${BASE_URL}/report`); // 根据实际的 Report 页面 URL 修改
    await page.waitForLoadState('networkidle'); // 等待页面加载完成

    // 导航回 Dashboard
    await page.click('nav a:has-text("Dashboard")'); // 根据实际的导航链接选择器和文本修改
    await expect(page).toHaveURL(`${BASE_URL}/dashboard`); // 根据实际的 Dashboard 页面 URL 修改
    await page.waitForLoadState('networkidle'); // 等待页面加载完成
  });

  test('应能管理上下文', async ({ page }) => {
    // 导航到 Manage Context 页面
    await page.goto(`${BASE_URL}/manage-context`); // 根据实际的 Manage Context 页面 URL 修改
    await page.waitForLoadState('networkidle'); // 等待数据加载

    // 验证数据加载 (检查表格或其他列表是否存在数据)
    // 假设上下文列表在表格中，且至少有一行数据
    await expect(page.locator('table tbody tr')).toBeVisible(); // 根据实际的上下文列表选择器修改

    // 删除单条记录 (需要根据实际页面元素和交互进行调整)
    // 找到第一条记录的删除按钮并点击
    // 注意：这里假设删除按钮在每行中，且文本为“删除”或有 data-test-id="delete-context-button"
    // await page.locator('table tbody tr:first-child button:has-text("删除")').click(); // 根据实际的删除按钮选择器和文本修改
    // 或者使用 data-test-id
    // await page.locator('table tbody tr:first-child [data-test-id="delete-context-button"]').click();
    // 确认删除操作 (如果需要)
    // 注意：这里假设有一个确认删除的模态框或弹窗，并点击确认按钮
    // await page.click('button:has-text("确认删除")'); // 根据实际的确认按钮选择器和文本修改
    // 验证记录是否被删除 (检查列表中的记录数量或特定记录是否存在)
    // 这部分需要根据实际应用的行为来编写断言，例如等待列表更新或检查特定元素消失
    // await expect(page.locator('table tbody tr')).toHaveCount(originalCount - 1); // 根据实际情况修改

    // 更新全局 TTL (需要根据实际页面元素和交互进行调整)
    // 找到 TTL 输入框并填写新值
    // 注意：这里假设 TTL 输入框有一个 aria-label="全局 TTL" 或 data-test-id="global-ttl-input"
    await page.fill('input[aria-label="全局 TTL"]', '3600'); // 根据实际的 TTL 输入框选择器修改
    // 或者使用 data-test-id
    // await page.fill('[data-test-id="global-ttl-input"]', '3600');
    // 点击保存按钮
    // 注意：这里假设有一个保存 TTL 的按钮，文本为“保存 TTL”或 data-test-id="save-ttl-button"
    await page.click('button:has-text("保存 TTL")'); // 根据实际的保存按钮选择器和文本修改
    // 或者使用 data-test-id
    // await page.click('[data-test-id="save-ttl-button"]');
    // 验证 TTL 是否更新成功 (可能需要重新加载页面或检查页面上的显示值)
    // 这部分需要根据实际应用的行为来编写断言
    test.describe('前端响应式测试', () => {
      // 定义不同视口尺寸
      const viewports = [
        { name: '桌面', width: 1280, height: 720 },
        { name: '平板', width: 768, height: 1024 },
        { name: '手机', width: 375, height: 667 },
      ];
  
      // 在每个测试之前使用已保存的认证状态创建新的上下文
      test.use({ storageState: 'playwright/.auth/user.json' });
  
      // 遍历不同视口进行测试
      for (const viewport of viewports) {
        test(`在 ${viewport.name} 视口下验证响应式布局`, async ({ page }) => {
          await page.setViewportSize({ width: viewport.width, height: viewport.height });
          await page.goto(`${BASE_URL}/dashboard`); // 导航到 Dashboard 页面
          await page.waitForLoadState('networkidle'); // 等待页面加载
  
          console.log(`正在测试 ${viewport.name} 视口 (${viewport.width}x${viewport.height})`); // 打印当前测试的视口信息
  
          // 验证导航栏的可见性和布局
          const navigation = page.locator('nav'); // 假设导航栏是 <nav> 标签
          await expect(navigation).toBeVisible(); // 导航栏应该始终可见
  
          if (viewport.name === '手机') {
            // 手机视口下，验证导航栏是否变为汉堡菜单（如果存在）
            // 假设汉堡菜单按钮有一个 data-testid="hamburger-menu-button"
            const hamburgerMenuButton = page.locator('[data-testid="hamburger-menu-button"]');
            if (await hamburgerMenuButton.isVisible()) {
              await expect(hamburgerMenuButton).toBeVisible(); // 汉堡菜单按钮可见
              await expect(navigation.locator('a:has-text("Dashboard")')).toBeHidden(); // 导航链接可能隐藏
              await hamburgerMenuButton.click(); // 点击汉堡菜单打开导航
              await expect(navigation.locator('a:has-text("Dashboard")')).toBeVisible(); // 导航链接可见
              await page.click('body', { position: { x: 10, y: 10 } }); // 点击页面其他地方关闭菜单
              await expect(navigation.locator('a:has-text("Dashboard")')).toBeHidden(); // 导航链接再次隐藏
            } else {
              console.warn('未找到汉堡菜单按钮，请检查选择器或应用是否支持汉堡菜单。'); // 警告：未找到汉堡菜单按钮
            }
          } else {
            // 桌面和平板视口下，验证导航链接是否直接可见
            await expect(navigation.locator('a:has-text("Dashboard")')).toBeVisible(); // 导航链接可见
            await expect(navigation.locator('a:has-text("Manage Context")')).toBeVisible(); // 导航链接可见
            await expect(navigation.locator('a:has-text("Manage Keys")')).toBeVisible(); // 导航链接可见
            await expect(navigation.locator('a:has-text("Report")')).toBeVisible(); // 导航链接可见
          }
  
          // 验证 Bento 视图布局
          const bentoView = page.locator('.dashboard-view'); // 假设 Bento 视图有一个类名 'dashboard-view'
          await expect(bentoView).toBeVisible(); // Bento 视图应该可见
          // 验证 Bento 卡片布局是否适应视口
          const bentoCards = page.locator('.bento-card'); // 假设 Bento 卡片有一个类名 'bento-card'
          const cardCount = await bentoCards.count(); // 获取卡片数量
          if (cardCount > 0) {
            // 验证第一张卡片的位置和大小，确保其在视口内且布局合理
            const firstCardBoundingBox = await bentoCards.first().boundingBox();
            expect(firstCardBoundingBox).not.toBeNull(); // 边界框不为空
            if (firstCardBoundingBox) { // 检查是否为 null
              expect(firstCardBoundingBox.x).toBeGreaterThanOrEqual(0); // x 坐标大于等于 0
              expect(firstCardBoundingBox.y).toBeGreaterThanOrEqual(0); // y 坐标大于等于 0
              expect(firstCardBoundingBox.width).toBeLessThanOrEqual(viewport.width); // 宽度小于等于视口宽度
              expect(firstCardBoundingBox.height).toBeLessThanOrEqual(viewport.height); // 高度小于等于视口高度
            }
          } else {
            console.warn('未找到 Bento 卡片，请检查选择器或 Dashboard 页面是否包含 Bento 卡片。'); // 警告：未找到 Bento 卡片
          }
  
          // 切换到 Traditional 视图并验证布局
          const traditionalSwitchButton = page.locator('button:has-text("Traditional")'); // 假设切换按钮的文本是“Traditional”
          if (await traditionalSwitchButton.isVisible()) {
            await traditionalSwitchButton.click(); // 点击切换到 Traditional 视图
            await expect(page.locator('.traditional-list-view')).toBeVisible(); // Traditional 视图可见
            await expect(bentoView).toBeHidden(); // Bento 视图隐藏
  
            // 验证 Traditional 列表布局
            const traditionalList = page.locator('[data-testid="traditional-list-container"]'); // 假设 Traditional 列表容器有 data-testid="traditional-list-container"
            await expect(traditionalList).toBeVisible(); // 传统列表容器可见
            // 验证列表项是否在视口内且布局合理
            const listItems = page.locator('.traditional-list-item'); // 假设列表项有一个类名 'traditional-list-item'
            const listItemCount = await listItems.count(); // 获取列表项数量
            if (listItemCount > 0) {
              const firstListItemBoundingBox = await listItems.first().boundingBox();
              expect(firstListItemBoundingBox).not.toBeNull(); // 边界框不为空
              if (firstListItemBoundingBox) { // 添加空值检查，确保在访问属性前对象不为null
                expect(firstListItemBoundingBox.x).toBeGreaterThanOrEqual(0); // x 坐标大于等于 0
                expect(firstListItemBoundingBox.y).toBeGreaterThanOrEqual(0); // y 坐标大于等于 0
                expect(firstListItemBoundingBox.width).toBeLessThanOrEqual(viewport.width); // 宽度小于等于视口宽度
                expect(firstListItemBoundingBox.height).toBeLessThanOrEqual(viewport.height); // 高度小于等于视口高度
              }
            } else {
              console.warn('未找到 Traditional 列表项，请检查选择器或 Traditional 页面是否包含列表项。'); // 警告：未找到 Traditional 列表项
            }
  
            // 切换回 Bento 视图
            const bentoSwitchButton = page.locator('button:has-text("Bento")'); // 假设切换按钮的文本是“Bento”
            if (await bentoSwitchButton.isVisible()) {
              await bentoSwitchButton.click(); // 点击切换回 Bento 视图
              await expect(bentoView).toBeVisible(); // Bento 视图可见
              await expect(page.locator('.traditional-list-view')).toBeHidden(); // Traditional 视图隐藏
            } else {
              console.warn('未找到 Bento 切换按钮，请检查选择器。'); // 警告：未找到 Bento 切换按钮
            }
          } else {
            console.warn('未找到 Traditional 切换按钮，请检查选择器或 Dashboard 页面是否支持视图切换。'); // 警告：未找到 Traditional 切换按钮
          }
        });
      }
    });
  });

  test('应能管理 API Key', async ({ page }) => {
    // 导航到 Manage Keys 页面
    await page.goto(`${BASE_URL}/manage-keys`); // 根据实际的 Manage Keys 页面 URL 修改
    await page.waitForLoadState('networkidle'); // 等待数据加载

    // 验证数据加载 (检查表格或其他列表是否存在数据)
    // 假设 Key 列表在表格中，且至少有一行数据
    await expect(page.locator('table tbody tr')).toBeVisible(); // 根据实际的 Key 列表选择器修改

    // 打开添加/编辑模态框 (需要根据实际页面元素和交互进行调整)
    // 点击添加 Key 按钮
    // 注意：这里假设添加按钮文本为“添加 Key”或 data-test-id="add-key-button"
    await page.click('button:has-text("添加 Key")'); // 根据实际的添加按钮选择器和文本修改
    // 或者使用 data-test-id
    // await page.click('[data-test-id="add-key-button"]');
    // 验证模态框是否显示
    // 注意：这里假设模态框有一个类名 '.modal' 或 data-test-id="key-modal"
    await expect(page.locator('.modal')).toBeVisible(); // 根据实际的模态框选择器修改
    // 或者使用 data-test-id
    // await expect(page.locator('[data-test-id="key-modal"]')).toBeVisible();
    // 关闭模态框
    // 注意：这里假设关闭按钮有一个类名 '.close-button' 或 data-test-id="close-modal-button"
    await page.click('.modal .close-button'); // 根据实际的关闭按钮选择器修改
    // 或者使用 data-test-id
    // await page.click('[data-test-id="close-modal-button"]');
    // 验证模态框是否隐藏
    await expect(page.locator('.modal')).toBeHidden(); // 根据实际的模态框选择器修改
    // 或者使用 data-test-id
    // await expect(page.locator('[data-test-id="key-modal"]')).toBeHidden();

    // 删除 Key (需要根据实际页面元素和交互进行调整)
    // 找到第一条记录的删除按钮并点击
    // 注意：这里假设删除按钮在每行中，且文本为“删除”或 data-test-id="delete-key-button"
    // await page.locator('table tbody tr:first-child button:has-text("删除")').click(); // 根据实际的删除按钮选择器和文本修改
    // 或者使用 data-test-id
    // await page.locator('table tbody tr:first-child [data-test-id="delete-key-button"]').click();
    // 确认删除操作 (如果需要)
    // 注意：这里假设有一个确认删除的模态框或弹窗，并点击确认按钮
    // await page.click('button:has-text("确认删除")'); // 根据实际的确认按钮选择器和文本修改
    // 验证 Key 是否被删除
    // 这部分需要根据实际应用的行为来编写断言
  });

  test('应能在 Bento 和 Traditional 视图之间切换', async ({ page }) => {
    // 导航到 Dashboard 页面
    await page.goto(`${BASE_URL}/dashboard`); // 根据实际的 Dashboard 页面 URL 修改
    await page.waitForLoadState('networkidle'); // 等待页面加载

    // 验证初始视图 (假设初始是 Bento 视图)
    // 注意：这里假设 Dashboard 组件是 Bento 视图的代表，TraditionalListView 是 Traditional 视图的代表
    await expect(page.locator('.dashboard-view')).toBeVisible(); // 假设 Dashboard 视图有一个类名 'dashboard-view'
    await expect(page.locator('.traditional-list-view')).toBeHidden(); // 根据实际的 Traditional 视图标识选择器修改

    // 切换到 Traditional 视图
    // 假设切换按钮的文本是“Traditional”或 data-test-id="switch-to-traditional"
    await page.click('button:has-text("Traditional")'); // 根据实际的切换按钮选择器和文本修改

    // 验证是否切换到 Traditional 视图
    await expect(page.locator('.dashboard-view')).toBeHidden(); // 假设 Dashboard 视图有一个类名 'dashboard-view'
    await expect(page.locator('.traditional-list-view')).toBeVisible(); // 根据实际的 Traditional 视图标识选择器修改
    await expect(page.locator('[data-testid="traditional-list-container"]')).toBeVisible(); // 验证列表容器可见
    await expect(page.locator('[data-testid="empty-data-message"]')).toBeHidden(); // 验证空数据消息隐藏

    // 切换回 Bento 视图
    // 假设切换按钮的文本是“Bento”或 data-test-id="switch-to-bento"
    await page.click('button:has-text("Bento")'); // 根据实际的切换按钮选择器和文本修改

    // 验证是否切换回 Bento 视图
    await expect(page.locator('.dashboard-view')).toBeVisible(); // 假设 Dashboard 视图有一个类名 'dashboard-view'
    await expect(page.locator('.traditional-list-view')).toBeHidden(); // 根据实际的 Traditional 视图标识选择器修改
  });

  test('应在数据为空时显示“目前没有数据可显示”', async ({ page }) => {
    // 导航到 Dashboard 页面
    await page.goto(`${BASE_URL}/dashboard`);
    await page.waitForLoadState('networkidle');

    // 切换到 Traditional 视图
    await page.click('button:has-text("Traditional")');
    await expect(page.locator('.traditional-list-view')).toBeVisible();

    // 模拟 appStore 中的 traditionalListItems 为空
    await page.evaluate(() => {
      const appStore = window.__pinia.useAppStore(); // 假设 Pinia store 挂载在 window.__pinia 上
      appStore.setTraditionalListItems([]);
    });

    // 验证“目前没有数据可显示”消息是否可见
    await expect(page.locator('[data-testid="empty-data-message"]')).toBeVisible();
    await expect(page.locator('[data-testid="traditional-list-container"]')).toBeHidden(); // 验证列表容器隐藏

    // 模拟 appStore 中的 traditionalListItems 恢复数据
    await page.evaluate(() => {
      const appStore = window.__pinia.useAppStore();
      appStore.setTraditionalListItems([
        { id: 1, name: '列表项 1' },
        { id: 2, name: '列表项 2' },
      ]);
    });

    // 验证列表容器可见，空数据消息隐藏
    await expect(page.locator('[data-testid="traditional-list-container"]')).toBeVisible();
    await expect(page.locator('[data-testid="empty-data-message"]')).toBeHidden();
  });

  test('应能访问错误页面并验证内容', async ({ page }) => {
    // 访问 404 页面
    await page.goto(`${BASE_URL}/non-existent-page`); // 访问一个不存在的路径
    await page.waitForLoadState('networkidle'); // 等待页面加载
    // 注意：这里假设错误页面有一个 h1 标签显示错误信息
    await expect(page.locator('h1:has-text("404 Not Found")')).toBeVisible(); // 根据实际的 404 页面标题选择器和文本修改

    // 访问 401 页面 (假设需要模拟未授权状态)
    // 这可能需要更复杂的设置，例如清除认证信息或模拟后端响应
    // 尝试导航到需要认证但未认证时会重定向到 401 的页面
    await page.goto(`${BASE_URL}/manage`); // 假设 /manage 需要认证
    await page.waitForURL(`${BASE_URL}/unauthorized`); // 等待重定向到 401 页面
    await page.waitForLoadState('networkidle'); // 等待页面加载
    await expect(page.locator('h1:has-text("401 Unauthorized")')).toBeVisible(); // 根据实际的 401 页面标题选择器和文本修改

    // 访问 403 页面 (假设需要模拟禁止访问状态)
    // 这可能需要更复杂的设置，例如使用特定用户角色或模拟后端响应
    // 尝试导航到需要特定权限但当前用户没有权限时会重定向到 403 的页面
    // await page.goto(`${BASE_URL}/some-restricted-page`); // 假设 /some-restricted-page 需要特定权限
    await page.goto(`${BASE_URL}/forbidden`); // 直接访问 403 页面进行验证
    await page.waitForLoadState('networkidle'); // 等待页面加载
    await expect(page.locator('h1:has-text("403 Forbidden")')).toBeVisible(); // 根据实际的 403 页面标题选择器和文本修改
  });

});