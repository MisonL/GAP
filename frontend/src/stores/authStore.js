import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import apiService from '../services/apiService'; // 导入 apiService

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('authToken') || null);
  
  // 添加isAuthenticated计算属性
  const isAuthenticated = computed(() => !!token.value);
  
  // 初始化时检查token有效性
  const checkTokenValidity = async () => {
    if (!token.value) return false;
    try {
      // 假设 apiService 有 verifyToken 方法，用于验证 token
      await apiService.verifyToken(token.value);
      return true;
    } catch (error) {
      console.error('Token 有效性检查失败:', error); // 添加错误日志
      logout(); // 如果 token 无效，则执行登出操作
      return false;
    }
  };
  
  // 在创建store时检查token
  checkTokenValidity();
  
  const login = async (credentials) => {
    const response = await apiService.login(credentials);
    token.value = response.token;
    localStorage.setItem('authToken', response.token);
  };
  
  const logout = () => {
    token.value = null;
    localStorage.removeItem('authToken');
  };
  
  return { token, isAuthenticated, login, logout };
});
