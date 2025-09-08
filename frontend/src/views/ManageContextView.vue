<template>
  <div class="manage-context-view" :class="{ 'bento-layout': appStore.isBentoMode, 'traditional-layout': appStore.isTraditionalMode }">
    <header class="view-header">
      <h1>上下文管理</h1>
      <!-- 可能有全局 TTL 设置等操作 -->
    </header>

    <!-- 全局 TTL 设置区域 -->
    <div v-if="appStore.isAdmin && !isLoading && !error" class="global-ttl-section" :class="{ 'bento-card': appStore.isBentoMode, 'traditional-section': appStore.isTraditionalMode }">
        <h3>全局上下文 TTL: <span class="ttl-value">{{ globalTTL }}</span> 秒</h3>
        <div class="ttl-input-group">
            <input type="number" v-model.number="newGlobalTTL" placeholder="输入新的 TTL (秒)" min="0" :disabled="!appStore.isAdmin || isLoading"/>
            <button @click="updateGlobalTTL" :disabled="!appStore.isAdmin || isLoading">更新全局 TTL</button>
        </div>
         <p class="storage-mode-info">当前上下文存储模式: <span class="mode-highlight">{{ storageMode }}</span></p>
         <p v-if="storageMode === 'memory'" class="warning-info">注意：内存模式下，应用重启将丢失所有上下文数据。</p>
    </div>

    <div v-if="isLoading" class="loading-message">加载中...</div>
    <div v-if="!isLoading && error" class="error-message">获取上下文数据失败: {{ error }}</div>
    <div v-if="!isLoading && !error && contexts.length === 0" class="no-data-message">当前没有缓存的上下文记录。</div>


    <!-- Bento 视图 (虚拟滚动) -->
    <div v-if="appStore.isBentoMode && !isLoading && !error && contexts.length > 0" class="context-list-container bento-grid">
      <VirtualList
        :data-key="'id'"
        :data-sources="contexts"
        :data-component="BentoCardWithContextActions"
        :estimate-size="200"
        :item-class="'bento-card-item'"
        :wrap-class="'bento-grid-virtual-wrap'"
        :extra-props="{ confirmDeleteContext: confirmDeleteContext, isLoading: contextActionLoading, truncateContent: truncateContent }"
      >
        <!-- VirtualList 会将每个 item 作为 prop 传递给 data-component -->
      </VirtualList>
    </div>

    <!-- 传统视图 -->
    <div v-if="appStore.isTraditionalMode && !isLoading && !error && contexts.length > 0" class="context-list-container traditional-list">
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>用户/Key</th>
                    <th>内容 (部分)</th>
                    <th>创建于</th>
                    <th>TTL (秒)</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
                <tr v-for="contextItem in contexts" :key="contextItem.id">
                    <td>{{ contextItem.id }}</td>
                    <td>{{ contextItem.user_id || '未知' }} - {{ contextItem.context_key }}</td>
                    <td><code>{{ truncateContent(contextItem.context_value, 50) }}</code></td>
                    <td>{{ contextItem.created_at }}</td>
                    <td>{{ contextItem.ttl_seconds }}</td>
                    <td>
                        <button @click="confirmDeleteContext(contextItem)" class="delete-button" :disabled="isLoading">删除</button>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useAppStore } from '@/stores/appStore'; // 导入 appStore
import BentoCard from '@/components/common/BentoCard.vue';
import apiService from '@/services/apiService';
import VirtualList from 'vue-virtual-scroll-list'; // 导入 VirtualList 组件

console.log('[ManageContextView.vue] <script setup> executed.');

const isLoading = ref(false);
const error = ref(null);
const contexts = ref([]);
const globalTTL = ref(0);
const newGlobalTTL = ref(null);
const storageMode = ref('unknown'); // 新增存储模式状态

const appStore = useAppStore(); // 使用 appStore

// 创建一个包装组件来处理 BentoCard 的 prop 和事件
const BentoCardWithContextActions = {
  props: {
    source: Object, // VirtualList 会将数据项作为 source prop 传递
    confirmDeleteContext: Function, // 从父组件传递
    isLoading: Boolean, // 从父组件传递
    truncateContent: Function, // 从父组件传递
  },
  components: {
    BentoCard,
  },
  setup(props) {
    return {
      contextItem: props.source,
      confirmDeleteContext: props.confirmDeleteContext,
      isLoading: props.isLoading,
      truncateContent: props.truncateContent,
    };
  },
  template: `
    <BentoCard
      :title="\`用户: \${contextItem.user_id || '未知'} - \${contextItem.context_key}\`"
      :gridSpan="{ colSpan: 1, rowSpan: 1 }"
    >
      <div class="context-details">
        <p><strong>ID:</strong> {{ contextItem.id }}</p>
        <p><strong>内容 (部分):</strong> <code>{{ truncateContent(contextItem.context_value) }}</code></p>
        <p><strong>创建于:</strong> {{ contextItem.created_at }}</p>
        <p><strong>TTL (秒):</strong> {{ contextItem.ttl_seconds }}</p>
      </div>
      <template #footer>
        <div class="context-actions">
          <button @click="confirmDeleteContext(contextItem)" class="delete-button" :disabled="isLoading">删除</button>
        </div>
      </template>
    </BentoCard>
  `,
};

