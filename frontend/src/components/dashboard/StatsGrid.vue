<template>
  <div class="stats-grid-container">
    <BentoCard 
      title="API Keys" 
      :subtitle="`${keysStore.activeKeys.length} 个活跃密钥`"
      :grid-span="{ colSpan: 1, rowSpan: 1 }"
      variant="elevated"
      decoration="gradient"
    >
      <div class="stat-display">
        <div class="stat-icon keys-icon">
          🔑
        </div>
        <div class="stat-details">
          <div class="stat-number">
            {{ keysStore.activeKeys.length }}
          </div>
          <div class="stat-label">
            活跃密钥
          </div>
          <div class="stat-total">
            总计: {{ keysStore.keys.length }} 个
          </div>
        </div>
      </div>
      <div class="stat-progress">
        <div class="progress-bar">
          <div 
            class="progress-fill" 
            :style="{ width: `${(keysStore.activeKeys.length / Math.max(keysStore.keys.length, 1)) * 100}%` }"
          />
        </div>
      </div>
    </BentoCard>

    <BentoCard 
      title="上下文缓存" 
      :subtitle="`${contextStore.contextCount} 个条目`"
      :grid-span="{ colSpan: 1, rowSpan: 1 }"
      variant="elevated"
      decoration="dots"
    >
      <div class="stat-display">
        <div class="stat-icon context-icon">
          💾
        </div>
        <div class="stat-details">
          <div class="stat-number">
            {{ contextStore.contextCount }}
          </div>
          <div class="stat-label">
            上下文条目
          </div>
          <div class="stat-expired">
            {{ contextStore.expiredContexts.length }} 个已过期
          </div>
        </div>
      </div>
      <div class="stat-chart">
        <div class="chart-bar">
          <div
            class="bar active"
            :style="{ height: `${Math.min(contextStore.contextCount * 2, 100)}%` }"
          />
          <div
            class="bar expired"
            :style="{ height: `${Math.min(contextStore.expiredContexts.length * 5, 100)}%` }"
          />
        </div>
      </div>
    </BentoCard>
  </div>
</template>

<script setup>
import BentoCard from '@/components/common/BentoCard.vue';
import { useKeysStore } from '@/stores/keysStore.js';
import { useContextStore } from '@/stores/contextStore.js';

const keysStore = useKeysStore();
const contextStore = useContextStore();
</script>

<style scoped>
.stats-grid-container {
  display: contents; /* Allow grid items to participate in parent grid */
}

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
</style>
