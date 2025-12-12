import type { Ref } from 'vue';
import type { ApiError } from './types/index';

export interface AppState {
  viewMode: 'bento' | 'traditional';
  globalNotification: {
    show: boolean;
    message: string;
    type: 'success' | 'error' | 'warning' | 'info';
    timeout?: number;
  };
  loading: boolean;
  globalError: ApiError | null;
  theme: 'light' | 'dark' | 'auto';
  sidebar: boolean;
  userSession: {
    token: string | null;
    refreshToken: string | null;
    userId: string | null;
    username: string | null;
    isLoggedIn: boolean;
  };
}

export declare const useAppStore: () => AppState & {
  setViewMode(mode: 'bento' | 'traditional'): void;
  setGlobalNotification(notification: {
    message: string;
    type: 'success' | 'error' | 'warning' | 'info';
    timeout?: number;
  }): void;
  clearGlobalNotification(): void;
  setLoading(loading: boolean): void;
  setGlobalError(error: ApiError | null): void;
  clearGlobalError(): void;
  setTheme(theme: 'light' | 'dark' | 'auto'): void;
  toggleSidebar(): void;
  setSidebar(open: boolean): void;
  setUserSession(session: {
    token: string | null;
    refreshToken: string | null;
    userId: string | null;
    username: string | null;
    isLoggedIn: boolean;
  }): void;
  clearUserSession(): void;
  showNotification(message: string, type?: string, duration?: number): void;
  incrementActiveRequests(): void;
  decrementActiveRequests(): void;
};