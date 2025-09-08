<template>
  <div class="manage-keys-view" :class="{ 'bento-layout': appStore.isBentoMode, 'traditional-layout': appStore.isTraditionalLayout }">
    <header class="view-header">
      <h1>API Key 管理</h1>
      <button v-if="appStore.isAdmin" @click="openAddKeyModal" :disabled="isLoading">添加新 Key</button>
    </header>

    <div v-if="isLoading" class="loading-message">加载中...</div>
    <div v-if="!isLoading && error" class="error-message">获取 API Key 数据失败: {{ error }}</div>
    <div v-if="!isLoading && !error && keys.length === 0" class="no-data-message">当前没有配置任何 API Key。请添加一个新的 Key。</div>

    <!-- Bento 视图 (虚拟滚动) -->
    <div v-if="appStore.isBentoMode && !isLoading && !error && keys.length > 0" class="key-list-container bento-grid">
      <VirtualList
        :data-key="'key'"
        :data-sources="keys"
        :data-component="BentoCardWithKeyActions"
        :estimate-size="200"
        :item-class="'bento-card-item'"
        :wrap-class="'bento-grid-virtual-wrap'"
        :extra-props="{ openEditKeyModal: openEditKeyModal, confirmDeleteKey: confirmDeleteKey, isLoading: keyActionLoading, appStore: appStore }"
      >
        <!-- VirtualList 会将每个 item 作为 prop 传递给 data-component -->
      </VirtualList>
    </div>

    <!-- 传统视图 -->
    <div v-if="appStore.isTraditionalMode && !isLoading && !error && keys.length > 0" class="key-list-container traditional-list">
      <table>
        <thead>
          <tr>
            <th>描述</th>
            <th>Key (部分)</th>
            <th>状态</th>
            <th>创建于</th>
            <th>过期于</th>
            <th>上下文补全</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="apiKey in keys" :key="apiKey.key" :class="{ 'inactive-row': !apiKey.is_active }">
            <td>{{ apiKey.description || 'N/A' }}</td>
            <td><code>{{ maskApiKey(apiKey.key) }}</code></td>
            <td>{{ apiKey.is_active ? '激活' : '禁用' }}</td>
            <td>{{ apiKey.created_at || 'N/A' }}</td>
            <td>{{ apiKey.expires_at || '永不' }}</td>
            <td>{{ apiKey.enable_context_completion ? '启用' : '禁用' }}</td>
            <td>
              <div class="key-actions-table">
                <button @click="openEditKeyModal(apiKey)" :disabled="isLoading || !appStore.isAdmin">编辑</button>
                <button @click="confirmDeleteKey(apiKey)" class="delete-button" :disabled="isLoading || !appStore.isAdmin">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 实际的模态框组件 -->
    <AddEditKeyModal
      v-if="showAddEditModal"
      :keyToEdit="selectedKey"
      :adminApiKey="adminApiKeyPlaceholder"
      @close="closeAddEditModal"
      @save="handleKeySave"
      :isLoading="keyActionLoading"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useAppStore } from '@/stores/appStore'; // 导入 appStore
import BentoCard from '@/components/common/BentoCard.vue';
import apiService from '@/services/apiService';
import AddEditKeyModal from '@/components/keys/AddEditKeyModal.vue';
import VirtualList from 'vue-virtual-scroll-list'; // 导入 VirtualList 组件

// API密钥掩码函数
const maskApiKey = (key) => {
  if (!key) return '';
  const visibleChars = 4;
  const maskedLength = Math.max(0, key.length - visibleChars);
  return '*'.repeat(maskedLength) + key.slice(-visibleChars);
};

console.log('[ManageKeysView.vue] <script setup> executed.');

const isLoading = ref(false);
const error = ref(null);
const keys = ref([]);

const showAddEditModal = ref(false);
const selectedKey = ref(null);
const adminApiKeyPlaceholder = ref("your_admin_api_key_here"); // 占位符

const appStore = useAppStore(); // 使用 appStore

