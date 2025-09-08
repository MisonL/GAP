// app/frontend/src/composables/useKeyForm.ts
import { ref, watch, computed } from 'vue';
import apiService from '@/services/apiService'; // 引入 apiService

// 定义本地类型接口（替代 global.d.ts 导入）
interface KeyItem {
  key_string: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
  usage_count: number;
  description?: string; // 添加 description 属性
  expires_at?: string | null; // 添加 expires_at 属性
  enable_context_completion?: boolean; // 添加 enable_context_completion 属性
}

interface AddKeyPayload {
  key_string?: string; // key_string 在添加时是可选的
  is_active?: boolean;
  description?: string;
  expires_at?: string | null;
  enable_context_completion?: boolean;
}

interface UpdateKeyPayload {
  is_active?: boolean;
  description?: string;
  expires_at?: string | null;
  enable_context_completion?: boolean;
}

interface KeyForm {
  key_string: string;
  description: string;
  expires_at: string | null;
  is_active: boolean;
  enable_context_completion: boolean;
}

interface UseKeyFormProps {
  keyToEdit?: KeyItem | null;
  adminApiKey?: string;
}

/**
 * 组合式函数，用于管理 API Key 的添加和编辑表单逻辑。
 * @param {UseKeyFormProps} props - 传入的 props，包含 keyToEdit 和 adminApiKey。
 * @param {Function} emit - Vue 组件的 emit 函数。
 * @returns {Object} 包含表单状态、提交函数和相关计算属性的对象。
 */
export function useKeyForm(props: UseKeyFormProps, emit: Function) {
  const isEditMode = computed<boolean>(() => !!props.keyToEdit);
  const isKeyProtected = computed<boolean>(() => !!props.keyToEdit && props.keyToEdit.key_string === props.adminApiKey);

  const form = ref<KeyForm>({
    key_string: '', // 仅在编辑模式下显示
    description: '',
    expires_at: '', // ISO 格式字符串或空
    is_active: true,
    enable_context_completion: true,
  });

  const isSubmitting = ref<boolean>(false);
  const error = ref<string | null>(null); // 明确 error 的类型

  // 当 keyToEdit prop 变化时 (例如打开编辑模态框)，初始化表单
  watch(() => props.keyToEdit, (newVal) => {
    if (newVal) {
      form.value.key_string = newVal.key_string || ''; // 兼容不同属性名
      form.value.description = newVal.description || '';
      form.value.expires_at = newVal.expires_at || '';
      form.value.is_active = newVal.is_active === undefined ? true : newVal.is_active;
      form.value.enable_context_completion = newVal.enable_context_completion === undefined ? true : newVal.enable_context_completion;
    } else {
      // 添加模式，重置表单
      form.value.key_string = '';
      form.value.description = '';
      form.value.expires_at = '';
      form.value.is_active = true;
      form.value.enable_context_completion = true;
    }
    error.value = null; // 清除旧错误
  }, { immediate: true });

  const handleSubmit = async () => {
    isSubmitting.value = true;
    error.value = null;

    // 确保在编辑模式下有有效的 keyToEdit
    if (isEditMode.value && !props.keyToEdit) {
      error.value = '无效的编辑对象';
      isSubmitting.value = false;
      return;
    }

    let payload: AddKeyPayload | UpdateKeyPayload = { // 明确 payload 类型
      description: form.value.description,
      expires_at: form.value.expires_at === '' || form.value.expires_at?.toLowerCase() === 'null' ? null : form.value.expires_at,
      enable_context_completion: form.value.enable_context_completion,
    };

    if (isEditMode.value) {
      if (isKeyProtected.value) {
        const protectedPayload: UpdateKeyPayload = { // 明确 protectedPayload 类型
          description: form.value.description,
          enable_context_completion: form.value.enable_context_completion,
        };
        payload = protectedPayload;
      } else {
        (payload as UpdateKeyPayload).is_active = form.value.is_active; // 类型断言
      }
      try {
        console.log('[useKeyForm] Submitting update for key:', form.value.key_string, 'Payload:', payload);
        await apiService.updateKey(form.value.key_string, payload as UpdateKeyPayload); // 类型断言
        console.log('[useKeyForm] Update successful.');
        emit('save'); // 通知父组件保存成功
      } catch (err: any) { // 明确 err 类型
        console.error('[useKeyForm] 更新 Key 失败:', err);
        error.value = err.message || err.detail || '更新 Key 失败。';
        if (typeof err === 'object' && err !== null && err.message) {
          error.value = `错误 ${err.status || ''}: ${err.message}`;
        } else if (typeof err === 'object' && err !== null && err.detail) {
          error.value = `错误 ${err.status || ''}: ${err.detail}`;
        }
      }
    } else {
      // 添加模式
      try {
        console.log('[useKeyForm] Submitting new key. Payload:', payload);
        await apiService.addKey(payload as AddKeyPayload); // 类型断言
        console.log('[useKeyForm] Add successful.');
        emit('save'); // 通知父组件保存成功
      } catch (err: any) { // 明确 err 类型
        console.error('[useKeyForm] 添加 Key 失败:', err);
        error.value = err.message || err.detail || '添加 Key 失败。';
        if (typeof err === 'object' && err !== null && err.message) {
          error.value = `错误 ${err.status || ''}: ${err.message}`;
        } else if (typeof err === 'object' && err !== null && err.detail) {
          error.value = `错误 ${err.status || ''}: ${err.detail}`;
        }
      }
    }
    isSubmitting.value = false;
  };

  return {
    form,
    isSubmitting,
    error,
    isEditMode,
    isKeyProtected,
    handleSubmit,
  };
}