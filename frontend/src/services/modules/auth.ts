import http from '../http';
import type { ApiResponse, LoginCredentials, LoginResponse, TokenVerifyResponse, UserProfileUpdate, User } from '../../stores/types';

// HTTP错误类型
interface HttpErrorResponse {
  response?: {
    data?: {
      message?: string;
    };
  };
  message?: string;
}

// 用户数据类型
export type UserData = User;

// 登录接口
export const login = async (credentials: LoginCredentials): Promise<LoginResponse> => {
  try {
    const response = await http.post<ApiResponse<LoginResponse>>('/api/auth/login', credentials);

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '登录失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '登录请求失败');
  }
};

// 登出接口
export const logout = async (): Promise<void> => {
  try {
    await http.post<ApiResponse>('/api/auth/logout');
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    // 登出失败也不抛出错误，只记录警告
    console.warn('服务端登出失败:', httpError.response?.data?.message || httpError.message);
  }
};

// 验证Token
export const verifyToken = async (token: string): Promise<TokenVerifyResponse> => {
  try {
    const response = await http.post<ApiResponse<TokenVerifyResponse>>('/api/auth/verify', { token });

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || 'Token验证失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || 'Token验证失败');
  }
};

// 刷新Token
export const refreshToken = async (currentToken: string): Promise<LoginResponse> => {
  try {
    const response = await http.post<ApiResponse<LoginResponse>>('/api/auth/refresh', {
      token: currentToken
    });

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || 'Token刷新失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || 'Token刷新失败');
  }
};

// 获取当前用户信息
export const getCurrentUser = async (): Promise<UserData> => {
  try {
    const response = await http.get<ApiResponse<UserData>>('/api/auth/me');

    if (!response.data.success || !response.data.data) {
      throw new Error((response.data as any)?.message || '获取用户信息失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '获取用户信息失败');
  }
};

// 更新用户资料
export const updateProfile = async (profileData: UserProfileUpdate): Promise<UserData> => {
  try {
    const response = await http.put<ApiResponse<UserData>>('/api/auth/profile', profileData);

    if (!response.data.success || !response.data.data) {
      throw new Error((response.data as any)?.message || '更新资料失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '更新资料失败');
  }
};

// 修改密码
export const changePassword = async (passwordData: {
  currentPassword: string;
  newPassword: string;
}): Promise<void> => {
  try {
    const response = await http.put<ApiResponse>('/api/auth/password', passwordData);

    if (!response.data.success) {
      throw new Error(response.data.message || '修改密码失败');
    }
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '修改密码失败');
  }
};

// 重置密码请求
export const requestPasswordReset = async (email: string): Promise<void> => {
  try {
    const response = await http.post<ApiResponse>('/api/auth/reset-password-request', { email });

    if (!response.data.success) {
      throw new Error(response.data.message || '发送重置邮件失败');
    }
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '发送重置邮件失败');
  }
};

// 重置密码
export const resetPassword = async (resetData: {
  token: string;
  newPassword: string;
}): Promise<void> => {
  try {
    const response = await http.post<ApiResponse>('/api/auth/reset-password', resetData);

    if (!response.data.success) {
      throw new Error(response.data.message || '重置密码失败');
    }
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '重置密码失败');
  }
};

// 验证邮箱
export const verifyEmail = async (token: string): Promise<void> => {
  try {
    const response = await http.post<ApiResponse>('/api/auth/verify-email', { token });

    if (!response.data.success) {
      throw new Error(response.data.message || '邮箱验证失败');
    }
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '邮箱验证失败');
  }
};

// 检查用户名是否存在
export const checkUsernameAvailability = async (username: string): Promise<boolean> => {
  try {
    const response = await http.get<ApiResponse<{ available: boolean }>>(
      `/api/auth/check-username?username=${encodeURIComponent(username)}`
    );

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '检查用户名失败');
    }

    return response.data.data.available;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '检查用户名失败');
  }
};

// 检查邮箱是否存在
export const checkEmailAvailability = async (email: string): Promise<boolean> => {
  try {
    const response = await http.get<ApiResponse<{ available: boolean }>>(
      `/api/auth/check-email?email=${encodeURIComponent(email)}`
    );

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '检查邮箱失败');
    }

    return response.data.data.available;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '检查邮箱失败');
  }
};