// 创建一个包装组件来处理 BentoCard 的 prop 和事件
// 创建一个包装组件来处理 BentoCard 的 prop 和事件
const BentoCardWithKeyActions = {
  props: {
    source: Object, // VirtualList 会将数据项作为 source prop 传递
    openEditKeyModal: Function, // 从父组件传递
    confirmDeleteKey: Function, // 从父组件传递
    isLoading: Boolean, // 从父组件传递
    appStore: Object, // 从父组件传递
  },
  components: {
    BentoCard,
  },
  setup(props) {
    return {
      apiKey: props.source,
      openEditKeyModal: props.openEditKeyModal,
      confirmDeleteKey: props.confirmDeleteKey,
      isLoading: props.isLoading,
      appStore: props.appStore,
    };
  },
  template: `
    <BentoCard
      :title="apiKey.description || maskApiKey(apiKey.key)"
      :gridSpan="{ colSpan: 1, rowSpan: 1 }"
      :class="{ 'inactive-key-card': !apiKey.is_active }"
    >
      <div class="key-details">
        <p><strong>Key:</strong> <code>{{ maskApiKey(apiKey.key) }}</code></p>
        <p><strong>状态:</strong> {{ apiKey.is_active ? '激活' : '禁用' }}</p>
        <p><strong>创建于:</strong> {{ apiKey.created_at || 'N/A' }}</p>
        <p><strong>过期于:</strong> {{ apiKey.expires_at || '永不' }}</p>
        <p><strong>上下文补全:</strong> {{ apiKey.enable_context_completion ? '启用' : '禁用' }}</p>
      </div>
      <template #footer>
        <div class="key-actions">
          <button @click="openEditKeyModal(apiKey)" :disabled="isLoading || !appStore.isAdmin">编辑</button>
          <button @click="confirmDeleteKey(apiKey)" class="delete-button" :disabled="isLoading || !appStore.isAdmin">删除</button>
        </div>
      </template>
    </BentoCard>
  `,
};


// 提取公共逻辑到 useKeyActions composable
const useKeyActions = (fetchKeysCallback, selectedKeyRef, showAddEditModalRef) => { // 接受回调函数和父组件的 ref
  const isLoading = ref(false);
  const error = ref(null);
  const appStore = useAppStore(); // 确保 appStore 在 composable 中可用

  const openEditKeyModal = (apiKey) => {
    selectedKeyRef.value = { ...apiKey };
    showAddEditModalRef.value = true;
  };

  const confirmDeleteKey = async (apiKey) => {
    const confirmed = confirm(`确定要删除 API Key "${apiKey.description || apiKey.key}"吗？此操作无法撤销。`);
    if (confirmed) {
      isLoading.value = true;
      error.value = null;
      try {
        await apiService.deleteKey(apiKey.key);
        // 删除成功后，调用回调函数刷新列表
        if (fetchKeysCallback) {
          fetchKeysCallback();
        }
      } catch (err) {
        console.error(`[ManageKeysView] Failed to delete key ${apiKey.key}:`, err);
        error.value = err.message || err.detail || `删除 Key ${apiKey.key.substring(0,8)}... 失败。`;
         if (typeof err === 'object' && err !== null && err.message) {
          error.value = `错误 ${err.status || ''}: ${err.message}`;
        } else if (typeof err === 'object' && err !== null && err.detail) {
          error.value = `错误 ${err.status || ''}: ${err.detail}`;
        }
      } finally {
        isLoading.value = false;
      }
    }
  };

  return {
    openEditKeyModal,
    confirmDeleteKey,
    isLoading,
    appStore,
  };
};

// 使用 useKeyActions composable，并传入 fetchKeys 作为回调，以及父组件的 selectedKey 和 showAddEditModal
const { openEditKeyModal, confirmDeleteKey, isLoading: keyActionLoading } = useKeyActions(fetchKeys, selectedKey, showAddEditModal);

onMounted(() => {
  fetchKeys();
});

const openAddKeyModal = () => {
  selectedKey.value = null;
  showAddEditModal.value = true;
};

const closeAddEditModal = () => {
  showAddEditModal.value = false;
  fetchKeys(); // 关闭模态框后刷新列表
};

const handleKeySave = () => {
  fetchKeys();
  closeAddEditModal();
};
</script>

