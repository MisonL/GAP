<template>
  <div 
    :class="[
      'bento-card',
      `col-span-${gridSpan.colSpan || 1}`,
      `row-span-${gridSpan.rowSpan || 1}`,
      variant
    ]"
    :style="customStyle"
  >
    <div class="card-header" v-if="title || $slots.header">
      <slot name="header">
        <h3 class="card-title">{{ title }}</h3>
        <p v-if="subtitle" class="card-subtitle">{{ subtitle }}</p>
      </slot>
    </div>
    
    <div class="card-content">
      <slot></slot>
    </div>
    
    <div class="card-footer" v-if="$slots.footer">
      <slot name="footer"></slot>
    </div>
    
    <!-- 装饰性元素 -->
    <div class="card-decoration" :class="`decoration-${decoration}`" v-if="decoration">
      <div class="decoration-inner"></div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  title: {
    type: String,
    default: ''
  },
  subtitle: {
    type: String,
    default: ''
  },
  gridSpan: {
    type: Object,
    default: () => ({ colSpan: 1, rowSpan: 1 })
  },
  variant: {
    type: String,
    default: 'default', // default, elevated, outlined, glass
    validator: (value) => ['default', 'elevated', 'outlined', 'glass'].includes(value)
  },
  decoration: {
    type: String,
    default: '', // gradient, dots, waves
    validator: (value) => ['', 'gradient', 'dots', 'waves'].includes(value)
  },
  customStyle: {
    type: Object,
    default: () => ({})
  }
});

const customStyle = computed(() => ({
  ...props.customStyle
}));
</script>

<style scoped>
.bento-card {
  position: relative;
  background: var(--bg-primary);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-xl);
  padding: var(--spacing-lg);
  transition: all var(--transition-normal);
  overflow: hidden;
  backdrop-filter: blur(10px);
}

.bento-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-xl);
}

/* 变体样式 */
.bento-card.elevated {
  box-shadow: var(--shadow-md);
  border: none;
}

.bento-card.outlined {
  background: transparent;
  border: 2px solid var(--gray-300);
}

.bento-card.glass {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.2);
}

/* 网格跨度 */
.col-span-1 { grid-column: span 1; }
.col-span-2 { grid-column: span 2; }
.col-span-3 { grid-column: span 3; }
.col-span-4 { grid-column: span 4; }

.row-span-1 { grid-row: span 1; }
.row-span-2 { grid-row: span 2; }
.row-span-3 { grid-row: span 3; }

.card-header {
  margin-bottom: var(--spacing-md);
}

.card-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--spacing-xs);
}

.card-subtitle {
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin: 0;
}

.card-content {
  flex: 1;
}

.card-footer {
  margin-top: var(--spacing-md);
  padding-top: var(--spacing-md);
  border-top: 1px solid var(--gray-200);
}

/* 装饰性元素 */
.card-decoration {
  position: absolute;
  top: 0;
  right: 0;
  width: 100px;
  height: 100px;
  opacity: 0.1;
  pointer-events: none;
}

.decoration-gradient .decoration-inner {
  background: linear-gradient(135deg, var(--primary), var(--secondary));
  border-radius: 50%;
  width: 100%;
  height: 100%;
  transform: translate(30%, -30%);
}

.decoration-dots .decoration-inner {
  background-image: radial-gradient(circle, var(--primary) 1px, transparent 1px);
  background-size: 10px 10px;
  width: 100%;
  height: 100%;
}

.decoration-waves .decoration-inner {
  background: linear-gradient(45deg, 
    transparent 30%, 
    var(--primary) 30%, 
    var(--primary) 70%, 
    transparent 70%
  );
  background-size: 20px 20px;
  width: 100%;
  height: 100%;
  transform: rotate(45deg);
}

/* 响应式设计 */
@media (max-width: 768px) {
  .bento-card {
    grid-column: span 1 !important;
    grid-row: span 1 !important;
    padding: var(--spacing-md);
  }
  
  .card-title {
    font-size: 1.125rem;
  }
}

/* 深色模式支持 */
[data-theme="dark"] .bento-card {
  background: var(--bg-secondary);
  border-color: var(--gray-700);
}

[data-theme="dark"] .bento-card:hover {
  border-color: var(--gray-600);
}

/* 动画效果 */
.bento-card {
  animation: slideUp 0.5s ease-out;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 悬停效果增强 */
.bento-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, transparent, rgba(99, 102, 241, 0.05));
  opacity: 0;
  transition: opacity var(--transition-normal);
  border-radius: var(--radius-xl);
  pointer-events: none;
}

.bento-card:hover::before {
  opacity: 1;
}
</style>