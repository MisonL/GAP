import { useAuthStore } from '../stores/authStore';
import { useAppStore } from '../stores/appStore'; // 引入 appStore
import { API_ENDPOINTS } from '../constants/apiConstants';

// 用于跟踪所有活跃请求的 Set
const activeRequests = new Set();

// 生成唯一请求 ID 的函数
function generateRequestId() {
    return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

// 后端 API 的基础 URL，可以从环境变量获取
// 在 Vite 中，可以使用 import.meta.env.VITE_API_BASE_URL
// 对于 /login 这样的 Web UI 路由，它通常不在 /api/v1 下，所以 API_BASE_URL 不适用于它。
// 我们将为 login 请求特殊处理路径。
const API_BASE_URL_FOR_OTHER_APIS = import.meta.env.VITE_API_BASE_URL || API_ENDPOINTS.BASE_V1;

/**
 * 封装的 fetch 请求函数
 * @param {string} endpoint API 端点路径 (例如 '/users')
 * @param {object} options Fetch API 的配置对象 (method, headers, body, etc.)
 * @returns {Promise<any>} 解析后的 JSON 响应或在错误时 reject
 */
async function request(endpoint, options = {}) {
    const authStore = useAuthStore();
    const appStore = useAppStore(); // 获取 appStore 实例
    const currentToken = authStore.token; // Renamed to avoid conflict with loginToken

    const requestId = generateRequestId(); // 生成唯一请求 ID
    activeRequests.add(requestId); // 将请求 ID 添加到活跃请求 Set 中
    appStore.incrementActiveRequests(); // 增加活跃请求计数器

    let requestHeaders = { ...options.headers };
    let requestBody = options.body;
    let targetUrl;

    if (endpoint === '/login') {
        // 特殊处理登录请求：发送 x-www-form-urlencoded 数据
        requestHeaders['Content-Type'] = 'application/x-www-form-urlencoded';
        if (options.body && typeof options.body === 'object') {
            const params = new URLSearchParams();
            for (const key in options.body) {
                params.append(key, options.body[key]);
            }
            requestBody = params;
        }
        targetUrl = endpoint; // 直接使用 /login，由 Vite 代理
    } else {
        // 其他 API 请求使用 API_BASE_URL_FOR_OTHER_APIS
        requestHeaders['Content-Type'] = requestHeaders['Content-Type'] || 'application/json';
        if (options.body && typeof options.body !== 'string' && !(options.body instanceof FormData)) {
            requestBody = JSON.stringify(options.body);
        }
        // 如果 endpoint 已经是像 /api/manage/... 这样的路径，则直接使用
        // 否则，才拼接 API_BASE_URL_FOR_OTHER_APIS (通常用于 /v1/...)
        if (endpoint.startsWith(API_ENDPOINTS.BASE_MANAGE) || endpoint.startsWith(API_ENDPOINTS.BASE_V2) ) { // 假设 /api/v2 也是直接路径
             targetUrl = endpoint;
        } else {
             targetUrl = `${API_BASE_URL_FOR_OTHER_APIS}${endpoint}`;
        }
    }

    if (currentToken) {
        requestHeaders['Authorization'] = `Bearer ${currentToken}`;
    }

    const config = {
        ...options,
        headers: requestHeaders,
        body: requestBody,
    };
    
    // 对于 GET 或 HEAD 请求，移除 body
    if (config.method === 'GET' || config.method === 'HEAD') {
        delete config.body;
    }

    try {
        // 使用 targetUrl 而不是 API_BASE_URL + endpoint
        const response = await fetch(targetUrl, config);
        console.log(`[API Request] URL: ${targetUrl}, Status: ${response.status}`);

        if (!response.ok) {
            // 尝试解析错误响应体
            let errorData;
            try {
                console.error(`[API Error] URL: ${targetUrl}, Status: ${response.status}, StatusText: ${response.statusText}`);
                errorData = await response.json();
            } catch (e) {
                // 如果响应体不是 JSON 或为空
                errorData = { message: response.statusText || '请求失败' };
            }
            
            // 如果是 401 未授权，可能需要触发登出逻辑
            if (response.status === 401 && endpoint !== '/login') { // 防止登录请求 401 时无限循环
                authStore.logout();
                // router.push({ name: 'Login' }); // 跳转应在调用方或路由守卫处理
                // 或者抛出一个特定类型的错误，让上层处理跳转
            }

            return Promise.reject({ status: response.status, ...errorData });
        }

        // 对于登录接口，token 在 X-Access-Token 头部，且状态码为 204
        if (endpoint === '/login' && response.status === 204 && response.headers.has('x-access-token')) {
            const loginToken = response.headers.get('x-access-token');
            // 后端不返回 user body，所以 user 需要从 token 解码或后续请求
            return Promise.resolve({ token: loginToken, user: {} }); // 返回空 user 对象
        }

        // 如果响应状态码是 204 (No Content) 且不是登录成功的情况
        if (response.status === 204) {
            return Promise.resolve({}); // 或 resolve(null)
        }

        return response.json();
    } catch (error) {
        console.error('API Service Error:', error);
        // 可以向上层抛出更通用的错误
        return Promise.reject(error.response ? error.response.data : { message: '网络错误或请求未能发出', status: error.status });
    } finally {
        activeRequests.delete(requestId); // 无论成功或失败，都从活跃请求 Set 中移除 ID
        appStore.decrementActiveRequests(); // 减少活跃请求计数器
    }
}

// 检查是否有任何请求正在进行中
export function hasActiveRequests() {
    return activeRequests.size > 0;
}

// 导出具体的 API 调用函数示例
export default {
    // 认证相关
    // login 的 body 是一个对象，例如 { password: 'your_api_key' }
    login: (formData) => request('/login', { method: 'POST', body: formData }),
    // verifyToken 方法，用于验证 token
    verifyToken: (token) => request('/verify-token', { method: 'POST', body: { token } }), // 假设后端有一个 /verify-token 接口

    // Key 管理 API
    getKeys: () => request(API_ENDPOINTS.KEYS.DATA, { method: 'GET' }),
    addKey: (keyData) => request(API_ENDPOINTS.KEYS.ADD, { method: 'POST', body: keyData }),
    updateKey: (keyString, updateData) => request(`${API_ENDPOINTS.KEYS.UPDATE}/${keyString}`, { method: 'PUT', body: updateData }),
    deleteKey: (keyString) => request(`${API_ENDPOINTS.KEYS.DELETE}/${keyString}`, { method: 'DELETE' }),

    // Context Management API
    getContextData: () => request(API_ENDPOINTS.CONTEXT.DATA, { method: 'GET' }),
    updateContextTTL: (ttlData) => request(API_ENDPOINTS.CONTEXT.UPDATE_TTL, { method: 'POST', body: ttlData }), // ttlData should be { ttl_seconds: value }
    deleteContext: (contextId) => request(API_ENDPOINTS.CONTEXT.DELETE, { method: 'POST', body: { context_id: contextId } }),

    // Config Management API
    getConfigInfo: () => request('/api/v1/config/info', { method: 'GET' }),
    updateConfig: (configData) => request('/api/v1/config/update', { method: 'POST', body: configData }),
    getMemoryModeWarning: () => request('/api/v1/config/memory-warning', { method: 'GET' }),

    // 更多 API 调用...
};

// 也可以按模块导出
// export const authService = { login, ... }
// export const keyService = { getKeys, ... }
