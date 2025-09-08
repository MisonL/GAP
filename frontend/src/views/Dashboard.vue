<template>
  <div class="dashboard-container">
    <!-- 顶部导航栏 -->
    <nav class="dashboard-nav">
      <div class="nav-brand">
        <div class="brand-icon">🚀</div>
        <h1>Gemini API 代理</h1>
        <span class="version-badge">v{{ appVersion }}</span>
      </div>
      
      <div class="nav-actions">
        <button @click="toggleTheme" class="theme-toggle" :title="isDark ? '切换到浅色模式' : '切换到深色模式'">
          {{ isDark ? '🌙' : '☀️' }}
        </button>
        <button @click="refreshAllData" class="refresh-btn" :class="{ 'spinning': isRefreshing }">
          <span class="refresh-icon">↻</span>
        </button>
      </div>
    </nav>

    <!-- 主要内容区域 -->
    <main class="dashboard-main">
      <!-- 内存模式警告 -->
      <div v-if="isMemoryMode" class="memory-mode-warning">
        <div class="warning-content">
          <div class="warning-icon">⚠️</div>
          <div class="warning-text">
            <strong>警告：</strong>当前运行在纯内存模式下，所有配置和数据仅在当前会话中有效，重启服务后将丢失。
          </div>
        </div>
      </div>

      <!-- 欢迎区域 -->
      <section class="welcome-section">
        <div class="welcome-content">
          <h2 class="welcome-title">
            欢迎使用 Gemini API 代理
            <span class="wave-emoji">👋</span>
          </h2>
          <p class="welcome-subtitle">
            现代化的API密钥管理和上下文缓存系统
          </p>
        </div>
      </section>

      <!-- 统计卡片网格 -->
      <section class="stats-grid">
        <BentoCard 
          title="API Keys" 
          :subtitle="`${keysStore.activeKeys.length} 个活跃密钥`"
          :gridSpan="{ colSpan: 1, rowSpan: 1 }"
          variant="elevated"
          decoration="gradient"
        >
          <div class="stat-display">
            <div class="stat-icon keys-icon">🔑</div>
            <div class="stat-details">
              <div class="stat-number">{{ keysStore.activeKeys.length }}</div>
              <div class="stat-label">活跃密钥</div>
              <div class="stat-total">总计: {{ keysStore.keys.length }} 个</div>
            </div>
          </div>
          <div class="stat-progress">
            <div class="progress-bar">
              <div 
                class="progress-fill" 
                :style="{ width: `${(keysStore.activeKeys.length / Math.max(keysStore.keys.length, 1)) * 100}%` }"
              ></div>
            </div>
          </div>
        </BentoCard>

        <BentoCard 
          title="上下文缓存" 
          :subtitle="`${contextStore.contextCount} 个条目`"
          :gridSpan="{ colSpan: 1, rowSpan: 1 }"
          variant="elevated"
          decoration="dots"
        >
          <div class="stat-display">
            <div class="stat-icon context-icon">💾</div>
            <div class="stat-details">
              <div class="stat-number">{{ contextStore.contextCount }}</div>
              <div class="stat-label">上下文条目</div>
              <div class="stat-expired">{{ contextStore.expiredContexts.length }} 个已过期</div>
            </div>
          </div>
          <div class="stat-chart">
            <div class="chart-bar">
              <div class="bar active" :style="{ height: `${Math.min(contextStore.contextCount * 2, 100)}%` }"></div>
              <div class="bar expired" :style="{ height: `${Math.min(contextStore.expiredContexts.length * 5, 100)}%` }"></div>
            </div>
          </div>
        </BentoCard>

        <BentoCard 
          title="系统状态" 
          subtitle="实时系统信息"
          :gridSpan="{ colSpan: 2, rowSpan: 1 }"
          variant="glass"
          decoration="waves"
        >
          <div class="system-status">
            <div class="status-item">
              <div class="status-indicator online"></div>
              <div class="status-info">
                <span class="status-label">服务状态</span>
                <span class="status-value">在线</span>
              </div>
            </div>
            
            <div class="status-item">
              <div class="status-indicator version"></div>
              <div class="status-info">
                <span class="status-label">版本</span>
                <span class="status-value">v{{ appVersion }}</span>
              </div>
            </div>
            
            <div class="status-item">
              <div class="status-indicator storage"></div>
              <div class="status-info">
                <span class="status-label">存储模式</span>
                <span class="status-value">{{ storageMode }}</span>
              </div>
            </div>
            
            <div class="status-item">
              <div class="status-indicator auth"></div>
              <div class="status-info">
                <span class="status-label">认证状态</span>
                <span class="status-value">{{ authStore.isAuthenticated ? '已认证' : '未认证' }}</span>
              </div>
            </div>
          </div>
        </BentoCard>

        <BentoCard 
          title="快速操作" 
          subtitle="常用功能快捷入口"
          :gridSpan="{ colSpan: 2, rowSpan: 1 }"
          variant="elevated"
        >
          <div class="quick-actions">
            <button @click="goToKeys" class="action-card keys">
              <div class="action-icon">🔑</div>
              <div class="action-content">
                <h4>管理Keys</h4>
                <p>添加、编辑和删除API密钥</p>
              </div>
            </button>
            
            <button @click="goToContext" class="action-card context">
              <div class="action-icon">💾</div>
              <div class="action-content">
                <h4>管理上下文</h4>
                <p>查看和管理对话缓存</p>
              </div>
            </button>
            
            <button @click="goToReport" class="action-card report">
              <div class="action-icon">📊</div>
              <div class="action-content">
                <h4>查看报告</h4>
                <p>查看使用统计和分析</p>
              </div>
            </button>
            
            <button @click="refreshAllData" class="action-card refresh">
              <div class="action-icon">🔄</div>
              <div class="action-content">
                <h4>刷新数据</h4>
                <p>更新所有系统信息</p>
              </div>
            </button>
          </div>
        </BentoCard>
      </section>

      <!-- 最近活动 -->
      <section class="recent-activity">
        <BentoCard 
          title="最近活动" 
          subtitle="系统最新动态"
          :gridSpan="{ colSpan: 2, rowSpan: 1 }"
          variant="elevated"
        >
          <div class="activity-list">
            <div class="activity-item" v-for="(activity, index) in recentActivities" :key="index">
              <div class="activity-icon" :class="activity.type">{{ activity.icon }}</div>
              <div class="activity-content">
                <div class="activity-title">{{ activity.title }}</div>
                <div class="activity-time">{{ activity.time }}</div>
              </div>
            </div>
          </div>
        </BentoCard>
      </section>
    </main>

    <!-- 加载遮罩 -->
    <div v-if="isLoading" class="loading-overlay">
      <div class="loading-content">
        <div class="loading-spinner"></div>
        <p>正在加载数据...</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/authStore.js';
