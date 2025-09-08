<template>
  <nav class="app-navigation bottom-dock" role="navigation" aria-label="主应用导航">
    <ul>
      <li>
        <router-link :to="{ name: 'Dashboard' }" aria-label="仪表盘" active-class="router-link-active">
          <i class="icon-dashboard" aria-hidden="true"></i> <!-- 仪表盘图标占位符 -->
          <span>仪表盘</span>
        </router-link>
      </li>
      <li>
        <router-link :to="{ name: 'ManageKeys' }" aria-label="管理 API Key" active-class="router-link-active">
           <i class="icon-key" aria-hidden="true"></i> <!-- Key 管理图标占位符 -->
          <span>API Key</span>
        </router-link>
      </li>
      <li>
        <router-link :to="{ name: 'ManageContext' }" aria-label="管理上下文" active-class="router-link-active">
          <i class="icon-context" aria-hidden="true"></i> <!-- 上下文管理图标占位符 -->
          <span>上下文</span>
        </router-link>
      </li>
      <li>
        <router-link :to="{ name: 'Report' }" aria-label="查看周期报告" active-class="router-link-active">
          <i class="icon-report" aria-hidden="true"></i> <!-- 周期报告图标占位符 -->
          <span>报告</span>
        </router-link>
      </li>
      <li>
        <router-link :to="{ name: 'config' }" aria-label="系统配置" active-class="router-link-active">
          <i class="icon-settings" aria-hidden="true"></i> <!-- 配置图标占位符 -->
          <span>配置</span>
        </router-link>
      </li>
      <li>
       <a href="/docs" target="_blank" rel="noopener noreferrer" aria-label="打开 API 文档">
         <i class="icon-document" aria-hidden="true"></i> <!-- API文档图标占位符 -->
         <span>API 文档</span>
       </a>
     </li>
      <!-- TODO: 添加用户/设置等图标导航项 -->
       <li>
        <a href="#" @click.prevent="handleLogout" aria-label="登出">
          <i class="icon-logout" aria-hidden="true"></i> <!-- 登出图标占位符 -->
          <span>登出</span>
        </a>
      </li>
    </ul>
    <!-- 用户信息可以移到其他地方，例如头部或设置页面 -->
    <!-- <div class="user-info" v-if="authStore.isAuthenticated">
      <span>用户: {{ authStore.user?.name || '未知用户' }} ({{ authStore.isAdmin ? '管理员' : '普通用户' }})</span>
    </div> -->
  </nav>
</template>

<script setup>
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/authStore.js';

const router = useRouter();
const authStore = useAuthStore();

// 登出逻辑
const handleLogout = () => {
  authStore.logout();
  router.push({ name: 'Login' });
};

console.log('[AppNavigation.vue] <script setup> executed.');
</script>

<style scoped>
/* 底部 Dock 导航样式 */
.app-navigation.bottom-dock {
  background-color: rgba(255, 255, 255, 0.9); /* 半透明背景 */
  backdrop-filter: blur(10px); /* 毛玻璃效果 */
  padding: 10px 20px;
  border-top: 1px solid rgba(224, 224, 224, 0.5);
  position: fixed; /* 固定在底部 */
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 1000; /* 确保在最上层 */
  display: flex;
  justify-content: center; /* 导航项居中 */
  box-shadow: 0 -5px 15px rgba(0, 0, 0, 0.05); /* 顶部阴影 */
}

.app-navigation.bottom-dock ul {
  list-style-type: none;
  margin: 0;
  padding: 0;
  display: flex;
  gap: 30px; /* 导航项之间的间距 */
}

.app-navigation.bottom-dock li {
  margin: 0; /* 移除默认外边距 */
}

.app-navigation.bottom-dock a {
  color: #555; /* 默认图标/文字颜色 */
  text-decoration: none;
  padding: 8px 12px; /* 调整内边距 */
  display: flex;
  flex-direction: column; /* 图标和文字垂直排列 */
  align-items: center; /* 居中 */
  border-radius: 8px; /* 圆角 */
  transition: color 0.3s ease, background-color 0.3s ease;
}

.app-navigation.bottom-dock a:hover,
.app-navigation.bottom-dock a.router-link-active {
  color: #007bff; /* 激活/悬停颜色 */
  background-color: rgba(0, 123, 255, 0.1); /* 激活/悬停背景色 */
}

.app-navigation.bottom-dock a i {
  font-size: 24px; /* 图标大小 */
  margin-bottom: 4px; /* 图标与文字间距 */
}

.app-navigation.bottom-dock a span {
  font-size: 0.8em; /* 文字大小 */
  font-weight: 500;
}

/* 用户信息区域 (如果保留) */
/* .user-info {
  color: #f8f9fa;
  font-size: 0.9em;
} */

/* TODO: 添加图标字体或 SVG */
/* 响应式调整 */
@media (max-width: 768px) {
  .app-navigation.bottom-dock ul {
    gap: 15px; /* 减小导航项间距 */
  }

  .app-navigation.bottom-dock a {
    padding: 6px 8px; /* 调整内边距 */
  }

  .app-navigation.bottom-dock a i {
    font-size: 20px; /* 调整图标大小 */
  }

  .app-navigation.bottom-dock a span {
    font-size: 0.7em; /* 调整文字大小 */
  }
}

@media (max-width: 480px) {
  .app-navigation.bottom-dock ul {
    gap: 10px; /* 进一步减小导航项间距 */
  }

  .app-navigation.bottom-dock a {
    padding: 5px 6px; /* 进一步调整内边距 */
  }

  .app-navigation.bottom-dock a i {
    font-size: 18px; /* 进一步调整图标大小 */
  }

  .app-navigation.bottom-dock a span {
    display: none; /* 在极小屏幕上隐藏文字，只显示图标 */
  }
}
</style>
