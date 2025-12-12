import http from '../http';
import type { ApiResponse, SystemStatus, UsageStats } from '../../stores/types';

// HTTP错误类型
interface HttpErrorResponse {
  response?: {
    data?: {
      message?: string;
    };
  };
  message?: string;
}

// 系统配置类型
export interface SystemConfig {
  database: {
    url: string;
    maxConnections: number;
    poolTimeout: number;
  };
  redis: {
    url: string;
    maxRetries: number;
    retryDelay: number;
  };
  api: {
    maxRequestsPerMinute: number;
    maxRequestsPerDay: number;
    defaultTimeout: number;
    enableDocs: boolean;
    enableCors: boolean;
  };
  security: {
    secretKeyRotationDays: number;
    sessionTimeoutMinutes: number;
    maxLoginAttempts: number;
    lockoutDurationMinutes: number;
  };
  logging: {
    level: string;
    maxFileSize: string;
    maxFiles: number;
    enableConsole: boolean;
  };
}

// 获取系统状态
export const getSystemStatus = async (): Promise<SystemStatus> => {
  try {
    const response = await http.get<ApiResponse<SystemStatus>>('/api/system/status');

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '获取系统状态失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '获取系统状态失败');
  }
};

// 获取系统配置
export const getSystemConfig = async (): Promise<SystemConfig> => {
  try {
    const response = await http.get<ApiResponse<SystemConfig>>('/api/system/config');

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '获取系统配置失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '获取系统配置失败');
  }
};

// 更新系统配置
export const updateSystemConfig = async (configData: Partial<SystemConfig>): Promise<SystemConfig> => {
  try {
    const response = await http.put<ApiResponse<SystemConfig>>('/api/system/config', configData);

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '更新系统配置失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '更新系统配置失败');
  }
};

// 获取使用统计
export const getUsageStats = async (params?: {
  period?: 'hour' | 'day' | 'week' | 'month';
  startDate?: string;
  endDate?: string;
  groupBy?: 'model' | 'user' | 'endpoint';
}): Promise<UsageStats> => {
  try {
    const queryParams = new URLSearchParams();
    if (params?.period) queryParams.append('period', params.period);
    if (params?.startDate) queryParams.append('startDate', params.startDate);
    if (params?.endDate) queryParams.append('endDate', params.endDate);
    if (params?.groupBy) queryParams.append('groupBy', params.groupBy);

    const url = queryParams.toString()
      ? `/api/system/stats?${queryParams}`
      : '/api/system/stats';

    const response = await http.get<ApiResponse<UsageStats>>(url);

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '获取使用统计失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '获取使用统计失败');
  }
};

// 重置使用统计
export const resetUsageStats = async (params?: {
  period?: 'hour' | 'day' | 'week' | 'month';
}): Promise<void> => {
  try {
    const queryParams = new URLSearchParams();
    if (params?.period) queryParams.append('period', params.period);

    const url = queryParams.toString()
      ? `/api/system/stats/reset?${queryParams}`
      : '/api/system/stats/reset';

    const response = await http.post<ApiResponse>(url);

    if (!response.data.success) {
      throw new Error(response.data.message || '重置使用统计失败');
    }
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '重置使用统计失败');
  }
};

// 获取数据库统计
export const getDatabaseStats = async (): Promise<{
  totalConnections: number;
  activeConnections: number;
  idleConnections: number;
  totalQueries: number;
  avgResponseTime: number;
  errorRate: number;
  tables: {
    name: string;
    rowCount: number;
    size: string;
    lastUpdated: string;
  }[];
}> => {
  try {
    const response = await http.get<ApiResponse<any>>('/api/system/database-stats');

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '获取数据库统计失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '获取数据库统计失败');
  }
};

// 获取缓存统计
export const getCacheStats = async (): Promise<{
  totalKeys: number;
  memoryUsage: number;
  hitRate: number;
  missRate: number;
  evictions: number;
  connections: number;
  uptime: number;
}> => {
  try {
    const response = await http.get<ApiResponse<any>>('/api/system/cache-stats');

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '获取缓存统计失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '获取缓存统计失败');
  }
};

// 清理缓存
export const clearCache = async (params?: {
  pattern?: string;
  userId?: string;
  model?: string;
}): Promise<{ deletedKeys: number }> => {
  try {
    const queryParams = new URLSearchParams();
    if (params?.pattern) queryParams.append('pattern', params.pattern);
    if (params?.userId) queryParams.append('userId', params.userId);
    if (params?.model) queryParams.append('model', params.model);

    const url = queryParams.toString()
      ? `/api/system/cache/clear?${queryParams}`
      : '/api/system/cache/clear';

    const response = await http.post<ApiResponse<{ deletedKeys: number }>>(url);

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '清理缓存失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '清理缓存失败');
  }
};

// 备份数据
export const backupData = async (params?: {
  includeDatabase?: boolean;
  includeCache?: boolean;
  includeLogs?: boolean;
}): Promise<{
  backupId: string;
  filename: string;
  size: number;
  createdAt: string;
}> => {
  try {
    const response = await http.post<ApiResponse<any>>('/api/system/backup', params || {});

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '备份数据失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '备份数据失败');
  }
};

// 恢复数据
export const restoreData = async (backupId: string): Promise<{
  success: boolean;
  restoredItems: string[];
  errors?: string[];
}> => {
  try {
    const response = await http.post<ApiResponse<any>>(`/api/system/restore/${backupId}`);

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '恢复数据失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '恢复数据失败');
  }
};

// 获取备份列表
export const getBackups = async (): Promise<Array<{
  id: string;
  filename: string;
  size: number;
  createdAt: string;
  type: string;
}>> => {
  try {
    const response = await http.get<ApiResponse<any>>('/api/system/backups');

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '获取备份列表失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '获取备份列表失败');
  }
};

// 删除备份
export const deleteBackup = async (backupId: string): Promise<void> => {
  try {
    const response = await http.delete<ApiResponse>(`/api/system/backups/${backupId}`);

    if (!response.data.success) {
      throw new Error(response.data.message || '删除备份失败');
    }
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '删除备份失败');
  }
};

// 下载备份文件
export const downloadBackup = async (backupId: string): Promise<Blob> => {
  try {
    const response = await http.get(`/api/system/backups/${backupId}/download`, {
      responseType: 'blob'
    });

    return response.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '下载备份失败');
  }
};

// 重启系统服务
export const restartService = async (service: 'api' | 'database' | 'cache' | 'all'): Promise<{
  success: boolean;
  message: string;
  restartedAt: string;
}> => {
  try {
    const response = await http.post<ApiResponse<any>>(`/api/system/restart/${service}`);

    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.message || '重启服务失败');
    }

    return response.data.data;
  } catch (error: unknown) {
    const httpError = error as HttpErrorResponse;
    throw new Error(httpError.response?.data?.message || httpError.message || '重启服务失败');
  }
};