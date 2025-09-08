<template>
  <div id="app" :class="{ 'dark-theme': isDark }">
    <!-- 全局通知组件 -->
    <div v-if="notification.show" class="global-notification" :class="notification.type">
      {{ notification.message }}
    </div>

    <!-- 主内容区域 -->
    <router-view v-slot="{ Component, route }">
      <transition :name="route.meta.transition || 'fade'" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useAppStore } from './stores/appStore';

const appStore = useAppStore();
const isDark = ref(false);
const notification = ref({
  show: false,
  message: '',
  type: 'info'
});

// 主题切换
const toggleTheme = () => {
  isDark.value = !isDark.value;
  document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light');
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light');
};

// 显示通知
const showNotification = (message, type = 'info') => {
  notification.value = { show: true, message, type };
  setTimeout(() => {
    notification.value.show = false;
  }, 3000);
};

// 生命周期
onMounted(() => {
  // 加载主题
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme) {
    isDark.value = savedTheme === 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
  }
  
  // 添加全局样式
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/_app/assets/styles/global.css';
  document.head.appendChild(link);
});

// 暴露给子组件
window.toggleTheme = toggleTheme;
window.showNotification = showNotification;
</script>

<style>
/* 基础重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
  font-size: 16px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

body {
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  color: #111827;
  transition: all 0.3s ease;
}

[data-theme="dark"] body {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  color: #f9fafb;
}

#app {
  min-height: 100vh;
}

/* 全局过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: all 0.3s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-20px);
}

/* 全局通知 */
.global-notification {
  position: fixed;
  top: 20px;
  right: 20px;
  padding: 1rem 1.5rem;
  border-radius: 0.5rem;
  color: white;
  font-weight: 500;
  z-index: 1000;
  animation: slideIn 0.3s ease;
}

.global-notification.success {
  background: #10b981;
}

.global-notification.error {
  background: #ef4444;
}

.global-notification.info {
  background: #3b82f6;
}

@keyframes slideIn {
  from {
    transform: translateX(100%);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: rgba(0, 0, 0, 0.1);
}

::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.3);
}
</style>
