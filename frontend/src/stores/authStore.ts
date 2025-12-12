import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import apiService from '../services/apiService';
import type { LoginCredentials, LoginResponse } from '../services/apiService';
import type { ApiError } from './types/index';

export interface User {
  id: string;
  username?: string;
  email?: string;
  role?: 'user' | 'admin';
  createdAt?: string;
  lastLoginAt?: string;
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('authToken'));
  const user = ref<User | null>(null);

  // 计算属性：是否已认证
  const isAuthenticated = computed(() => !!token.value);

  // 检查Token有效性
  const checkTokenValidity = async (): Promise<boolean> => {
    if (!token.value) {
      return false;
    }

    try {
      const response = await apiService.verifyToken(token.value);
      user.value = response.user || {
        id: 'unknown',
        username: 'unknown'
      };
      return true;
    } catch (error) {
      console.error('Token 有效性检查失败:', error);
      logout();
      return false;
    }
  };

  // 登录功能
  const login = async (credentials: LoginCredentials): Promise<void> => {
    try {
      const response: LoginResponse = await apiService.login(credentials);

      if (!response.token) {
        throw new Error('登录响应中缺少token');
      }

      token.value = response.token;
      user.value = response.user || null;

      // 持久化token
      localStorage.setItem('authToken', response.token);

      console.log('用户登录成功:', user.value?.username || '未知用户');
    } catch (error) {
      const apiError = error as ApiError;
      console.error('登录失败:', apiError.message || error);
      logout(); // 登录失败时确保清理状态
      throw apiError;
    }
  };

  // 登出功能
  const logout = async (): Promise<void> => {
    const currentToken = token.value;

    try {
      // 先清理本地状态
      token.value = null;
      user.value = null;
      localStorage.removeItem('authToken');

      // 可选：调用服务端的登出接口（使用清理前的token）
      if (currentToken) {
        try {
          await apiService.logout();
        } catch (error) {
          console.warn('服务端登出请求失败:', error);
          // 服务端登出失败不影响本地状态清理
        }
      }

      console.log('用户已登出');
    } catch (error) {
      console.error('登出时发生错误:', error);
      // 即使出错也要确保清理本地状态
      token.value = null;
      user.value = null;
      localStorage.removeItem('authToken');
    }
  };

  // 刷新Token（如果JWT过期）
  const refreshToken = async (): Promise<void> => {
    if (!token.value) {
      throw new Error('无法刷新token：当前无有效token');
    }

    try {
      const response = await apiService.refreshToken(token.value);
      token.value = response.token;
      user.value = response.user || null;

      localStorage.setItem('authToken', response.token);
    } catch (error) {
      console.error('Token刷新失败:', error);
      logout();
      throw error;
    }
  };

  // 更新用户资料
  const updateProfile = async (profileData: Partial<User>): Promise<void> => {
    if (!token.value) {
      throw new Error('用户未登录，无法更新资料');
    }

    try {
      const updatedUser = await apiService.updateProfile(profileData);
      user.value = { ...user.value, ...updatedUser };
    } catch (error) {
      console.error('更新用户资料失败:', error);
      throw error;
    }
  };

  // 初始化时检查token
  (async (): Promise<void> => {
    if (token.value) {
      try {
        await checkTokenValidity();
      } catch (error) {
        console.warn('初始化token检查失败:', error);
        logout();
      }
    }
  })();

  return {
    token,
    user,
    isAuthenticated,
    login,
    logout,
    checkTokenValidity,
    refreshToken,
    updateProfile
  };
});