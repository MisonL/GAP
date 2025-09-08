<template>
  <div class="traditional-list-view">
    <h2>传统列表视图</h2>
    <p v-if="isEmpty" data-testid="empty-data-message">目前没有数据可显示。</p>
    <div v-else class="list-container" data-testid="traditional-list-container">
      <ul role="list">
        <li v-for="item in items" :key="item.id" role="listitem">{{ item.name }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';

const props = defineProps({
  items: {
    type: Array,
    default: () => [
      { id: 1, name: '列表项 1' },
      { id: 2, name: '列表项 2' },
      { id: 3, name: '列表项 3' },
      { id: 4, name: '列表项 4' },
      { id: 5, name: '列表项 5' },
    ],
  },
});

const isEmpty = ref(props.items.length === 0);

// 监听 items 属性的变化，更新 isEmpty 状态
watch(() => props.items, (newItems) => {
  isEmpty.value = newItems.length === 0;
}, { immediate: true });
</script>

<style scoped>
.traditional-list-view {
  padding: 20px;
  border: 1px solid #ccc;
  border-radius: 8px;
  background-color: #f9f9f9;
}

.list-container {
  margin-top: 15px;
}

ul {
  list-style-type: none;
  padding: 0;
}

li {
  background-color: #fff;
  border: 1px solid #eee;
  padding: 10px;
  margin-bottom: 5px;
  border-radius: 4px;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .traditional-list-view {
    padding: 15px;
  }

  h2 {
    font-size: 1.8rem;
  }
}

@media (max-width: 480px) {
  .traditional-list-view {
    padding: 10px;
  }

  h2 {
    font-size: 1.5rem;
  }

  li {
    padding: 8px;
    font-size: 0.9em;
  }
}
</style>