<style scoped>
.manage-keys-view {
  padding: 20px;
}

.view-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
}

.view-header h1 {
  font-size: 28px;
  color: #333;
  margin: 0;
}

.view-header button {
  padding: 10px 20px;
  background-color: #007bff;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1em;
  font-weight: 500;
  transition: background-color 0.3s ease, opacity 0.3s ease;
}
.view-header button:hover:not(:disabled) {
  background-color: #0056b3;
}
.view-header button:disabled {
    background-color: #cccccc;
    cursor: not-allowed;
    opacity: 0.7;
}

/* 加载、错误、无数据消息样式 */
.loading-message, .error-message, .no-data-message {
    text-align: center;
    font-size: 1.1em;
    color: #555;
    margin-top: 50px;
}

.error-message {
    color: #dc3545;
}

/* Bento Grid 容器 */
.key-list-container.bento-grid {
  /* display: grid; */ /* VirtualList 会管理布局 */
  /* grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); */
  /* gap: 20px; */
  height: calc(100vh - 200px); /* 设置一个固定高度，以便虚拟滚动生效 */
  overflow-y: auto; /* 允许垂直滚动 */
  padding-right: 10px; /* 防止滚动条遮挡内容 */
}

.bento-grid-virtual-wrap {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
  padding-bottom: 20px; /* 底部留白 */
}

.bento-card-item {
  /* VirtualList 渲染的每个项目的样式 */
  /* 确保 BentoCard 内部的样式不会被 VirtualList 的容器影响 */
}

.inactive-key-card {
  opacity: 0.7;
}

.inactive-key-card .card-title {
  text-decoration: line-through;
  color: #888;
}


.key-details p {
  margin: 0.5rem 0;
  font-size: 1em;
  word-break: break-word;
  color: #555;
}

.key-details strong {
    color: #333;
}

.key-details code {
  background-color: #f8f8f8;
  padding: 5px 8px;
  border-radius: 6px;
  font-family: 'SF Mono', Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  display: inline-block;
  white-space: normal;
  word-break: break-all;
  max-width: 100%;
  overflow-x: auto;
  vertical-align: middle;
}


.key-actions {
  margin-top: 1.5rem;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.key-actions button {
  padding: 8px 15px;
  font-size: 0.9em;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.3s ease, opacity 0.3s ease;
}

.key-actions button:hover:not(:disabled) {
    opacity: 0.9;
}

.key-actions button:disabled {
    background-color: #cccccc;
    cursor: not-allowed;
    opacity: 0.7;
}

.key-actions button:not(.delete-button) {
    background-color: #e9ecef;
    color: #333;
    border: 1px solid #ced4da;
}

.key-actions .delete-button {
  background-color: #dc3545;
  color: white;
  border: none;
}

.key-actions .delete-button:hover:not(:disabled) {
  background-color: #c82333;
}

/* 传统列表样式 */
.key-list-container.traditional-list {
    margin-top: 20px;
    width: 100%;
    overflow-x: auto; /* 确保宽表格可以水平滚动 */
}

.traditional-list table {
    width: 100%;
    border-collapse: collapse; /* 合并边框 */
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1); /* 轻微阴影增加层次感 */
    background-color: #fff;
    border-radius: 6px; /* 轻微圆角 */
    overflow: hidden; /* 配合圆角 */
    border: 1px solid #ddd; /* 添加外边框 */
}

.traditional-list th,
.traditional-list td {
    padding: 12px 15px;
    text-align: left;
    border-bottom: 1px solid #e0e0e0; /* 稍微柔和的分割线 */
    vertical-align: middle; /* 垂直居中对齐单元格内容 */
}

/* 表头样式 */
.traditional-list th {
    background-color: #f7f7f7; /* 更传统的浅灰色背景 */
    font-weight: 600;
    color: #333;
    white-space: nowrap; /* 防止表头换行 */
}

/* 表格主体行悬停效果 */
.traditional-list tbody tr:hover {
    background-color: #f0f8ff; /* 淡蓝色悬停效果 */
}