// 提取公共逻辑到 useContextActions composable
const useContextActions = (fetchContextDataCallback) => { // 接受一个回调函数用于刷新列表
  const isLoading = ref(false);
  const error = ref(null);

  const confirmDeleteContext = async (contextItem) => {
    if (confirm(`确定要删除上下文 ID: ${contextItem.id} (Key: ${contextItem.context_key})吗？`)) {
      console.log(`[ManageContextView] Confirming deletion for context ID: ${contextItem.id}`);
      isLoading.value = true;
      error.value = null;
      try {
        console.log(`[ManageContextView] Deleting context ID: ${contextItem.id}`);
        await apiService.deleteContext(contextItem.id);
        console.log(`[ManageContextView] Context ID ${contextItem.id} deleted successfully.`);
        // 删除成功后，调用回调函数刷新列表
        if (fetchContextDataCallback) {
          fetchContextDataCallback();
        }
      } catch (err) {
        console.error(`[ManageContextView] Failed to delete context ID ${contextItem.id}:`, err);
        error.value = err.message || err.detail || `删除上下文 ID ${contextItem.id} 失败。`;
        if (typeof err === 'object' && err !== null && err.message) {
          error.value = `错误 ${err.status || ''}: ${err.message}`;
        } else if (typeof err === 'object' && err !== null && err.detail) {
          error.value = `错误 ${err.status || ''}: ${err.detail}`;
        }
      } finally {
        isLoading.value = false;
      }
    } else {
      console.log(`[ManageContextView] Deletion cancelled for context ID: ${contextItem.id}`);
    }
  };

  return {
    confirmDeleteContext,
    isLoading,
  };
};

const truncateContent = (content, maxLength = 100) => {
  if (typeof content !== 'string') return '';
  if (content.length <= maxLength) return content;
  return content.substring(0, maxLength) + '...';
};

const fetchContextData = async () => {
  isLoading.value = true;
  error.value = null;
  contexts.value = []; // 清空旧数据
  try {
    console.log('[ManageContextView] Fetching context data from API...');
    const response = await apiService.getContextData();
    if (response && Array.isArray(response.contexts)) {
      contexts.value = response.contexts;
      globalTTL.value = response.global_ttl || 0;
      newGlobalTTL.value = globalTTL.value; // 初始化输入框的值
      storageMode.value = response.storage_mode || 'unknown'; // 获取存储模式
      console.log('[ManageContextView] Context data fetched successfully:', contexts.value.length, 'contexts');
      console.log('[ManageContextView] Storage mode:', storageMode.value);
    } else {
      console.warn('[ManageContextView] API response for context data is empty or not in expected format:', response);
      error.value = '从服务器获取的上下文数据格式不正确。';
    }
  } catch (err) {
    console.error('[ManageContextView] Failed to fetch context data:', err);
    error.value = err.message || err.detail || '获取上下文数据失败。';
    if (typeof err === 'object' && err !== null && err.message) {
        error.value = `错误 ${err.status || ''}: ${err.message}`;
    } else if (typeof err === 'object' && err !== null && err.detail) {
        error.value = `错误 ${err.status || ''}: ${err.detail}`;
    }
  } finally {
    isLoading.value = false;
  }
};

const updateGlobalTTL = async () => {
    if (newGlobalTTL.value === null || newGlobalTTL.value < 0) {
        alert('请输入有效的 TTL 值 (大于等于0)。');
        return;
    }
    isLoading.value = true;
    error.value = null;
    try {
      console.log(`[ManageContextView] Updating global TTL to: ${newGlobalTTL.value}`);
      await apiService.updateContextTTL({ ttl_seconds: newGlobalTTL.value });
      console.log(`[ManageContextView] Global TTL updated successfully.`);
      console.log(`[ManageContextView] Global TTL updated successfully.`);
      // 更新本地状态，然后重新获取数据以确认并刷新列表
      await fetchContextData(); // 重新获取数据以确认并刷新列表
      // 在 fetchContextData 成功后，其内部会更新 globalTTL 和 newGlobalTTL
    } catch (err) {
      console.error('[ManageContextView] Failed to update global TTL:', err);
      error.value = err.message || err.detail || '更新全局 TTL 失败。';
      if (typeof err === 'object' && err !== null && err.message) {
        error.value = `错误 ${err.status || ''}: ${err.message}`;
      } else if (typeof err === 'object' && err !== null && err.detail) {
        error.value = `错误 ${err.status || ''}: ${err.detail}`;
      }
    } finally {
      isLoading.value = false;
    }
};

