import { defineStore } from 'pinia';
import apiService from '@/services/apiService';
import { useAppStore } from './appStore';

export const useContextStore = defineStore('context', {
    state: () => ({
        contexts: [],
        loading: false,
        error: null,
        ttl: 7 * 24 * 3600, // 默认TTL 7天
    }),
    
    getters: {
        contextCount: (state) => state.contexts.length,
        expiredContexts: (state) => state.contexts.filter(ctx => new Date(ctx.expires_at) < new Date()),
    },
    
    actions: {
        async fetchContexts() {
            const appStore = useAppStore();
            this.loading = true;
            this.error = null;
            
            try {
                appStore.incrementActiveRequests();
                const response = await apiService.getContextData();
                this.contexts = response.contexts || [];
            } catch (error) {
                // eslint-disable-next-line no-console
                console.error('获取上下文失败:', error);
                this.error = error.message || '获取上下文失败';
                appStore.showNotification(this.error, 'error');
            } finally {
                this.loading = false;
                appStore.decrementActiveRequests();
            }
        },
        
        async updateTTL(newTTL) {
            const appStore = useAppStore();
            try {
                appStore.incrementActiveRequests();
                await apiService.updateContextTTL({ ttl_seconds: newTTL });
                this.ttl = newTTL;
                await this.fetchContexts(); // 重新获取数据
                appStore.showNotification('TTL更新成功', 'success');
            } catch (error) {
                // eslint-disable-next-line no-console
                console.error('更新TTL失败:', error);
                appStore.showNotification(error.message || '更新TTL失败', 'error');
                throw error;
            } finally {
                appStore.decrementActiveRequests();
            }
        },
        
        async deleteContext(contextId) {
            const appStore = useAppStore();
            try {
                appStore.incrementActiveRequests();
                await apiService.deleteContext(contextId);
                await this.fetchContexts(); // 重新获取数据
                appStore.showNotification('上下文删除成功', 'success');
            } catch (error) {
                // eslint-disable-next-line no-console
                console.error('删除上下文失败:', error);
                appStore.showNotification(error.message || '删除上下文失败', 'error');
                throw error;
            } finally {
                appStore.decrementActiveRequests();
            }
        },
        
        async deleteAllContexts() {
            const appStore = useAppStore();
            try {
                appStore.incrementActiveRequests();
                const promises = this.contexts.map(ctx => 
                    apiService.deleteContext(ctx.context_id)
                );
                await Promise.all(promises);
                await this.fetchContexts();
                appStore.showNotification('所有上下文已删除', 'success');
            } catch (error) {
                // eslint-disable-next-line no-console
                console.error('批量删除上下文失败:', error);
                appStore.showNotification(error.message || '批量删除失败', 'error');
                throw error;
            } finally {
                appStore.decrementActiveRequests();
            }
        },
    },
});