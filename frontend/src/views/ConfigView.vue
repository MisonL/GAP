<template>
  <div class="config-view">
    <div class="page-header">
      <h1 class="text-2xl font-bold text-gray-900 mb-4">系统配置</h1>
      <p class="text-gray-600 mb-6">查看和管理系统配置参数</p>
    </div>

    <!-- 权限提示 -->
    <div class="bg-blue-50 border-l-4 border-blue-400 p-4 mb-6">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg class="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm text-blue-700">
            <strong>{{ configInfo?.is_admin ? '管理员权限' : '普通用户权限' }}：</strong>
            {{ configInfo?.is_admin ? '您可以查看所有系统配置并修改参数' : '您只能查看全局配置信息，无法修改参数' }}
          </p>
        </div>
      </div>
    </div>

    <!-- 内存模式警告 -->
    <div v-if="configInfo?.is_memory_mode" class="bg-yellow-50 border-l-4 border-yellow-400 p-4 mb-6">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg class="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm text-yellow-700">
            <strong>警告：</strong>当前运行在纯内存模式下，所有配置修改仅在当前会话中有效，重启服务后将恢复原始配置。
          </p>
        </div>
      </div>
    </div>

    <!-- 配置信息卡片 -->
    <div class="bg-white shadow rounded-lg p-6 mb-6">
      <h2 class="text-lg font-semibold text-gray-900 mb-4">当前配置信息</h2>
      
      <div v-if="loading" class="text-center py-8">
        <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        <p class="mt-2 text-gray-600">加载配置信息中...</p>
      </div>

      <div v-else-if="error" class="text-center py-8">
        <div class="text-red-600">
          <svg class="h-12 w-12 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p>{{ error }}</p>
        </div>
      </div>

      <div v-else-if="configInfo" class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <!-- 管理员可见的完整信息 -->
        <template v-if="configInfo.is_admin">
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700">存储模式</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.storage_mode }}</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">密钥存储模式</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.key_storage_mode }}</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">上下文存储模式</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.context_storage_mode }}</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">原生缓存</label>
              <p class="mt-1 text-sm text-gray-900">
                <span :class="configInfo.enable_native_caching ? 'text-green-600' : 'text-red-600'">
                  {{ configInfo.enable_native_caching ? '已启用' : '已禁用' }}
                </span>
              </p>
            </div>
          </div>

          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700">每分钟最大请求数</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.max_requests_per_minute }}</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">每日每IP最大请求数</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.max_requests_per_day_per_ip }}</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">Web UI密码数量</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.web_ui_passwords_count }}</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">Gemini API密钥数量</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.gemini_api_keys_count }}</p>
            </div>
          </div>
        </template>

        <!-- 普通用户可见的简化信息 -->
        <template v-else>
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700">存储模式</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.storage_mode }}</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">每分钟最大请求数</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.max_requests_per_minute }}</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">每日每IP最大请求数</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.max_requests_per_day_per_ip }}</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">原生缓存</label>
              <p class="mt-1 text-sm text-gray-900">
                <span :class="configInfo.enable_native_caching ? 'text-green-600' : 'text-red-600'">
                  {{ configInfo.enable_native_caching ? '已启用' : '已禁用' }}
                </span>
              </p>
            </div>
          </div>

          <!-- 用户自己的key信息 -->
          <div v-if="configInfo.user_key_info" class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700">当前密钥</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.user_key_info.key_string }}</p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">密钥状态</label>
              <p class="mt-1 text-sm text-gray-900">
                <span :class="configInfo.user_key_info.is_active ? 'text-green-600' : 'text-red-600'">
                  {{ configInfo.user_key_info.is_active ? '活跃' : '已禁用' }}
                </span>
              </p>
            </div>
            
            <div>
              <label class="block text-sm font-medium text-gray-700">使用次数</label>
              <p class="mt-1 text-sm text-gray-900">{{ configInfo.user_key_info.usage_count || 0 }}</p>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 配置修改卡片（仅管理员和内存模式） -->
    <div v-if="configInfo?.is_admin && configInfo?.is_memory_mode" class="bg-white shadow rounded-lg p-6">
      <h2 class="text-lg font-semibold text-gray-900 mb-4">临时配置修改</h2>
      
      <form @submit.prevent="updateConfig" class="space-y-4">
        <div>
          <label for="max_requests_per_minute" class="block text-sm font-medium text-gray-700">
            每分钟最大请求数
          </label>
          <input
            type="number"
            id="max_requests_per_minute"
            v-model.number="updateForm.max_requests_per_minute"
            class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
            min="1"
            max="1000"
          />
        </div>

        <div>
          <label for="max_requests_per_day_per_ip" class="block text-sm font-medium text-gray-700">
            每日每IP最大请求数
          </label>
          <input
            type="number"
            id="max_requests_per_day_per_ip"
            v-model.number="updateForm.max_requests_per_day_per_ip"
            class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
            min="1"
            max="10000"
          />
        </div>

        <div>
          <label class="flex items-center">
            <input
              type="checkbox"
              v-model="updateForm.enable_native_caching"
              class="rounded border-gray-300 text-blue-600 shadow-sm focus:border-blue-300 focus:ring focus:ring-blue-200 focus:ring-opacity-50"
            />
            <span class="ml-2 text-sm text-gray-700">启用原生缓存</span>
          </label>
        </div>

        <div class="flex items-center justify-between">
          <p class="text-sm text-gray-500">
            修改仅在当前会话中有效
          </p>
          <button
            type="submit"
            :disabled="updating"
            class="inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
          >
            <span v-if="updating" class="inline-block animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></span>
            {{ updating ? '更新中...' : '更新配置' }}
          </button>
        </div>
      </form>

      <div v-if="updateResult" class="mt-4 p-3 rounded-md" :class="updateResult.success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'">
        {{ updateResult.message }}
      </div>
    </div>

    <!-- 普通用户提示 -->
    <div v-if="!configInfo?.is_admin" class="bg-gray-50 border-l-4 border-gray-400 p-4">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg class="h-5 w-5 text-gray-400" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm text-gray-700">
            您当前使用的是普通用户权限，只能查看全局配置信息，无法修改系统参数。
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import apiService from '@/services/apiService';