import { useKeysStore } from '@/stores/keysStore.js';
import { useContextStore } from '@/stores/contextStore.js';
import { useAppStore } from '@/stores/appStore.js';
import BentoCard from '@/components/common/BentoCard.vue';

const router = useRouter();
const authStore = useAuthStore();
const keysStore = useKeysStore();
const contextStore = useContextStore();
const appStore = useAppStore();

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
    console.error('数据刷新失败:', error);
  } finally {
    isRefreshing.value = false;
  }
};

const goToKeys = () => {
  router.push({ name: 'keys' });
};

const goToContext = () => {
  router.push({ name: 'context' });
};

const goToReport = () => {
  router.push({ name: 'report' });
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

// 检查存储模式
const checkStorageMode = async () => {
  try {
    const response = await apiService.getMemoryModeWarning();
    isMemoryMode.value = response.storage_mode === 'memory';
    storageMode.value = response.storage_mode;
  } catch (error) {
    console.error('检查存储模式失败:', error);
  }
};
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

/* 欢迎区域 */
.welcome-section {
  text-align: center;
  margin-bottom: 3rem;
}

.welcome-content {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border-radius: var(--radius-xl);
  padding: 2rem;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.welcome-title {
  font-size: 2.5rem;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.wave-emoji {
  animation: wave 2s ease-in-out infinite;
}

@keyframes wave {
  0%, 100% { transform: rotate(0deg); }
  25% { transform: rotate(20deg); }
  75% { transform: rotate(-20deg); }
}

.welcome-subtitle {
  font-size: 1.125rem;
  color: var(--text-secondary);
  margin: 0;
}

/* 统计网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 1.5rem;
  margin-bottom: 2rem;
}

/* 统计显示 */
.stat-display {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.stat-icon {
  font-size: 2.5rem;
  padding: 1rem;
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  border-radius: var(--radius-lg);
  color: white;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.05); }
}

.stat-details {
  flex: 1;
}

.stat-number {
  font-size: 2rem;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 0.25rem;
}

.stat-label {
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin-bottom: 0.25rem;
}

.stat-total,
.stat-expired {
  font-size: 0.75rem;
  color: var(--text-tertiary);
}

/* 进度条 */
.stat-progress {
  margin-top: 1rem;
}

.progress-bar {
  height: 4px;
  background: var(--gray-200);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), var(--secondary));
  border-radius: var(--radius-sm);
  transition: width var(--transition-normal);
}