// 使用 useContextActions composable，并传入 fetchContextData 作为回调
const { confirmDeleteContext, isLoading: contextActionLoading } = useContextActions(fetchContextData);

onMounted(() => {
  fetchContextData();
});
</script>

<style scoped>
.manage-context-view {
  padding: 20px; /* 增加内边距 */
}

.view-header {
  margin-bottom: 30px; /* 增加底部外边距 */
  text-align: center; /* 标题居中 */
}

.view-header h1 {
  font-size: 28px; /* 调整标题大小 */
  color: #333;
}

/* 全局 TTL 设置区域样式 */
.global-ttl-section {
    margin-top: 30px; /* 增加顶部外边距 */
    padding: 20px; /* 调整内边距 */
}

.global-ttl-section.bento-card {
    /* 继承 BentoCard 的样式 */
    background-color: rgba(255, 255, 255, 0.7);
    border-radius: 12px;
    box-shadow: 0 8px 16px rgba(0, 0, 0, 0.1);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.18);
}

/* 传统视图下的全局 TTL 设置区域 */
.traditional-layout .global-ttl-section.traditional-section {
    background-color: #f9f9f9; /* 淡灰色背景 */
    border: 1px solid #e0e0e0; /* 细边框 */
    border-radius: 8px; /* 轻微圆角 */
    padding: 20px;
    margin-bottom: 20px; /* 与下方表格的间距 */
    box-shadow: none; /* 移除阴影 */
    backdrop-filter: none; /* 移除模糊效果 */
    -webkit-backdrop-filter: none;
}

/* 确保传统视图下标题和输入组样式协调 */
.traditional-layout .global-ttl-section.traditional-section h3 {
    color: #333;
    margin-bottom: 15px;
}

/* .traditional-layout .global-ttl-section.traditional-section .ttl-input-group { */
    /* 样式可能与 Bento 模式下相同，无需额外修改 */
/* } */

.traditional-layout .global-ttl-section.traditional-section input[type="number"] {
     /* 样式可能与 Bento 模式下相同，无需额外修改 */
     background-color: #fff; /* 确保输入框背景为白色 */
}

/* .traditional-layout .global-ttl-section.traditional-section button { */
     /* 样式可能与 Bento 模式下相同，无需额外修改 */
/* } */

.traditional-layout .global-ttl-section.traditional-section .storage-mode-info,
.traditional-layout .global-ttl-section.traditional-section .warning-info {
     /* 样式可能与 Bento 模式下相同，无需额外修改 */
     color: #555; /* 确保颜色合适 */
}
.traditional-layout .global-ttl-section.traditional-section .warning-info {
    color: #dc3545; /* 保持警告颜色 */
}


.global-ttl-section h3 {
    margin-top: 0;
    margin-bottom: 15px;
    font-size: 1.2rem;
    color: #333;
}

.global-ttl-section .ttl-value {
    font-weight: 600;
    color: #007bff; /* 蓝色高亮 */
}

.global-ttl-section .ttl-input-group {
    display: flex;
    gap: 10px; /* 输入框和按钮间距 */
    align-items: center;
    margin-bottom: 15px;
}

.global-ttl-section input[type="number"] {
    flex-grow: 1; /* 输入框占据剩余空间 */
    padding: 10px 12px; /* 调整内边距 */
    border: 1px solid #ccc;
    border-radius: 8px; /* 圆角 */
    font-size: 1em;
    box-sizing: border-box;
}

.global-ttl-section button {
    padding: 10px 20px; /* 调整内边距 */
    background-color: #007bff;
    color: white;
    border: none;
    border-radius: 8px; /* 圆角 */
    cursor: pointer;
    font-size: 1em;
    transition: background-color 0.3s ease, opacity 0.3s ease;
}

.global-ttl-section button:hover:not(:disabled) {
    background-color: #0056b3;
}

.global-ttl-section button:disabled {
    background-color: #cccccc;
    cursor: not-allowed;
    opacity: 0.7;
}

.global-ttl-section .storage-mode-info {
    font-size: 0.9em;
    color: #555;
    margin-bottom: 10px;
}

.global-ttl-section .mode-highlight {
    font-weight: 600;
    color: #007bff; /* 蓝色高亮 */
}