const configInfo = ref(null);
const loading = ref(true);
const error = ref(null);
const updating = ref(false);
const updateResult = ref(null);

const updateForm = ref({
  max_requests_per_minute: null,
  max_requests_per_day_per_ip: null,
  enable_native_caching: null
});

const loadConfig = async () => {
  try {
    loading.value = true;
    error.value = null;
    
    const response = await apiService.getConfigInfo();
    configInfo.value = response;
    
    // 初始化更新表单
    updateForm.value = {
      max_requests_per_minute: response.max_requests_per_minute,
      max_requests_per_day_per_ip: response.max_requests_per_day_per_ip,
      enable_native_caching: response.enable_native_caching
    };
  } catch (err) {
    console.error('加载配置失败:', err);
    error.value = err.response?.data?.detail || '加载配置信息失败';
  } finally {
    loading.value = false;
  }
};

const updateConfig = async () => {
  try {
    updating.value = true;
    updateResult.value = null;
    
    const updateData = {};
    if (updateForm.value.max_requests_per_minute !== configInfo.value.max_requests_per_minute) {
      updateData.max_requests_per_minute = updateForm.value.max_requests_per_minute;
    }
    if (updateForm.value.max_requests_per_day_per_ip !== configInfo.value.max_requests_per_day_per_ip) {
      updateData.max_requests_per_day_per_ip = updateForm.value.max_requests_per_day_per_ip;
    }
    if (updateForm.value.enable_native_caching !== configInfo.value.enable_native_caching) {
      updateData.enable_native_caching = updateForm.value.enable_native_caching;
    }
    
    if (Object.keys(updateData).length === 0) {
      updateResult.value = {
        success: true,
        message: '没有需要更新的配置'
      };
      return;
    }
    
    const response = await apiService.updateConfig(updateData);
    updateResult.value = {
      success: true,
      message: response.message
    };
    
    // 重新加载配置
    await loadConfig();
  } catch (err) {
    console.error('更新配置失败:', err);
    updateResult.value = {
      success: false,
      message: err.response?.data?.detail || '更新配置失败'
    };
  } finally {
    updating.value = false;
  }
};

onMounted(() => {
  loadConfig();
});
</script>

<style scoped>
.config-view {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

.page-header {
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 1rem;
  margin-bottom: 2rem;
}
</style>