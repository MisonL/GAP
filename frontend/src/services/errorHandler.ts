import type { ApiError } from './http';

// 错误级别
export enum ErrorLevel {
  INFO = 'info',
  WARNING = 'warning',
  ERROR = 'error',
  CRITICAL = 'critical'
}

// 错误处理策略
export interface ErrorHandlingStrategy {
  showNotification: boolean;
  logToConsole: boolean;
  reportToServer: boolean;
  retry: boolean;
  fallbackAction?: () => void;
}

// 默认错误处理策略
const DEFAULT_ERROR_STRATEGIES: Record<number, ErrorHandlingStrategy> = {
  // 网络错误
  0: {
    showNotification: true,
    logToConsole: true,
    reportToServer: false,
    retry: true
  },

  // 客户端错误
  400: {
    showNotification: true,
    logToConsole: true,
    reportToServer: false,
    retry: false
  },

  401: {
    showNotification: true,
    logToConsole: true,
    reportToServer: false,
    retry: false,
    fallbackAction: () => {
      // 清除认证信息并重定向到登录页
      localStorage.removeItem('authToken');
      localStorage.removeItem('authUser');
      window.location.href = '/login';
    }
  },

  403: {
    showNotification: true,
    logToConsole: true,
    reportToServer: false,
    retry: false
  },

  404: {
    showNotification: false,
    logToConsole: true,
    reportToServer: false,
    retry: false
  },

  // 服务器错误
  500: {
    showNotification: true,
    logToConsole: true,
    reportToServer: true,
    retry: true
  },

  502: {
    showNotification: true,
    logToConsole: true,
    reportToServer: true,
    retry: true
  },

  503: {
    showNotification: true,
    logToConsole: true,
    reportToServer: false,
    retry: true
  }
};

// 错误缓存（用于防重复报告）
const errorCache = new Map<string, number>();

// 错误处理主类
export class ErrorHandler {
  private static instance: ErrorHandler;
  private errorCallbacks: Array<(error: ApiError, level: ErrorLevel) => void> = [];

  private constructor() {}

  static getInstance(): ErrorHandler {
    if (!ErrorHandler.instance) {
      ErrorHandler.instance = new ErrorHandler();
    }
    return ErrorHandler.instance;
  }

  // 注册错误回调
  onError(callback: (error: ApiError, level: ErrorLevel) => void): () => void {
    this.errorCallbacks.push(callback);

    // 返回取消注册函数
    return () => {
      const index = this.errorCallbacks.indexOf(callback);
      if (index > -1) {
        this.errorCallbacks.splice(index, 1);
      }
    };
  }

  // 主要错误处理方法
  async handleError(error: ApiError | Error | unknown, customStrategy?: Partial<ErrorHandlingStrategy>): Promise<void> {
    const apiError = this.normalizeError(error);
    const strategy = this.getStrategy(apiError.status || 0, customStrategy);

    // 确定错误级别
    const level = this.determineErrorLevel(apiError);

    // 检查是否为重复错误
    if (this.isDuplicateError(apiError)) {
      return;
    }

    // 执行处理策略
    if (strategy.logToConsole) {
      this.logError(apiError, level);
    }

    if (strategy.showNotification) {
      this.showErrorNotification(apiError);
    }

    if (strategy.reportToServer) {
      await this.reportErrorToServer(apiError);
    }

    if (strategy.fallbackAction) {
      strategy.fallbackAction();
    }

    // 调用注册的回调函数
    this.errorCallbacks.forEach(callback => {
      try {
        callback(apiError, level);
      } catch (callbackError) {
        console.error('Error in error callback:', callbackError);
      }
    });
  }

  // 标准化错误对象
  private normalizeError(error: unknown): ApiError {
    if (this.isApiError(error)) {
      return error;
    }

    if (error instanceof Error) {
      return {
        message: error.message,
        code: 'JAVASCRIPT_ERROR',
        timestamp: new Date().toISOString(),
        details: {
          stack: error.stack,
          name: error.name
        }
      };
    }

    if (typeof error === 'string') {
      return {
        message: error,
        code: 'STRING_ERROR',
        timestamp: new Date().toISOString()
      };
    }

    return {
      message: '未知错误',
      code: 'UNKNOWN_ERROR',
      timestamp: new Date().toISOString(),
      details: { originalError: error }
    };
  }

