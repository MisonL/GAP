import http from '../http';
import type { ApiResponse, PaginatedResponse, ApiKeyData, ApiKeyStats, ApiKeyCreateRequest, ApiKeyUpdateRequest } from '../../stores/types';

// HTTP错误类型
interface HttpErrorResponse {
  response?: {
    data?: {
      message?: string;
    };
  };
  message?: string;
}

// 获取API密钥列表
export const getKeys = async (params?: {
  page?: number;
  limit?: number;
  provider?: string;
  status?: string;
}): Promise<PaginatedResponse<ApiKeyData>> => {
  try {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    if (params?.provider) queryParams.append('provider', params.provider);
    if (params?.status) queryParams.append('status', params.status);

    const url = queryParams.toString()
      ? `/api/keys?${queryParams}`
      : '/api/keys';

    const response = await http.get<PaginatedResponse<ApiKeyData>>(url);

    if (!response.data.success) {
      throw new Error((response.data as any)?.message || '获取API密钥失败');
    }

    return response.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '获取API密钥失败');
  }
};

// 获取单个API密钥详情
export const getKey = async (keyId: string): Promise<ApiKeyData> => {
  try {
    const response = await http.get<ApiResponse<ApiKeyData>>(`/api/keys/${keyId}`);

    if (!response.data.success || !response.data.data) {
      throw new Error((response.data as any)?.message || '获取密钥详情失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '获取密钥详情失败');
  }
};

// 创建API密钥
export const addKey = async (keyData: ApiKeyCreateRequest): Promise<ApiKeyData> => {
  try {
    const response = await http.post<ApiResponse<ApiKeyData>>('/api/keys', keyData);

    if (!response.data.success || !response.data.data) {
      throw new Error((response.data as any)?.message || '创建API密钥失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '创建API密钥失败');
  }
};

// 更新API密钥
export const updateKey = async (keyId: string, keyData: ApiKeyUpdateRequest): Promise<ApiKeyData> => {
  try {
    const response = await http.put<ApiResponse<ApiKeyData>>(`/api/keys/${keyId}`, keyData);

    if (!response.data.success || !response.data.data) {
      throw new Error((response.data as any)?.message || '更新API密钥失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '更新API密钥失败');
  }
};

// 删除API密钥
export const deleteKey = async (keyId: string): Promise<void> => {
  try {
    const response = await http.delete<ApiResponse>(`/api/keys/${keyId}`);

    if (!response.data.success) {
      throw new Error((response.data as any)?.message || '删除API密钥失败');
    }
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '删除API密钥失败');
  }
};

// 获取API密钥使用统计
export const getKeyStats = async (
  keyIdOrString: string,
  period?: 'day' | 'week' | 'month' | 'all'
): Promise<ApiKeyStats> => {
  try {
    const queryParams = new URLSearchParams();
    if (period) queryParams.append('period', period);

    const url = queryParams.toString()
      ? `/api/keys/${keyIdOrString}/stats?${queryParams}`
      : `/api/keys/${keyIdOrString}/stats`;

    const response = await http.get<ApiResponse<ApiKeyStats>>(url);

    if (!response.data.success || !response.data.data) {
      throw new Error((response.data as any)?.message || '获取密钥统计失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '获取密钥统计失败');
  }
};

// 重置API密钥使用计数
export const resetKeyUsage = async (keyIdOrString: string): Promise<void> => {
  try {
    const response = await http.post<ApiResponse>(`/api/keys/${keyIdOrString}/reset-usage`);

    if (!response.data.success) {
      throw new Error((response.data as any)?.message || '重置密钥使用计数失败');
    }
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '重置密钥使用计数失败');
  }
};

// 启用/禁用API密钥
export const toggleKeyStatus = async (keyIdOrString: string): Promise<ApiKeyData> => {
  try {
    const response = await http.patch<ApiResponse<ApiKeyData>>(`/api/keys/${keyIdOrString}/toggle`);

    if (!response.data.success || !response.data.data) {
      throw new Error((response.data as any)?.message || '切换密钥状态失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '切换密钥状态失败');
  }
};

// 测试API密钥
export const testKey = async (keyIdOrString: string): Promise<boolean> => {
  try {
    const response = await http.post<ApiResponse>(`/api/keys/${keyIdOrString}/test`);

    if (!response.data.success) {
      throw new Error((response.data as any)?.message || '测试API密钥失败');
    }

    return (response.data as any).data || true;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '测试API密钥失败');
  }
};