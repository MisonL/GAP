<template>
  <div class="view-switcher">
    <button
      class="btn btn-sm btn-outline-secondary"
      @click="toggleView"
    >
      切换视图: {{ currentView === 'bento' ? '传统' : 'Bento' }}
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { useAppStore } from '@/stores/appStore';

// 使用 Pinia store
const appStore = useAppStore();

// 获取当前视图模式 (应为 viewMode)
const currentView = computed(() => appStore.viewMode);

// 切换视图模式的方法
const toggleView = () => {
  // 假设 store 中有一个名为 toggleViewMode 的 action
  // 如果没有，我们稍后会在 appStore.js 中添加
  appStore.toggleViewMode();
};
</script>

<style scoped>
.view-switcher {
  /* 根据需要添加样式 */
  margin-left: 1rem; /* 示例：与其他头部元素保持间距 */
}
</style>