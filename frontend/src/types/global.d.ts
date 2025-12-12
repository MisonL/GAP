// app/frontend/src/types/global.d.ts
// app/frontend/src/types/global.d.ts
import type { Pinia } from 'pinia'; // 导入 Pinia 类型
import { useAppStore } from '../stores/appStore'; // 导入 useAppStore 函数
import { useAuthStore } from '../stores/authStore'; // 导入 useAuthStore 函数
import { useNotificationStore } from '../stores/notificationStore'; // 导入 useNotificationStore 函数
import { NOTIFICATION_TYPES } from '../constants/notificationConstants'; // 导入通知类型常量
import { VIEW_MODES } from '../constants/viewModeConstants'; // 导入视图模式常量

// 获取 Pinia store 的返回类型
type AppStoreInstance = ReturnType<typeof useAppStore>;
type AuthStoreInstance = ReturnType<typeof useAuthStore>;
type NotificationStoreInstance = ReturnType<typeof useNotificationStore>;

// 定义全局接口和类型
declare global {
  // 窗口对象扩展
  interface Window {
    __pinia: Pinia & {
      useAppStore: () => AppStoreInstance; // 声明 useAppStore 方法，返回 AppStoreInstance 类型
      useAuthStore: () => AuthStoreInstance; // 声明 useAuthStore 方法
      useNotificationStore: () => NotificationStoreInstance; // 声明 useNotificationStore 方法
    };
  }

  // API 响应数据类型
  interface ApiResponse<T = unknown> {
    status: number;
    message?: string;
    detail?: string;
    data?: T;
  }

  // Key 管理相关类型
  interface KeyItem {
    key_string: string;
    is_active: boolean;
    created_at: string;
    last_used_at: string | null;
    usage_count: number;
    // 根据实际后端返回的 Key 字段补充
  }

  interface AddKeyPayload {
    key_string: string;
    is_active?: boolean;
  }

  interface UpdateKeyPayload {
    is_active?: boolean;
    // 其他可更新字段
  }

  // Context 管理相关类型
  interface ContextItem {
    context_id: string;
    ttl_seconds: number;
    created_at: string;
    last_accessed_at: string | null;
    // 根据实际后端返回的 Context 字段补充
  }

  interface UpdateContextTTLPayload {
    context_id: string;
    ttl_seconds: number;
  }

  // Key 表单类型
  interface KeyForm {
    key_string: string;
    description: string;
    expires_at: string | null; // ISO 格式字符串或 null
    is_active: boolean;
    enable_context_completion: boolean;
  }

  // useKeyForm 组合式函数的 props 类型
  interface UseKeyFormProps {
    keyToEdit?: KeyItem | null; // 待编辑的 KeyItem，可选
    adminApiKey?: string; // 管理员 API Key，可选
  }

  // 通知类型
  interface NotificationState {
    show: boolean;
    message: string;
    type: typeof NOTIFICATION_TYPES[keyof typeof NOTIFICATION_TYPES]; // 使用常量替代
  }

  // Auth Store 状态类型
  // JWT Payload 类型
  interface JwtPayload {
    sub: string; // Subject (通常是用户ID或用户名)
    admin?: boolean; // 是否是管理员
    exp?: number; // 过期时间
    iat?: number; // 签发时间
    nbf?: number; // 生效时间
    jti?: string; // JWT ID
    iss?: string; // 签发者
    aud?: string[] | string; // 受众
    // 允许自定义扩展字段，但使用更严格的类型
    [key: string]: string | number | boolean | null | undefined;
  }

  // Auth Store 状态类型
  interface AuthState {
    token: string | null;
    user: JwtPayload | null; // 用户信息，使用 JwtPayload 类型
    isAuthenticated: boolean;
    isAdmin: boolean;
    // 其他认证相关状态
  }

  // App Store 状态类型
  interface AppState {
    viewMode: typeof VIEW_MODES[keyof typeof VIEW_MODES]; // 使用常量替代
    globalNotification: NotificationState;
    traditionalListItems: Array<{ id: number; name: string }>;
    // 其他应用相关状态
  }
}