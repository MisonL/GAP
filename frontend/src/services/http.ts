import axios from 'axios';
import type { AxiosInstance, AxiosResponse, AxiosError, InternalAxiosRequestConfig } from 'axios';
import { useAppStore } from '../stores/appStore';

// 错误类型定义
export interface ApiError {
  message: string;
  status?: number;
  code?: string;
  details?: Record<string, unknown>;
  timestamp?: string;
  requestId?: string;
}

// 重试配置
export interface RetryConfig {
  maxRetries: number;
  retryDelay: number;
  retryCondition?: (error: AxiosError) => boolean;
}

// 默认重试配置
const DEFAULT_RETRY_CONFIG: RetryConfig = {
  maxRetries: 3,
  retryDelay: 1000,
  retryCondition: (error: AxiosError) => {
    // 只对网络错误和5xx错误重试
    return !error.response || (error.response.status >= 500 && error.response.status < 600);
  }
};

// 请求取消令牌存储
const pendingRequests = new Map<string, AbortController>();

// 根据环境动态计算 API 基础地址
// - 开发环境: 默认指向本机 8000（FastAPI dev 端口），也可通过 VITE_API_BASE_URL 覆盖
// - 生产/容器环境: 默认使用当前站点 origin（例如 Docker 下的 http://localhost:7860），
//   从而复用同一域名/端口的后端 API
const defaultBaseURL = (() => {
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL;
  }
  if (import.meta.env.DEV) {
    return 'http://localhost:8000';
  }
  if (typeof window !== 'undefined') {
    return window.location.origin;
  }
  return '';
})();

// 创建axios实例
const http: AxiosInstance = axios.create({
  baseURL: defaultBaseURL,
  timeout: 30000, // 30秒超时
  headers: {
    'Content-Type': 'application/json',
  },
});

// 扩展Axios请求配置类型以支持metadata
declare module 'axios' {
  interface InternalAxiosRequestConfig {
    metadata?: {
      requestId: string;
      requestKey: string;
      startTime: number;
    };
  }
}

// 请求拦截器
http.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 生成请求ID
    const requestId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    // 取消相同URL的重复请求
    const requestKey = `${config.method?.toUpperCase()}-${config.url}`;
    if (pendingRequests.has(requestKey)) {
      const controller = pendingRequests.get(requestKey);
      controller?.abort();
    }

    // 创建新的取消控制器
    const controller = new AbortController();
    pendingRequests.set(requestKey, controller);

    // 添加取消信号到配置
    config.signal = controller.signal;
    config.metadata = { requestId, requestKey, startTime: Date.now() };

    // 添加认证token
    const token = localStorage.getItem('authToken');
    if (token) {
      config.headers = config.headers || {};
      config.headers['Authorization'] = `Bearer ${token}`;
    }

    // 更新应用状态
    const appStore = useAppStore();
    appStore.incrementActiveRequests();

    console.log(`[HTTP Request] ${config.method?.toUpperCase()} ${config.url}`, {
      requestId,
      hasData: !!config.data,
      hasAuth: !!token
    });

    return config;
  },
  (error: AxiosError) => {
    console.error('[HTTP Request Error]', error);
    return Promise.reject(createApiErrorFromAxiosError(error));
  }
);

// 响应拦截器
http.interceptors.response.use(
  (response: AxiosResponse) => {
    // 清理请求记录
    const config = response.config as InternalAxiosRequestConfig & {
      metadata?: {
        requestId: string;
        requestKey: string;
        startTime: number;
      };
    };
    if (config?.metadata?.requestKey) {
      pendingRequests.delete(config.metadata.requestKey);
    }

    // 更新应用状态
    const appStore = useAppStore();
    appStore.decrementActiveRequests();

    // 记录响应
    console.log(`[HTTP Response] ${response.status} ${response.config.method?.toUpperCase()} ${response.config.url}`, {
      requestId: config?.metadata?.requestId,
      duration: Date.now() - (config.metadata?.startTime || Date.now())
    });

    // 处理特殊响应状态
    return handleSpecialResponses(response);
  },
  async (error: AxiosError) => {
    // 清理请求记录
    const config = error.config as InternalAxiosRequestConfig & {
      metadata?: {
        requestId: string;
        requestKey: string;
        startTime: number;
      };
    };
    if (config?.metadata?.requestKey) {
      pendingRequests.delete(config.metadata.requestKey);
    }

    // 更新应用状态
    const appStore = useAppStore();
    appStore.decrementActiveRequests();

    // 处理取消请求
    if (error.name === 'CanceledError') {
      console.log(`[HTTP Request Cancelled] ${config?.method?.toUpperCase()} ${config?.url}`);
      return Promise.reject(createApiError('请求已取消', 0, 'REQUEST_CANCELLED'));
    }

    // 处理网络错误
    if (!error.response) {
      const apiError = createApiError('网络连接失败，请检查网络设置', 0, 'NETWORK_ERROR');
      return Promise.reject(apiError);
    }

    // 处理HTTP错误状态码
    const apiError = handleHttpStatusError(error);

    // 记录错误
    console.error(`[HTTP Error] ${error.response.status} ${error.config?.method?.toUpperCase()} ${error.config?.url}`, {
      requestId: config?.metadata?.requestId,
      error: apiError,
      response: error.response.data
    });

    return Promise.reject(apiError);
  }
);