.global-ttl-section .warning-info {
    font-size: 0.9em;
    color: #dc3545; /* 红色警告 */
    font-weight: 500;
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
.context-list-container.bento-grid {
  /* display: grid; */ /* VirtualList 会管理布局 */
  /* grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); */
  /* gap: 20px; */
  height: calc(100vh - 200px); /* 设置一个固定高度，以便虚拟滚动生效 */
  overflow-y: auto; /* 允许垂直滚动 */
  padding-right: 10px; /* 防止滚动条遮挡内容 */
  margin-top: 20px; /* 与上方元素的间距 */
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

/* 上下文详情样式 */
.context-details p {
  margin: 0.5rem 0; /* 调整段落间距 */
  font-size: 1em; /* 调整字体大小 */
  word-break: break-word; /* 允许长单词换行 */
  color: #555;
}

.context-details strong {
    color: #333;
}

.context-details code {
  background-color: #f8f8f8; /* 柔和背景色 */
  padding: 5px 8px; /* 调整内边距 */
  border-radius: 6px; /* 圆角 */
  font-family: 'SF Mono', Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; /* 更好的等宽字体 */
  display: block;
  white-space: pre-wrap;
  max-height: 150px; /* 增加代码块高度 */
  overflow-y: auto; /* 超出则滚动 */
  margin-top: 10px;
  border: 1px solid #eee;
}

/* 操作按钮容器 */
.context-actions {
  margin-top: 1.5rem; /* 增加顶部外边距 */
  text-align: right;
}

.context-actions button {
    padding: 8px 15px; /* 调整内边距 */
    border-radius: 8px; /* 圆角 */
    cursor: pointer;
    font-size: 0.9em;
    transition: background-color 0.3s ease, opacity 0.3s ease;
}

.context-actions button.delete-button {
  background-color: #dc3545; /* 红色 */
  color: white;
  border: none;
}

.context-actions button.delete-button:hover:not(:disabled) {
  background-color: #c82333;
}

.context-actions button:disabled {
    background-color: #cccccc;
    cursor: not-allowed;
    opacity: 0.7;
}


/* 传统列表样式 */
/* 应用 .traditional-layout 前缀以提高特异性，并调整与上方元素的间距 */
.traditional-layout .context-list-container.traditional-list {
    margin-top: 0; /* global-ttl-section 已有 margin-bottom */
    width: 100%;
    overflow-x: auto; /* 如果表格太宽，允许滚动 */
}

.traditional-list table {
    width: 100%;
    border-collapse: collapse; /* 合并边框 */
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1); /* 柔和阴影 */
    background-color: #fff; /* 白色背景 */
    border-radius: 8px; /* 圆角 */
    overflow: hidden; /* 隐藏超出圆角的部分 */
}

.traditional-list th,
.traditional-list td {
    padding: 12px 15px; /* 单元格内边距 */
    text-align: left;
    border-bottom: 1px solid #ddd; /* 底部边框 */
}

.traditional-list th {
    background-color: #f2f2f2; /* 头部背景色 */
    font-weight: 600;
    color: #333;
}

.traditional-list tbody tr:hover {
    background-color: #f9f9f9; /* 行悬停背景色 */
}

.traditional-list td code {
    background-color: #f8f8f8;
    padding: 2px 4px;
    border-radius: 3px;
    font-family: 'SF Mono', Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
    white-space: nowrap; /* 不换行 */
    overflow: hidden;
    text-overflow: ellipsis; /* 超出显示省略号 */
    max-width: 200px; /* 限制代码块宽度 */
    display: inline-block; /* 允许设置宽度 */
    vertical-align: middle;
}

.traditional-list td button {
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.9em;
    transition: background-color 0.3s ease, opacity 0.3s ease;
}

.traditional-list td button.delete-button {
    background-color: #dc3545;
    color: white;
    border: none;
}

.traditional-list td button.delete-button:hover:not(:disabled) {
    background-color: #c82333;
}

.traditional-list td button:disabled {
    background-color: #cccccc;
    cursor: not-allowed;
    opacity: 0.7;
}


/* 响应式调整 */
@media (max-width: 768px) {
  .context-list-container.bento-grid {
    grid-template-columns: 1fr; /* 小屏幕下改为单列 */
  }
  .global-ttl-section .ttl-input-group {
      flex-direction: column; /* 小屏幕下垂直排列 */
      gap: 10px;
  }
   .global-ttl-section input[type="number"],
   .global-ttl-section button {
       width: 100%; /* 小屏幕下宽度100% */
   }

   .traditional-list td {
       /* 小屏幕下调整表格单元格内边距 */
       padding: 8px 10px;
   }
   .traditional-list td code {
       max-width: 150px; /* 小屏幕下调整代码块宽度 */
   }
}
</style>
