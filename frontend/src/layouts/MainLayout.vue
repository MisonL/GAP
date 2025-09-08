<template>
  <div :class="layoutClass">
    <!-- 头部区域，可能包含 Logo, 标题, 用户信息等 -->
    <header class="layout-header" role="banner" aria-label="主页眉">
      <!-- AppNavigation 组件可能会被修改以适应 Bento 风格，或移至侧边/底部 -->
      <AppNavigation />
      <div class="header-content">
        <span class="app-title">Gemini API 代理</span>
        <!-- 用户信息或视图切换组件占位符 -->
        <div class="header-right">
          <ViewSwitcher /> <!-- 添加视图切换组件 -->
          <!-- <UserInfo /> -->
        </div>
      </div>
    </header>

    <!-- 主内容区域 -->
    <main class="layout-content" role="main" aria-label="主内容区域">
      <router-view /> <!-- 用于显示子路由的组件，例如 Dashboard.vue -->
    </main>

    <!-- 底部导航或 Dock 区域 -->
    <footer class="layout-footer" role="contentinfo" aria-label="页脚信息">
       <!--  将导航移至底部或侧边 -->
      <!-- <p>&copy; 2025 Gemini API 代理</p> -->
    </footer>
    <GlobalNotification /> <!-- 全局通知组件 -->
  </div>
</template>

<script setup>
import { computed } from 'vue'; // 导入 computed
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/authStore.js';
import { useAppStore } from '@/stores/appStore'; // 导入 appStore
import AppNavigation from '@/components/AppNavigation.vue'; // 导入导航组件
import ViewSwitcher from '@/components/ViewSwitcher.vue'; // 视图切换组件
import GlobalNotification from '@/components/common/GlobalNotification.vue'; // 导入全局通知组件
// import UserInfo from '@/components/UserInfo.vue'; // 用户信息组件 (待创建/修改)


const router = useRouter();
const authStore = useAuthStore();
const appStore = useAppStore(); // 获取 store 实例

// 计算属性，根据 viewMode 返回类名
const layoutClass = computed(() => {
  return {
    'main-layout': true, // 基础类
    'bento-layout': appStore.viewMode === 'bento',
    'traditional-layout': appStore.viewMode === 'traditional',
  };
});

// AppNavigation 组件内部已处理登出逻辑，此处移除
// const handleLogout = () => {
//   authStore.logout();
//   router.push({ name: 'Login' });
// };

console.log('[MainLayout.vue] <script setup> executed.');
</script>

<style scoped>
/* 整体布局容器 */
.main-layout {
  display: flex;
  flex-direction: column; /* 默认垂直布局 */
  min-height: 100vh;
  background-color: #f0f2f5; /* 柔和背景色 */
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif;
}

/* Bento 风格布局调整 */
.main-layout.bento-layout {
  display: flex;
}

/* 头部样式 */
.layout-header {
  background-color: rgba(255, 255, 255, 0.9); /* 半透明头部 */
  backdrop-filter: blur(10px);
  padding: 15px 20px;
  border-bottom: 1px solid rgba(224, 224, 224, 0.5);
  position: sticky; /* 头部固定 */
  top: 0;
  z-index: 100;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 1200px; /* 限制头部内容宽度 */
  margin: 0 auto;
}

.app-title {
  font-size: 20px;
  font-weight: 700;
  color: #333;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 15px; /* 头部右侧元素间距 */
}


/* 主内容区域 */
.layout-content {
  flex-grow: 1;
  padding: 20px; /* 增加内边距 */
  max-width: 1200px; /* 限制内容宽度 */
  margin: 0 auto;
  width: 100%; /* 确保宽度为100% */
  box-sizing: border-box; /* 包含内边距 */
}

/* 底部样式 (可能作为 Dock 或底部导航) */
.layout-footer {
  background-color: rgba(255, 255, 255, 0.9); /* 半透明底部 */
  backdrop-filter: blur(10px);
  padding: 10px 20px;
  border-top: 1px solid rgba(224, 224, 224, 0.5);
  text-align: center;
  font-size: 0.9em;
  color: #6c757d;
  position: sticky; /* 底部固定 */
  bottom: 0;
  z-index: 100;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .layout-header, .layout-content, .layout-footer {
    padding-left: 10px;
    padding-right: 10px;
  }

  .header-content {
    flex-direction: column; /* 小屏幕下垂直堆叠 */
    align-items: flex-start; /* 左对齐 */
    gap: 10px; /* 调整间距 */
  }

  .header-right {
    width: 100%; /* 占据全部宽度 */
    justify-content: flex-end; /* 右侧元素靠右对齐 */
  }

  .app-title {
    font-size: 1.8rem; /* 调整标题大小 */
  }
}

@media (max-width: 480px) {
  .layout-header, .layout-content, .layout-footer {
    padding-left: 5px;
    padding-right: 5px;
  }

  .app-title {
    font-size: 1.5rem; /* 进一步调整标题大小 */
  }
}
</style>
