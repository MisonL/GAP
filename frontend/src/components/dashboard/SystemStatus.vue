<template>
  <BentoCard 
    title="系统状态" 
    subtitle="实时系统信息"
    :grid-span="{ colSpan: 2, rowSpan: 1 }"
    variant="glass"
    decoration="waves"
  >
    <div class="system-status">
      <div class="status-item">
        <div class="status-indicator online" />
        <div class="status-info">
          <span class="status-label">服务状态</span>
          <span class="status-value">在线</span>
        </div>
      </div>
      
      <div class="status-item">
        <div class="status-indicator version" />
        <div class="status-info">
          <span class="status-label">版本</span>
          <span class="status-value">v{{ appVersion }}</span>
        </div>
      </div>
      
      <div class="status-item">
        <div class="status-indicator storage" />
        <div class="status-info">
          <span class="status-label">存储模式</span>
          <span class="status-value">{{ storageMode }}</span>
        </div>
      </div>
      
      <div class="status-item">
        <div class="status-indicator auth" />
        <div class="status-info">
          <span class="status-label">认证状态</span>
          <span class="status-value">{{ authStore.isAuthenticated ? '已认证' : '未认证' }}</span>
        </div>
      </div>
    </div>
  </BentoCard>
</template>

<script setup>
import BentoCard from '@/components/common/BentoCard.vue';
import { useAuthStore } from '@/stores/authStore';

defineProps({
  appVersion: {
    type: String,
    default: ''
  },
  storageMode: {
    type: String,
    default: ''
  }
});

const authStore = useAuthStore();
</script>

<style scoped>
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
</style>