// 处理特殊响应状态
function handleSpecialResponses(response: AxiosResponse): AxiosResponse {
  const { config } = response;

  // 登录接口的特殊处理
  if (config.url?.includes('/login') && response.status === 204) {
    const loginToken = response.headers['x-access-token'];
    if (loginToken) {
      response.data = { token: loginToken, user: {} };
      return response;
    }
  }

  // 204 No Content 响应处理
  if (response.status === 204) {
    response.data = { success: true, message: '操作成功' };
    return response;
  }

  return response;
}

// 处理HTTP状态码错误
function handleHttpStatusError(error: AxiosError): ApiError {
  const { response } = error;
  const status = response?.status || 0;
  const url = error.config?.url || '';

  switch (status) {
    case 400:
      return createApiError(
        (response?.data as any)?.message || '请求参数错误',
        400,
        'BAD_REQUEST',
        response?.data
      );

    case 401:
      // 清除过期的token
      localStorage.removeItem('authToken');
      return createApiError(
        '认证失败，请重新登录',
        401,
        'UNAUTHORIZED',
        { requiresReauth: true }
      );

    case 403:
      return createApiError(
        '权限不足，无法访问该资源',
        403,
        'FORBIDDEN'
      );

    case 404:
      return createApiError(
        `请求的资源不存在: ${url}`,
        404,
        'NOT_FOUND'
      );

    case 408:
      return createApiError(
        '请求超时，请稍后重试',
        408,
        'TIMEOUT'
      );

    case 429:
      return createApiError(
        '请求过于频繁，请稍后重试',
        429,
        'TOO_MANY_REQUESTS',
        { retryAfter: response?.headers?.['retry-after'] }
      );

    case 500:
      return createApiError(
        '服务器内部错误，请联系管理员',
        500,
        'INTERNAL_SERVER_ERROR'
      );

    case 502:
      return createApiError(
        '网关错误，请稍后重试',
        502,
        'BAD_GATEWAY'
      );

    case 503:
      return createApiError(
        '服务暂时不可用，请稍后重试',
        503,
        'SERVICE_UNAVAILABLE'
      );

    case 504:
      return createApiError(
        '网关超时，请稍后重试',
        504,
        'GATEWAY_TIMEOUT'
      );

    default:
      return createApiError(
        (response?.data as any)?.message || `未知错误 (${status})`,
        status,
        'UNKNOWN_ERROR',
        response?.data
      );
  }
}

// 创建API错误对象
function createApiError(
  message: string,
  status: number = 0,
  code?: string,
  details?: unknown
): ApiError {
  return {
    message,
    status,
    code,
    details: details as Record<string, unknown> | undefined,
    timestamp: new Date().toISOString(),
    requestId: Math.random().toString(36).substr(2, 9)
  };
}

// 从Axios错误创建API错误
function createApiErrorFromAxiosError(error: AxiosError): ApiError {
  return createApiError(
    error.message || '请求失败',
    error.response?.status || 0,
    error.code || 'REQUEST_ERROR',
    {
      url: error.config?.url,
      method: error.config?.method?.toUpperCase(),
      originalError: error
    }
  );
}

// 重试机制
async function retryRequest(
  config: InternalAxiosRequestConfig,
  retryConfig: RetryConfig = DEFAULT_RETRY_CONFIG,
  attempt: number = 1
): Promise<AxiosResponse> {
  try {
    return await http(config);
  } catch (error: unknown) {
    const axiosError = error as AxiosError;
    if (
      attempt < retryConfig.maxRetries &&
      (!retryConfig.retryCondition || retryConfig.retryCondition(axiosError))
    ) {
      console.log(`[HTTP Retry] Attempt ${attempt + 1} for ${config.method?.toUpperCase()} ${config.url}`);

      // 指数退避延迟
      const delay = retryConfig.retryDelay * Math.pow(2, attempt - 1);
      await new Promise(resolve => setTimeout(resolve, delay));

      return retryRequest(config, retryConfig, attempt + 1);
    }
    throw error;
  }
}

// 带重试的请求方法
export function requestWithRetry(
  config: InternalAxiosRequestConfig,
  retryConfig?: Partial<RetryConfig>
): Promise<AxiosResponse> {
  const finalRetryConfig = { ...DEFAULT_RETRY_CONFIG, ...retryConfig };
  return retryRequest(config, finalRetryConfig);
}

// 取消所有pending请求
export function cancelAllRequests(): void {
  pendingRequests.forEach(controller => {
    controller.abort();
  });
  pendingRequests.clear();
}

// 取消特定请求
export function cancelRequest(requestKey: string): void {
  const controller = pendingRequests.get(requestKey);
  if (controller) {
    controller.abort();
    pendingRequests.delete(requestKey);
  }
}

// 检查是否有活跃请求
export function hasActiveRequests(): boolean {
  return pendingRequests.size > 0;
}

// 获取活跃请求数量
export function getActiveRequestsCount(): number {
  return pendingRequests.size;
}

// 导出默认客户端
export default http;

// 导出辅助函数
export { createApiError, retryRequest };