/* 图表 */
.stat-chart {
  margin-top: 1rem;
}

.chart-bar {
  display: flex;
  align-items: end;
  gap: 0.5rem;
  height: 40px;
}

.bar {
  flex: 1;
  border-radius: var(--radius-sm);
  transition: height var(--transition-normal);
}

.bar.active {
  background: var(--success);
}

.bar.expired {
  background: var(--warning);
}

/* 系统状态 */
.system-status {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
}

.status-item:hover {
  background: rgba(255, 255, 255, 0.2);
}

.status-indicator {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-indicator.online {
  background: var(--success);
  box-shadow: 0 0 10px var(--success);
}

.status-indicator.version {
  background: var(--primary);
  box-shadow: 0 0 10px var(--primary);
}

.status-indicator.storage {
  background: var(--secondary);
  box-shadow: 0 0 10px var(--secondary);
}

.status-indicator.auth {
  background: var(--info);
  box-shadow: 0 0 10px var(--info);
}

.status-info {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.status-label {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.status-value {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
}

/* 快速操作 */
.quick-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}

.action-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.5rem;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--transition-normal);
  text-align: left;
  border: none;
  color: inherit;
  font-family: inherit;
}

.action-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
  background: rgba(255, 255, 255, 0.2);
}

.action-card.keys:hover {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(165, 180, 252, 0.2));
}

.action-card.context:hover {
  background: linear-gradient(135deg, rgba(6, 182, 212, 0.2), rgba(103, 232, 249, 0.2));
}

.action-card.report:hover {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(110, 231, 183, 0.2));
}

.action-card.refresh:hover {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.2), rgba(252, 211, 77, 0.2));
}

.action-icon {
  font-size: 1.5rem;
  padding: 0.5rem;
  background: rgba(255, 255, 255, 0.2);
  border-radius: var(--radius-md);
}

.action-content h4 {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
  color: var(--text-primary);
}

.action-content p {
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin: 0;
}

/* 最近活动 */
.recent-activity {
  margin-top: 2rem;
}

.activity-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.activity-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
}

.activity-item:hover {
  background: rgba(255, 255, 255, 0.2);
}

.activity-icon {
  font-size: 1.25rem;
  flex-shrink: 0;
}

.activity-content {
  flex: 1;
}

.activity-title {
  font-size: 0.875rem;
  color: var(--text-primary);
  margin-bottom: 0.125rem;
}

.activity-time {
  font-size: 0.75rem;
  color: var(--text-secondary);
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

[data-theme="dark"] .warning-content {
  background: linear-gradient(135deg, #78350f, #92400e);
  border-color: #f59e0b;
  color: #fef3c7;
}

.warning-icon {
  font-size: 1.5rem;
  flex-shrink: 0;
}

.warning-text {
  font-size: 0.875rem;
  line-height: 1.5;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .dashboard-container {
    padding: 1rem;
  }
  
  .dashboard-nav {
    padding: 1rem;
    flex-direction: column;
    gap: 1rem;
  }
  
  .welcome-title {
    font-size: 2rem;
    flex-direction: column;
    gap: 0.5rem;
  }
  
  .stats-grid {
    grid-template-columns: 1fr;
    gap: 1rem;
  }
  
  .system-status {
    grid-template-columns: 1fr;
  }
  
  .quick-actions {
    grid-template-columns: 1fr;
  }
  
  .dashboard-main {
    padding: 1rem;
  }
}
</style>