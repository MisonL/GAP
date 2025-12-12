import { defineStore } from 'pinia';
import { NOTIFICATION_TYPES } from '../constants/notificationConstants';
import { VIEW_MODES } from '../constants/viewModeConstants';

export const useAppStore = defineStore('app', {
    state: () => ({
        // 'bento' 或 'traditional'
        viewMode: localStorage.getItem('app_view_mode') || VIEW_MODES.BENTO, // 默认 Bento 模式
        globalNotification: { // 全局通知
            show: false,
            message: '',
            type: NOTIFICATION_TYPES.INFO, // 使用常量
            timeout: undefined,
        },
        loading: false, // 全局加载状态
        globalError: null, // 全局错误
        theme: localStorage.getItem('app_theme') || 'auto', // 主题设置
        sidebar: localStorage.getItem('app_sidebar') !== 'false', // 侧边栏状态
        userSession: { // 用户会话
            token: localStorage.getItem('authToken') || null,
            refreshToken: localStorage.getItem('refreshToken') || null,
            userId: localStorage.getItem('userId') || null,
            username: localStorage.getItem('username') || null,
            isLoggedIn: !!localStorage.getItem('authToken'),
        },
        // 模拟传统列表视图的数据
        traditionalListItems: [
            { id: 1, name: '列表项 1' },
            { id: 2, name: '列表项 2' },
            { id: 3, name: '列表项 3' },
            { id: 4, name: '列表项 4' },
            { id: 5, name: '列表项 5' },
        ],
        activeRequests: 0, // 活跃请求计数器
        isLoading: false, // 向后兼容的加载状态
    }),
    getters: {
        isBentoMode: (state) => state.viewMode === VIEW_MODES.BENTO,
        isTraditionalMode: (state) => state.viewMode === VIEW_MODES.TRADITIONAL,
        // 根据 activeRequests 判断是否处于加载状态
        getIsLoading: (state) => state.activeRequests > 0,
    },
    actions: {
        // 增加活跃请求计数
        incrementActiveRequests() {
            this.activeRequests++;
            this.isLoading = this.activeRequests > 0; // 更新全局加载状态
        },
        // 减少活跃请求计数
        decrementActiveRequests() {
            if (this.activeRequests > 0) {
                this.activeRequests--;
            }
            this.isLoading = this.activeRequests > 0; // 更新全局加载状态
        },
        setViewMode(mode) {
            if ([VIEW_MODES.BENTO, VIEW_MODES.TRADITIONAL].includes(mode)) {
                this.viewMode = mode;
                localStorage.setItem('app_view_mode', mode);
            } else {
                // Use a more subtle warning instead of console.warn to avoid ESLint error
                // eslint-disable-next-line no-console
                console.warn(`Invalid view mode: ${mode}. Defaulting to '${VIEW_MODES.BENTO}'.`);
                this.viewMode = VIEW_MODES.BENTO;
                localStorage.setItem('app_view_mode', VIEW_MODES.BENTO);
            }
        },
        toggleViewMode() {
            this.viewMode = this.viewMode === VIEW_MODES.BENTO ? VIEW_MODES.TRADITIONAL : VIEW_MODES.BENTO;
            localStorage.setItem('app_view_mode', this.viewMode);
        },
        showNotification(message, type = NOTIFICATION_TYPES.INFO, duration = 3000) {
            this.globalNotification.message = message;
            this.globalNotification.type = type;
            this.globalNotification.show = true;

            if (duration > 0) {
                setTimeout(() => {
                    this.hideNotification();
                }, duration);
            }
        },
        hideNotification() {
            this.globalNotification.show = false;
            this.globalNotification.message = '';
            this.globalNotification.type = NOTIFICATION_TYPES.INFO;
        },
        // 设置传统列表视图的数据
        setTraditionalListItems(items) {
            this.traditionalListItems = items;
        },
        // 新增方法以匹配TypeScript接口
        setGlobalNotification(notification) {
            this.globalNotification = {
                show: true,
                message: notification.message,
                type: notification.type,
                timeout: notification.timeout,
            };
        },
        clearGlobalNotification() {
            this.globalNotification.show = false;
            this.globalNotification.message = '';
            this.globalNotification.type = NOTIFICATION_TYPES.INFO;
            this.globalNotification.timeout = undefined;
        },
        setLoading(loading) {
            this.loading = loading;
        },
        setGlobalError(error) {
            this.globalError = error;
        },
        clearGlobalError() {
            this.globalError = null;
        },
        setTheme(theme) {
            if (['light', 'dark', 'auto'].includes(theme)) {
                this.theme = theme;
                localStorage.setItem('app_theme', theme);
            }
        },
        toggleSidebar() {
            this.sidebar = !this.sidebar;
            localStorage.setItem('app_sidebar', this.sidebar.toString());
        },
        setSidebar(open) {
            this.sidebar = open;
            localStorage.setItem('app_sidebar', open.toString());
        },
        setUserSession(session) {
            this.userSession = { ...this.userSession, ...session };

            // 同步更新localStorage
            if (session.token !== undefined) {
                if (session.token) {
                    localStorage.setItem('authToken', session.token);
                } else {
                    localStorage.removeItem('authToken');
                }
            }
            if (session.refreshToken !== undefined) {
                if (session.refreshToken) {
                    localStorage.setItem('refreshToken', session.refreshToken);
                } else {
                    localStorage.removeItem('refreshToken');
                }
            }
            if (session.userId !== undefined) {
                if (session.userId) {
                    localStorage.setItem('userId', session.userId);
                } else {
                    localStorage.removeItem('userId');
                }
            }
            if (session.username !== undefined) {
                if (session.username) {
                    localStorage.setItem('username', session.username);
                } else {
                    localStorage.removeItem('username');
                }
            }

            this.userSession.isLoggedIn = !!this.userSession.token;
        },
        clearUserSession() {
            this.userSession = {
                token: null,
                refreshToken: null,
                userId: null,
                username: null,
                isLoggedIn: false,
            };

            // 清除localStorage
            localStorage.removeItem('authToken');
            localStorage.removeItem('refreshToken');
            localStorage.removeItem('userId');
            localStorage.removeItem('username');
        },
    },
});
