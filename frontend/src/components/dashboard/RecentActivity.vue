<template>
  <BentoCard 
    title="最近活动" 
    subtitle="系统最新动态"
    :grid-span="{ colSpan: 2, rowSpan: 1 }"
    variant="elevated"
  >
    <div class="activity-list">
      <div
        v-for="(activity, index) in activities"
        :key="index"
        class="activity-item"
      >
        <div
          class="activity-icon"
          :class="activity.type"
        >
          {{ activity.icon }}
        </div>
        <div class="activity-content">
          <div class="activity-title">
            {{ activity.title }}
          </div>
          <div class="activity-time">
            {{ activity.time }}
          </div>
        </div>
      </div>
    </div>
  </BentoCard>
</template>

<script setup>
import BentoCard from '@/components/common/BentoCard.vue';

defineProps({
  activities: {
    type: Array,
    default: () => []
  }
});
</script>

<style scoped>
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
</style>
