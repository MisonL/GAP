import * as authModule from './modules/auth';
import * as keysModule from './modules/keys';
import * as contextModule from './modules/context';
import * as configModule from './modules/config';
import { hasActiveRequests } from './http';
import type {
  LoginCredentials,
  LoginResponse,
  TokenVerifyResponse,
  UserProfileUpdate,
  ApiKeyData,
  ApiKeyCreateRequest,
  CacheItem,
  ContextItem,
  SystemConfig,
  UsageStats,
  ApiResponse,
  PaginatedResponse,
  ApiError
} from '../stores/types/index';

export type {
  LoginCredentials,
  LoginResponse,
  TokenVerifyResponse,
  UserProfileUpdate,
  ApiKeyData,
  ApiKeyCreateRequest,
  CacheItem,
  ContextItem,
  SystemConfig,
  UsageStats,
  ApiResponse,
  PaginatedResponse,
  ApiError
};

export { hasActiveRequests };

// 导出合并的API服务
const apiService = {
  ...authModule,
  ...keysModule,
  ...contextModule,
  ...configModule,
};

export default apiService;

// 类型守卫函数
export function isApiError(error: unknown): error is ApiError {
  return (
    typeof error === 'object' &&
    error !== null &&
    'message' in error &&
    typeof (error as ApiError).message === 'string'
  );
}

export function isApiResponse<T>(response: unknown): response is ApiResponse<T> {
  return (
    typeof response === 'object' &&
    response !== null &&
    'success' in response &&
    typeof (response as ApiResponse<T>).success === 'boolean'
  );
}

export function isPaginatedResponse<T>(response: unknown): response is PaginatedResponse<T> {
  return (
    isApiResponse<T[]>(response) &&
    'pagination' in response &&
    typeof (response as PaginatedResponse<T>).pagination === 'object'
  );
}