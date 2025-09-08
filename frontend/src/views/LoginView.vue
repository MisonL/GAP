<template>
  <div class="login-view">
    <h2>API密钥登录</h2>
    <form @submit.prevent="handleLogin">
      <div class="form-group">
        <label for="apiKey">API密钥:</label>
        <input 
          type="password" 
          id="apiKey" 
          v-model="apiKey" 
          placeholder="请输入您的Gemini API密钥"
          required 
          autocomplete="off"
        />
        <div v-if="apiKey" class="key-preview">
          密钥预览: {{ maskApiKey(apiKey) }}
        </div>
      </div>
      <div v-if="error" class="error-message">{{ error }}</div>
      <button type="submit" :disabled="isLoading || !apiKey.trim()">
        {{ isLoading ? '登录中...' : '登录' }}
      </button>
    </form>
  </div>
</template>

<script setup>
console.log('[LoginView.vue] <script setup> executed.');
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/authStore.js';
import apiService from '@/services/apiService';

const apiKey = ref('');
const isLoading = ref(false);
const error = ref(null);

const router = useRouter();
const authStore = useAuthStore();

// API密钥掩码函数
const maskApiKey = (key) => {
  if (!key) return '';
  const visibleChars = 4;
  const maskedLength = Math.max(0, key.length - visibleChars);
  return '*'.repeat(maskedLength) + key.slice(-visibleChars);
};

const handleLogin = async () => {
  console.log('[LoginView] handleLogin triggered.');
  isLoading.value = true;
  error.value = null;
  try {
    const key = apiKey.value.trim();
    if (!key) {
      throw new Error('请输入API密钥');
    }
    
    console.log('[LoginView] Attempting login with API Key:', maskApiKey(key));
    
    // 发送表单数据，只使用 password 字段作为 API Key
      const response = await apiService.login({ password: key });
    
    console.log('[LoginView] Login API response:', response);
    
    if (response && response.token) {
      authStore.login(response.token);
      console.log('[LoginView] authStore.login called with token.');

      // 登录成功后跳转到之前的目标页面或首页
      const redirectPath = router.currentRoute.value.query.redirect || '/';
      router.replace(redirectPath);
      console.log(`[LoginView] Navigating to: ${redirectPath}`);
    } else {
      throw new Error('登录响应格式错误');
    }

  } catch (err) {
    console.error('[LoginView] Login failed:', err);
    
    // 更好的错误处理
    if (err.status === 422) {
      error.value = '请输入有效的API密钥';
    } else if (err.status === 401) {
      error.value = 'API密钥无效，请检查后重试';
    } else if (err.message) {
      error.value = err.message;
    } else if (err.detail) {
      error.value = `错误 ${err.status || ''}: ${err.detail}`;
    } else {
      error.value = '登录失败，请检查网络连接或API密钥';
    }
  } finally {
    isLoading.value = false;
  }
};</script>

<style scoped>
/* 登录视图容器 - Bento 风格卡片 */
.login-view {
  max-width: 400px;
  margin: 80px auto; /* 增加顶部外边距 */
  padding: 30px; /* 增加内边距 */
  background-color: rgba(255, 255, 255, 0.8); /* 半透明背景 */
  border-radius: 20px; /* 更大的圆角 */
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1); /* 更柔和的阴影 */
  backdrop-filter: blur(10px); /* 毛玻璃效果 */
  border: 1px solid rgba(255, 255, 255, 0.3); /* 柔和边框 */
  color: #333; /* 默认文本颜色 */
}

/* 标题样式 */
h2 {
  text-align: center;
  margin-bottom: 30px; /* 增加底部外边距 */
  color: #1a1a1a; /* 深色标题 */
  font-size: 24px;
  font-weight: 600;
}

/* 表单组 */
.form-group {
  margin-bottom: 25px;
}

.form-group label {
  display: block;
  margin-bottom: 10px;
  font-weight: 600;
  color: #333;
  font-size: 1.1em;
}

.form-group input {
  width: 100%;
  padding: 15px 18px;
  border: 2px solid #e0e0e0;
  border-radius: 12px;
  box-sizing: border-box;
  font-size: 16px;
  transition: all 0.3s ease;
  background-color: rgba(255, 255, 255, 0.9);
}

.form-group input:focus {
  outline: none;
  border-color: #007bff;
  box-shadow: 0 0 0 3px rgba(0, 123, 255, 0.1);
  background-color: white;
}

.form-group input::placeholder {
  color: #999;
  font-style: italic;
}

/* 错误消息样式 */
.error-message {
  color: #dc3545; /* 红色 */
  background-color: #f8d7da; /* 柔和背景色 */
  border: 1px solid #f5c6cb;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 20px;
  text-align: center;
  font-size: 0.9em;
  font-weight: 500;
  animation: shake 0.3s ease-in-out;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-5px); }
  75% { transform: translateX(5px); }
}

/* 密钥预览样式 */
.key-preview {
  margin-top: 8px;
  padding: 8px 12px;
  background-color: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 6px;
  font-family: 'Courier New', monospace;
  font-size: 0.85em;
  color: #495057;
  word-break: break-all;
}

/* 按钮样式 */
button {
  width: 100%;
  padding: 12px; /* 调整内边距 */
  background-color: #007bff; /* 主题蓝色 */
  color: white;
  border: none;
  border-radius: 10px; /* 圆角 */
  cursor: pointer;
  font-size: 18px; /* 字体大小 */
  font-weight: 600;
  transition: background-color 0.3s ease, opacity 0.3s ease;
}

button:hover:not(:disabled) {
  background-color: #0056b3; /* 悬停颜色 */
}

button:disabled {
  background-color: #cccccc; /* 禁用颜色 */
  cursor: not-allowed;
  opacity: 0.7;
}
</style>