  // 检查是否为ApiError
  private isApiError(error: unknown): error is ApiError {
    return error !== null && typeof error === 'object' && 'message' in error;
  }

  // 获取处理策略
  private getStrategy(status: number, customStrategy?: Partial<ErrorHandlingStrategy>): ErrorHandlingStrategy {
    const defaultStrategy = DEFAULT_ERROR_STRATEGIES[status] || {
      showNotification: true,
      logToConsole: true,
      reportToServer: false,
      retry: false
    };

    return { ...defaultStrategy, ...customStrategy };
  }

  // 确定错误级别
  private determineErrorLevel(error: ApiError): ErrorLevel {
    const status = error.status || 0;

    if (status >= 500) {
      return ErrorLevel.CRITICAL;
    }

    if (status >= 400) {
      return ErrorLevel.ERROR;
    }

    if (error.code === 'NETWORK_ERROR') {
      return ErrorLevel.WARNING;
    }

    return ErrorLevel.INFO;
  }

  // 检查重复错误
  private isDuplicateError(error: ApiError): boolean {
    const key = `${error.code}-${error.message}-${error.status || 0}`;
    const now = Date.now();

    if (errorCache.has(key)) {
      const lastTime = errorCache.get(key)!;
      if (now - lastTime < 5000) { // 5秒内的重复错误
        return true;
      }
    }

    errorCache.set(key, now);

    // 清理过期的错误缓存
    setTimeout(() => {
      errorCache.delete(key);
    }, 30000); // 30秒后清理

    return false;
  }

  // 控制台日志
  private logError(error: ApiError, level: ErrorLevel): void {
    const logMethod = level === ErrorLevel.CRITICAL ? 'error' :
                     level === ErrorLevel.ERROR ? 'error' :
                     level === ErrorLevel.WARNING ? 'warn' : 'info';

    console[logMethod](`[${level.toUpperCase()}] ${error.message}`, {
      status: error.status,
      code: error.code,
      details: error.details,
      timestamp: error.timestamp,
      requestId: error.requestId
    });
  }

  // 显示错误通知
  private showErrorNotification(error: ApiError): void {
    // 动态导入appStore以避免循环依赖
    import('../stores/appStore').then(({ useAppStore }) => {
      const appStore = useAppStore();

      // 根据错误级别选择通知类型
      const notificationType = error.status && error.status >= 500 ? 'error' : 'warning' as const;

      // 格式化错误消息
      let message = error.message;
      if (error.status && error.status >= 500) {
        message = `${error.message} (错误代码: ${error.status})`;
      }

      appStore.showNotification(message, notificationType, 5000);
    });
  }

  // 向服务器报告错误
  private async reportErrorToServer(error: ApiError): Promise<void> {
    try {
      // 避免在请求错误时再次发生错误
      if (error.code === 'NETWORK_ERROR') {
        return;
      }

      await fetch('/api/errors/report', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          error: {
            message: error.message,
            status: error.status,
            code: error.code,
            details: error.details
          },
          context: {
            userAgent: navigator.userAgent,
            url: window.location.href,
            timestamp: new Date().toISOString(),
            requestId: error.requestId
          }
        })
      });
    } catch (reportError) {
      console.warn('Failed to report error to server:', reportError);
    }
  }
}

// 全局错误处理器实例
export const globalErrorHandler = ErrorHandler.getInstance();

// 便捷的错误处理函数
export function handleError(error: unknown, customStrategy?: Partial<ErrorHandlingStrategy>): Promise<void> {
  return globalErrorHandler.handleError(error, customStrategy);
}

// 装饰器：为函数添加错误处理
export function withErrorHandling<T extends readonly unknown[], R>(
  fn: (...args: T) => Promise<R>,
  customStrategy?: Partial<ErrorHandlingStrategy>
): (...args: T) => Promise<R | undefined> {
  return async (...args: T): Promise<R | undefined> => {
    try {
      return await fn(...args);
    } catch (error) {
      await handleError(error, customStrategy);
      return undefined;
    }
  };
}

// React Hook风格的错误处理钩子
export function useErrorHandler() {
  const { onError } = globalErrorHandler;

  return {
    handleError: globalErrorHandler.handleError.bind(globalErrorHandler),
    onError,
    withErrorHandling
  };
}

export default globalErrorHandler;