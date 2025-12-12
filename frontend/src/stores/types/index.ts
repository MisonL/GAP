// API 错误类型
export interface ApiError {
  message: string;
  status?: number;
  code?: string;
  details?: Record<string, unknown>;
}

// 登录凭据
export interface LoginCredentials {
  username: string;
  password: string;
  remember?: boolean;
}

// 登录响应
export interface LoginResponse {
  token: string;
  refreshToken?: string;
  expiresIn?: number;
  user?: {
    id: string;
    username: string;
    email?: string;
    role?: 'user' | 'admin';
    avatar?: string;
  };
}

// Token验证响应
export interface TokenVerifyResponse {
  valid: boolean;
  user?: {
    id: string;
    username: string;
    email?: string;
    role?: 'user' | 'admin';
  };
  expiresAt?: string;
}

// 用户更新资料
export interface UserProfileUpdate {
  username?: string;
  email?: string;
  currentPassword?: string;
  newPassword?: string;
  avatar?: string;
}

// API响应基础类型
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  message?: string;
  code?: string;
}

// 分页响应
export interface PaginatedResponse<T = unknown> {
  success: boolean;
  data: T[];
  pagination: {
    page: number;
    limit: number;
    total: number;
    totalPages: number;
    hasNext: boolean;
    hasPrev: boolean;
  };
}

// 缓存项类型
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
}

// 上下文项类型
export interface ContextItem {
  id: string;
  userId: string;
  sessionId: string;
  model: string;
  messages: Array<{
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
  }>;
  createdAt: string;
  updatedAt: string;
  ttl: number;
  isActive: boolean;
}

// 系统配置类型
export interface SystemConfig {
  maintenance: boolean;
  version: string;
  features: {
    registration: boolean;
    chat: boolean;
    keys: boolean;
    reports: boolean;
  };
  limits: {
    maxKeysPerUser: number;
    maxContextsPerUser: number;
    maxRequestsPerHour: number;
  };
  security: {
    requireEmailVerification: boolean;
    passwordMinLength: number;
    sessionTimeout: number;
  };
  ui: {
    theme: 'light' | 'dark' | 'auto';
    language: string;
    customBranding: boolean;
  };
}

// API密钥统计接口
export interface ApiKeyStats {
  period: 'day' | 'week' | 'month' | 'all';
  startDate: string;
  endDate: string;
  requestCount: number;
  tokenCount: number;
  successfulRequests: number;
  failedRequests: number;
  errorRate: number;
  averageResponseTime?: number;
}

// API密钥创建请求
export interface ApiKeyCreateRequest {
  key: string;
  provider: 'gemini' | 'openai' | 'custom';
  name?: string;
  settings?: {
    rpd?: number;
    rpm?: number;
    tpd?: number;
    tpm?: number;
  };
}

// API密钥更新请求
export interface ApiKeyUpdateRequest {
  name?: string;
  status?: 'active' | 'inactive';
}

// API密钥类型
export interface ApiKeyData {
  id: string;
  key: string; // 部分隐藏的密钥
  name?: string;
  provider: 'gemini' | 'openai' | 'custom';
  status: 'active' | 'inactive' | 'error' | 'disabled';
  usage: {
    count: number;
    lastUsed?: string;
  };
  limits: {
    rpd?: number; // requests per day
    rpm?: number; // requests per minute
    tpd?: number; // tokens per day
    tpm?: number; // tokens per minute
  };
  health: {
    score: number;
    lastCheck: string;
    errorRate: number;
    avgResponseTime: number;
  };
  createdAt: string;
  updatedAt: string;
}

// 使用统计
export interface UsageStats {
  period: 'hour' | 'day' | 'week' | 'month';
  requests: number;
  tokens: number;
  cost: number;
  successRate: number;
  avgResponseTime: number;
  errors: {
    count: number;
    types: Record<string, number>;
  };
  breakdown: {
    byModel: Record<string, number>;
    byEndpoint: Record<string, number>;
    byUser: Record<string, number>;
  };
}

// 用户类型
export interface User {
  id: string;
  username: string;
  email?: string;
  role?: 'user' | 'admin';
  avatar?: string;
  createdAt?: string;
  lastLoginAt?: string;
  isActive?: boolean;
  preferences?: {
    theme?: 'light' | 'dark' | 'auto';
    language?: string;
    notifications?: {
      email?: boolean;
      push?: boolean;
    };
  };
}

// 系统状态
export interface SystemStatus {
  status: 'healthy' | 'degraded' | 'down';
  version: string;
  uptime: number;
  services: {
    database: 'healthy' | 'degraded' | 'down';
    redis: 'healthy' | 'degraded' | 'down';
    api: 'healthy' | 'degraded' | 'down';
  };
  metrics: {
    activeConnections: number;
    requestsPerMinute: number;
    errorRate: number;
    memoryUsage: number;
    cpuUsage: number;
  };
  timestamp: string;
}