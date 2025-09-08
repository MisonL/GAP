<template>
  <div class="modal-overlay" @click.self="closeModal">
    <div class="modal-content">
      <h2>{{ isEditMode ? '编辑 API Key' : '添加新 API Key' }}</h2>
      <form @submit.prevent="handleSubmit">
        <div class="form-group" v-if="isEditMode">
          <label>API Key:</label>
          <code>{{ form.key_string }}</code>
        </div>

        <div class="form-group">
          <label for="description">描述:</label>
          <input type="text" id="description" v-model="form.description" />
        </div>

        <div class="form-group">
          <label for="expires_at">过期时间 (YYYY-MM-DDTHH:MM:SSZ 或留空):</label>
          <input type="text" id="expires_at" v-model="form.expires_at" placeholder="例如: 2025-12-31T23:59:59Z" />
          <small>留空表示永不过期。输入 'null' (不区分大小写) 或删除内容以清除已有过期时间。</small>
        </div>

        <div class="form-group checkbox-group" v-if="isEditMode || !isKeyProtected">
          <input type="checkbox" id="is_active" v-model="form.is_active" :disabled="isKeyProtected && isEditMode" />
          <label for="is_active">激活状态</label>
           <small v-if="isKeyProtected && isEditMode">(管理员 Key 不能被禁用)</small>
        </div>
        
        <div class="form-group checkbox-group">
          <input type="checkbox" id="enable_context_completion" v-model="form.enable_context_completion" />
          <label for="enable_context_completion">启用上下文补全</label>
        </div>
<div class="form-group">
          <label>密钥存储模式:</label>
          <span>本地存储 (占位符)</span>
          <small>此提示仅为占位符，实际存储模式可能因后端配置而异。</small>
        </div>

        <div v-if="error" class="error-message">{{ error }}</div>

        <div class="modal-actions">
          <button type="button" @click="closeModal" class="button-cancel">取消</button>
          <button type="submit" :disabled="isSubmitting">
            {{ isSubmitting ? (isEditMode ? '保存中...' : '添加中...') : (isEditMode ? '保存更改' : '添加 Key') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'; // 仅保留 computed，如果 useKeyForm 不再需要，则移除
import { useKeyForm } from '@/composables/useKeyForm'; // 导入 useKeyForm 组合式函数
const props = defineProps({
  keyToEdit: { // 如果提供了这个 prop，则为编辑模式
    type: Object,
    default: null
  },
  // ADMIN_API_KEY 的值，用于判断是否是受保护的 Key
  adminApiKey: {
    type: String,
    default: null
  }
});

const emit = defineEmits(['close', 'save']);

// 使用 useKeyForm 组合式函数
const { form, isSubmitting, error, isEditMode, isKeyProtected, handleSubmit } = useKeyForm(props, emit);

const closeModal = () => {
  emit('close');
};

console.log('[AddEditKeyModal.vue] <script setup> executed.');
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.6);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.modal-content {
  background-color: white;
  padding: 2rem;
  border-radius: 8px;
  box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3);
  width: 90%;
  max-width: 500px;
}

.modal-content h2 {
  margin-top: 0;
  margin-bottom: 1.5rem;
  text-align: center;
}

.form-group {
  margin-bottom: 1rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  font-weight: 500;
}
.form-group code {
  background-color: #f0f0f0;
  padding: 0.2em 0.4em;
  border-radius: 3px;
  font-family: monospace;
}

.form-group input[type="text"],
.form-group input[type="password"] { /* 虽然没用 password type，但保留样式 */
  width: 100%;
  padding: 0.75rem;
  border: 1px solid #ccc;
  border-radius: 4px;
  box-sizing: border-box;
}
.form-group small {
  display: block;
  font-size: 0.8em;
  color: #777;
  margin-top: 0.25rem;
}

.checkbox-group {
  display: flex;
  align-items: center;
}
.checkbox-group input[type="checkbox"] {
  margin-right: 0.5rem;
}
.checkbox-group label {
  margin-bottom: 0; /* 重置 label 的 bottom margin */
  font-weight: normal;
}
.checkbox-group small {
    margin-left: 0.5rem;
}


.error-message {
  color: red;
  margin-bottom: 1rem;
  text-align: center;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
  margin-top: 1.5rem;
}

.modal-actions button {
  padding: 0.75rem 1.5rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 500;
}

.modal-actions .button-cancel {
  background-color: #f0f0f0;
  color: #333;
}
.modal-actions .button-cancel:hover {
  background-color: #e0e0e0;
}

.modal-actions button[type="submit"] {
  background-color: #007bff;
  color: white;
}
.modal-actions button[type="submit"]:hover {
  background-color: #0056b3;
}
.modal-actions button:disabled {
  background-color: #ccc;
  cursor: not-allowed;
}

</style>
