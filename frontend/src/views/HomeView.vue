<template>
  <div class="dashboard-view">
    <header class="dashboard-header">
      <h1>仪表盘总览</h1>
      <p v-if="authStore.user">欢迎回来, {{ authStore.user.name }}!</p>
    </header>
    
    <div class="bento-grid">
      <BentoCard title="API Key 状态" :gridSpan="{ colSpan: 1, rowSpan: 1 }">
        <p>您当前有 X 个活动的 API Key。</p>
        <router-link :to="{ name: 'ManageKeys' }">管理 Keys</router-link>
      </BentoCard>

      <BentoCard title="上下文缓存" :gridSpan="{ colSpan: 1, rowSpan: 1 }">
        <p>当前缓存了 Y 个上下文条目。</p>
        <router-link :to="{ name: 'ManageContext' }">管理上下文</router-link>
      </BentoCard>
      
      <BentoCard title="近期用量" :gridSpan="{ colSpan: 2, rowSpan: 2 }">
        <p>这里将显示用量图表或摘要。</p>
        <router-link :to="{ name: 'Report' }">查看完整报告</router-link>
      </BentoCard>
      
      <BentoCard title="快速操作" :gridSpan="{ colSpan: 1, rowSpan: 1 }">
        <ul>
          <li><button @click="notImplemented">创建新 Key</button></li>
          <li><button @click="notImplemented">清理缓存</button></li>
        </ul>
      </BentoCard>
       <BentoCard title="系统信息" :gridSpan="{ colSpan: 1, rowSpan: 1 }">
        <p>Key 存储模式: {{ keyModePlaceholder }}</p>
        <p>版本: v{{ appVersionPlaceholder }}</p>
      </BentoCard>
      <!-- 更多 Bento 卡片 -->
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useAuthStore } from '@/stores/authStore.js';
import { useRouter } from 'vue-router';
import BentoCard from '@/components/common/BentoCard.vue';

const authStore = useAuthStore();
const router = useRouter();

// 占位符数据，后续会从 API 或 store 获取
const keyModePlaceholder = ref('memory'); 
const appVersionPlaceholder = ref('1.8.1'); // 假设版本号

const handleLogout = () => { // 虽然登出按钮在 MainLayout，但这里保留以备不时之需
  authStore.logout();
  router.push({ name: 'Login' });
};

const notImplemented = () => {
  alert('此功能尚未实现！');
};

onMounted(() => {
  console.log('[HomeView/DashboardView] <script setup> onMounted executed.');
  // 在这里可以获取仪表盘所需的数据
});
</script>

<style scoped>
.dashboard-view {
  padding: 1rem;
}

.dashboard-header {
  margin-bottom: 2rem;
  text-align: center;
}

.dashboard-header h1 {
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.bento-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); /* 响应式列 */
  gap: 1rem; /* 卡片间距 */
}

/* 确保 BentoCard 内的链接和按钮样式合适 */
.bento-grid p {
  margin-bottom: 0.5rem;
}
.bento-grid a,
.bento-grid button {
  display: inline-block;
  margin-top: 0.5rem;
  padding: 0.5rem 1rem;
  background-color: #007bff;
  color: white;
  text-decoration: none;
  border-radius: 4px;
  border: none;
  cursor: pointer;
  font-size: 0.9rem;
}
.bento-grid button {
   margin-right: 0.5rem;
}

.bento-grid a:hover,
.bento-grid button:hover {
  background-color: #0056b3;
}
</style>
