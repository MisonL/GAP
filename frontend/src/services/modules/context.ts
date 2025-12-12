import http from '../http';
import type { ApiResponse, PaginatedResponse } from '../../stores/types';

// 上下文项类型
export interface ContextItem {
  id: string;
  userId: string;
  sessionId?: string;
  messages: Array<{
    role: 'user' | 'assistant' | 'system';
    content: string;
    timestamp: string;
    tokenCount?: number;
  }>;
  model: string;
  totalTokens: number;
  lastActivity: string;
  metadata?: {
    temperature?: number;
    maxTokens?: number;
    topP?: number;
    systemPrompt?: string;
  };
  createdAt: string;
  updatedAt: string;
  expiresAt?: string;
}

// 缓存项目类型（导出给stores使用）
export interface CacheItem {
  id: string;
  userId: string;
  model: string;
  input: string;
  output: string;
  cachedAt: string;
  expiresAt: string;
  ttl: number;
  size: number;
  hits: number;
  lastAccessed: string;
}

// 获取用户上下文列表
export const getContexts = async (params?: {
  page?: number;
  limit?: number;
  model?: string;
  sessionId?: string;
  search?: string;
}): Promise<PaginatedResponse<ContextItem>> => {
  try {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    if (params?.model) queryParams.append('model', params.model);
    if (params?.sessionId) queryParams.append('sessionId', params.sessionId);
    if (params?.search) queryParams.append('search', params.search);

    const url = queryParams.toString()
      ? `/api/contexts?${queryParams}`
      : '/api/contexts';

    const response = await http.get<PaginatedResponse<ContextItem>>(url);

    if (!response.data.success) {
      throw new Error((response.data as any)?.message || '获取上下文列表失败');
    }

    return response.data;
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '获取上下文列表失败');
  }
};

// 获取单个上下文详情
export const getContext = async (contextId: string): Promise<ContextItem> => {
  try {
    const response = await http.get<ApiResponse<ContextItem>>(`/api/contexts/${contextId}`);

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '获取上下文详情失败');
    }

    return response.data.data;
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '获取上下文详情失败');
  }
};

// 创建新上下文
export const createContext = async (contextData: {
  sessionId?: string;
  model: string;
  message: {
    role: 'user' | 'assistant' | 'system';
    content: string;
  };
  metadata?: {
    temperature?: number;
    maxTokens?: number;
    topP?: number;
    systemPrompt?: string;
  };
}): Promise<ContextItem> => {
  try {
    const response = await http.post<ApiResponse<ContextItem>>('/api/contexts', contextData);

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '创建上下文失败');
    }

    return response.data.data;
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '创建上下文失败');
  }
};

// 更新上下文（添加消息）
export const updateContext = async (contextId: string, updateData: {
  message: {
    role: 'user' | 'assistant' | 'system';
    content: string;
  };
  metadata?: {
    temperature?: number;
    maxTokens?: number;
    topP?: number;
  };
}): Promise<ContextItem> => {
  try {
    const response = await http.put<ApiResponse<ContextItem>>(`/api/contexts/${contextId}`, updateData);

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '更新上下文失败');
    }

    return response.data.data;
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '更新上下文失败');
  }
};

// 删除上下文
export const deleteContext = async (contextId: string): Promise<void> => {
  try {
    const response = await http.delete<ApiResponse>(`/api/contexts/${contextId}`);

    if (!response.data.success) {
      throw new Error(response.data.message || '删除上下文失败');
    }
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '删除上下文失败');
  }
};

// 批量删除上下文
export const bulkDeleteContexts = async (
  contextIds: string[],
  filters?: {
    model?: string;
    sessionId?: string;
    olderThan?: string;
  }
): Promise<{ deletedCount: number }> => {
  try {
    const response = await http.post<ApiResponse<{ deletedCount: number }>>('/api/contexts/bulk-delete', {
      contextIds,
      filters
    });

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '批量删除上下文失败');
    }

    return response.data.data;
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '批量删除上下文失败');
  }
};

// 清理过期上下文
export const cleanupExpiredContexts = async (): Promise<{ deletedCount: number }> => {
  try {
    const response = await http.post<ApiResponse<{ deletedCount: number }>>('/api/contexts/cleanup');

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '清理过期上下文失败');
    }

    return response.data.data;
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '清理过期上下文失败');
  }
};

// 导出上下文
export const exportContexts = async (params?: {
  format?: 'json' | 'csv' | 'txt';
  contextIds?: string[];
  filters?: {
    model?: string;
    sessionId?: string;
    dateFrom?: string;
    dateTo?: string;
  };
}): Promise<string> => {
  try {
    const queryParams = new URLSearchParams();
    if (params?.format) queryParams.append('format', params.format);
    if (params?.contextIds) {
      params.contextIds.forEach(id => queryParams.append('contextIds', id));
    }
    if (params?.filters?.model) queryParams.append('model', params.filters.model);
    if (params?.filters?.sessionId) queryParams.append('sessionId', params.filters.sessionId);
    if (params?.filters?.dateFrom) queryParams.append('dateFrom', params.filters.dateFrom);
    if (params?.filters?.dateTo) queryParams.append('dateTo', params.filters.dateTo);

    const url = queryParams.toString()
      ? `/api/contexts/export?${queryParams}`
      : '/api/contexts/export';

    const response = await http.get<string>(url, {
      responseType: params?.format === 'csv' ? 'blob' : 'text'
    });

    return response.data;
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '导出上下文失败');
  }
};

// 搜索上下文内容
export const searchContexts = async (searchParams: {
  query: string;
  model?: string;
  role?: 'user' | 'assistant' | 'system';
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  limit?: number;
}): Promise<PaginatedResponse<ContextItem>> => {
  try {
    const queryParams = new URLSearchParams();
    queryParams.append('q', searchParams.query);
    if (searchParams.model) queryParams.append('model', searchParams.model);
    if (searchParams.role) queryParams.append('role', searchParams.role);
    if (searchParams.dateFrom) queryParams.append('dateFrom', searchParams.dateFrom);
    if (searchParams.dateTo) queryParams.append('dateTo', searchParams.dateTo);
    if (searchParams.page) queryParams.append('page', searchParams.page.toString());
    if (searchParams.limit) queryParams.append('limit', searchParams.limit.toString());

    const response = await http.get<PaginatedResponse<ContextItem>>(
      `/api/contexts/search?${queryParams}`
    );

    if (!response.data.success) {
      throw new Error((response.data as any)?.message || '搜索上下文失败');
    }

    return response.data;
  } catch (error: any) {
    throw new Error(error.response?.data?.message || error.message || '搜索上下文失败');
  }
};