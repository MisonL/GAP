<template>
  <div class="dashboard-container">
    <!-- 顶部导航栏 -->
    <nav class="dashboard-nav">
      <div class="nav-brand">
        <div class="brand-icon">
          🚀
        </div>
        <h1>Gemini API 代理</h1>
        <span class="version-badge">v{{ appVersion }}</span>
      </div>
      
      <div class="nav-actions">
        <button
          class="theme-toggle"
          :title="isDark ? '切换到浅色模式' : '切换到深色模式'"
          @click="toggleTheme"
        >
          {{ isDark ? '🌙' : '☀️' }}
        </button>
        <button
          class="refresh-btn"
          :class="{ 'spinning': isRefreshing }"
          @click="refreshAllData"
        >
          <span class="refresh-icon">↻</span>
        </button>
      </div>
    </nav>

    <!-- 主要内容区域 -->
    <main class="dashboard-main">
      <!-- 内存模式警告 -->
      <div
        v-if="isMemoryMode"
        class="memory-mode-warning"
      >
        <div class="warning-content">
          <div class="warning-icon">
            ⚠️
          </div>
          <div class="warning-text">
            <strong>警告：</strong>当前运行在纯内存模式下，所有配置和数据仅在当前会话中有效，重启服务后将丢失。
          </div>
        </div>
      </div>

      <!-- 欢迎区域 -->
      <WelcomeSection />

      <!-- 统计卡片网格 -->
      <section class="stats-grid">
        <StatsGrid />

        <SystemStatus 
          :app-version="appVersion" 
          :storage-mode="storageMode" 
        />

        <QuickActions 
          @navigate="handleNavigation" 
          @refresh="refreshAllData" 
        />
      </section>

      <!-- 最近活动 -->
      <section class="recent-activity">
        <RecentActivity :activities="recentActivities" />
      </section>
    </main>

    <!-- 加载遮罩 -->
    <div
      v-if="isLoading"
      class="loading-overlay"
    >
      <div class="loading-content">
        <div class="loading-spinner" />
        <p>正在加载数据...</p>
      </div>
    </div>
  </div>
</template>

<script setup>
defineOptions({
  name: 'DashboardView'
})

import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';

import { useKeysStore } from '@/stores/keysStore.js';
import { useContextStore } from '@/stores/contextStore.js';
import apiService from '@/services/apiService';

import WelcomeSection from '@/components/dashboard/WelcomeSection.vue';
import StatsGrid from '@/components/dashboard/StatsGrid.vue';
import SystemStatus from '@/components/dashboard/SystemStatus.vue';
import QuickActions from '@/components/dashboard/QuickActions.vue';
import RecentActivity from '@/components/dashboard/RecentActivity.vue';

const router = useRouter();
// const authStore = useAuthStore();

const keysStore = useKeysStore();
const contextStore = useContextStore();

// 状态
const appVersion = ref('1.8.1');
const storageMode = ref('database');
const isRefreshing = ref(false);
const isDark = ref(false);
const isMemoryMode = ref(false);

// 计算属性
const isLoading = computed(() => 
  keysStore.loading || contextStore.loading || isRefreshing.value
);

// 模拟最近活动
const recentActivities = ref([
  {
    type: 'success',
    icon: '✅',
    title: '成功加载API密钥列表',
    time: '刚刚'
  },
  {
    type: 'info',
    icon: 'ℹ️',
    title: '系统状态检查完成',
    time: '2分钟前'
  },
  {
    type: 'warning',
    icon: '⚠️',
    title: '发现3个过期上下文',
    time: '5分钟前'
  }
]);

// 方法
const toggleTheme = () => {
  isDark.value = !isDark.value;
  document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light');
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light');
};

const refreshAllData = async () => {
  if (isRefreshing.value) return;
  
  isRefreshing.value = true;
  try {
    await Promise.all([
      keysStore.fetchKeys(),
      contextStore.fetchContexts()
    ]);
    
    // 添加新活动
    recentActivities.value.unshift({
      type: 'success',
      icon: '🔄',
      title: '数据刷新完成',
      time: '刚刚'
    });
    
    // 限制活动数量
    if (recentActivities.value.length > 5) {
      recentActivities.value = recentActivities.value.slice(0, 5);
    }
  } catch (error) {
    // eslint-disable-next-line no-console
    console.error('数据刷新失败:', error);
  } finally {
    isRefreshing.value = false;
  }
};

const handleNavigation = (routeName) => {
  router.push({ name: routeName });
};

// 检查存储模式
const checkStorageMode = async () => {
  try {
    const response = await apiService.getMemoryModeWarning();
    isMemoryMode.value = response.storage_mode === 'memory';
    storageMode.value = response.storage_mode;
  } catch (error) {
    // eslint-disable-next-line no-console
    console.error('检查存储模式失败:', error);
  }
};

// 生命周期
onMounted(() => {
  // 加载保存的主题
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme) {
    isDark.value = savedTheme === 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
  }
  
  // 检查存储模式
  checkStorageMode();
  
  // 初始加载数据
  refreshAllData();
});
</script>

<style scoped>
.dashboard-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
  transition: background var(--transition-normal);
}

[data-theme="dark"] .dashboard-container {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
}

/* 导航栏 */
.dashboard-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 2rem;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.brand-icon {
  font-size: 2rem;
  animation: float 3s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translateY(0px); }
  50% { transform: translateY(-10px); }
}

.nav-brand h1 {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.version-badge {
  background: var(--primary);
  color: white;
  padding: 0.25rem 0.5rem;
  border-radius: var(--radius-sm);
  font-size: 0.75rem;
  font-weight: 500;
}

.nav-actions {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.theme-toggle,
.refresh-btn {
  background: rgba(255, 255, 255, 0.2);
  border: none;
  border-radius: 50%;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: 1.2rem;
}

.theme-toggle:hover,
.refresh-btn:hover {
  background: rgba(255, 255, 255, 0.3);
  transform: scale(1.1);
}

.refresh-btn.spinning .refresh-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 主内容区域 */
.dashboard-main {
  padding: 2rem;
  max-width: 1200px;
  margin: 0 auto;
}

/* 统计网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 1.5rem;
  margin-bottom: 2rem;
}

/* 最近活动 */
.recent-activity {
  margin-top: 2rem;
}

/* 加载遮罩 */
.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(5px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.loading-content {
  background: var(--bg-primary);
  padding: 2rem;
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-xl);
  text-align: center;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid var(--gray-200);
  border-top: 4px solid var(--primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 1rem;
}

.loading-content p {
  color: var(--text-secondary);
  margin: 0;
}

/* 内存模式警告 */
.memory-mode-warning {
  margin-bottom: 2rem;
}

.warning-content {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.5rem;
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  border: 1px solid #f59e0b;
  border-radius: var(--radius-lg);
  color: #92400e;
  box-shadow: var(--shadow-md);
}
</style>