/* 非活动行样式 */
.traditional-list tbody tr.inactive-row {
    opacity: 0.7; /* 降低透明度 */
    background-color: #fcfcfc; /* 略微不同的背景 */
}
.traditional-list tbody tr.inactive-row td {
    /* text-decoration: line-through; */ /* 删除线可能过多，保留透明度即可 */
    color: #888; /* 灰色文字 */
}
/* 确保非活动行的 code 也变灰 */
.traditional-list tbody tr.inactive-row td code {
    color: #888;
    background-color: #f0f0f0; /* 稍微不同的背景 */
}


/* Key 显示样式 */
.traditional-list td code {
    background-color: #f0f0f0; /* 浅灰色背景 */
    padding: 3px 6px;
    border-radius: 4px;
    font-family: 'SF Mono', Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
    font-size: 0.9em; /* 稍微小一点 */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 180px; /* 调整最大宽度 */
    display: inline-block;
    vertical-align: middle;
    border: 1px solid #e0e0e0; /* 添加细边框 */
}

/* 操作按钮列 */
.traditional-list td:last-child {
    white-space: nowrap; /* 防止操作按钮换行 */
    width: 1%; /* 尝试让其宽度自适应内容 */
}

.key-actions-table {
    display: flex; /* 使用 flex 布局按钮 */
    gap: 8px; /* 按钮间距 */
}

.key-actions-table button {
    padding: 6px 12px; /* 调整内边距 */
    font-size: 0.9em; /* 调整字体大小 */
    border-radius: 5px; /* 调整圆角 */
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease, opacity 0.2s ease;
    border: 1px solid transparent; /* 预留边框位置 */
}

.key-actions-table button:disabled {
    background-color: #e0e0e0;
    border-color: #d0d0d0;
    color: #999;
    cursor: not-allowed;
    opacity: 0.7;
}

/* 编辑按钮 */
.key-actions-table button:not(.delete-button) {
    background-color: #f0f0f0;
    color: #333;
    border-color: #ccc;
}
.key-actions-table button:not(.delete-button):hover:not(:disabled) {
    background-color: #e0e0e0;
    border-color: #bbb;
}

/* 删除按钮 */
.key-actions-table .delete-button {
    background-color: #fde8e8; /* 淡红色背景 */
    color: #c82333; /* 深红色文字 */
    border-color: #f5c6cb; /* 红色边框 */
}
.key-actions-table .delete-button:hover:not(:disabled) {
    background-color: #f8d7da;
    border-color: #f1b0b7;
    color: #a01c28;
}


/* 响应式调整 */
@media (max-width: 768px) {
  .key-list-container.bento-grid {
    grid-template-columns: 1fr; /* Bento Grid 响应式 */
  }
  .view-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 15px;
  }
  /* 在小屏幕上，表格可能需要更多调整，但 overflow-x: auto 已提供基本支持 */
  .traditional-list th,
  .traditional-list td {
      padding: 10px 8px; /* 减小内边距 */
      font-size: 0.9em; /* 减小字体 */
  }
  .traditional-list td code {
       max-width: 100px; /* 进一步减小 Key 显示宽度 */
   }
   .key-actions-table {
       flex-direction: column; /* 在非常小的屏幕上可能需要垂直排列按钮 */
       align-items: flex-start;
       gap: 5px;
   }
   .key-actions-table button {
       width: 100%; /* 让按钮占满宽度 */
       text-align: center;
   }
}

/* 针对 600px 以下的更小屏幕 */
@media (max-width: 600px) {
    .traditional-list th:nth-child(4), /* 隐藏创建日期 */
    .traditional-list td:nth-child(4),
    .traditional-list th:nth-child(5), /* 隐藏过期日期 */
    .traditional-list td:nth-child(5),
    .traditional-list th:nth-child(6), /* 隐藏上下文补全 */
    .traditional-list td:nth-child(6) {
        display: none; /* 在非常小的屏幕上隐藏部分列 */
    }
     .key-actions-table {
       flex-direction: row; /* 改回水平排列，但可能需要换行 */
       flex-wrap: wrap;
       gap: 5px;
   }
    .key-actions-table button {
       width: auto; /* 恢复自动宽度 */
   }
}
</style>
