<template>
  <BentoCard 
    title="快速操作" 
    subtitle="常用功能快捷入口"
    :grid-span="{ colSpan: 2, rowSpan: 1 }"
    variant="elevated"
  >
    <div class="quick-actions">
      <button
        class="action-card keys"
        @click="$emit('navigate', 'keys')"
      >
        <div class="action-icon">
          🔑
        </div>
        <div class="action-content">
          <h4>管理Keys</h4>
          <p>添加、编辑和删除API密钥</p>
        </div>
      </button>
      
      <button
        class="action-card context"
        @click="$emit('navigate', 'context')"
      >
        <div class="action-icon">
          💾
        </div>
        <div class="action-content">
          <h4>管理上下文</h4>
          <p>查看和管理对话缓存</p>
        </div>
      </button>
      
      <button
        class="action-card report"
        @click="$emit('navigate', 'report')"
      >
        <div class="action-icon">
          📊
        </div>
        <div class="action-content">
          <h4>查看报告</h4>
          <p>查看使用统计和分析</p>
        </div>
      </button>
      
      <button
        class="action-card refresh"
        @click="$emit('refresh')"
      >
        <div class="action-icon">
          🔄
        </div>
        <div class="action-content">
          <h4>刷新数据</h4>
          <p>更新所有系统信息</p>
        </div>
      </button>
    </div>
  </BentoCard>
</template>

<script setup>
import BentoCard from '@/components/common/BentoCard.vue';

defineEmits(['navigate', 'refresh']);
</script>

<style scoped>
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
</style>
