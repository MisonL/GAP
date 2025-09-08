import { defineStore } from 'pinia';
import apiService from '@/services/apiService';
import { useAppStore } from './appStore';

export const useKeysStore = defineStore('keys', {
    state: () => ({
        keys: [],
        loading: false,
        error: null,
    }),
    
    getters: {
        activeKeys: (state) => state.keys.filter(key => key.is_enabled),
        inactiveKeys: (state) => state.keys.filter(key => !key.is_enabled),
    },
    
    actions: {
        async fetchKeys() {
            const appStore = useAppStore();
            this.loading = true;
            this.error = null;
            
            try {
                appStore.incrementActiveRequests();
                const response = await apiService.getKeys();
                this.keys = response.keys || [];
            } catch (error) {
                console.error('获取Keys失败:', error);
                this.error = error.message || '获取Keys失败';
                appStore.showNotification(this.error, 'error');
            } finally {
                this.loading = false;
                appStore.decrementActiveRequests();
            }
        },
        
        async addKey(keyData) {
            const appStore = useAppStore();
            try {
                appStore.incrementActiveRequests();
                const response = await apiService.addKey(keyData);
                await this.fetchKeys(); // 重新获取列表
                appStore.showNotification('API Key添加成功', 'success');
                return response;
            } catch (error) {
                console.error('添加Key失败:', error);
                appStore.showNotification(error.message || '添加Key失败', 'error');
                throw error;
            } finally {
                appStore.decrementActiveRequests();
            }
        },
        
        async updateKey(keyString, updateData) {
            const appStore = useAppStore();
            try {
                appStore.incrementActiveRequests();
                const response = await apiService.updateKey(keyString, updateData);
                await this.fetchKeys(); // 重新获取列表
                appStore.showNotification('API Key更新成功', 'success');
                return response;
            } catch (error) {
                console.error('更新Key失败:', error);
                appStore.showNotification(error.message || '更新Key失败', 'error');
                throw error;
            } finally {
                appStore.decrementActiveRequests();
            }
        },
        
        async deleteKey(keyString) {
            const appStore = useAppStore();
            try {
                appStore.incrementActiveRequests();
                await apiService.deleteKey(keyString);
                await this.fetchKeys(); // 重新获取列表
                appStore.showNotification('API Key删除成功', 'success');
            } catch (error) {
                console.error('删除Key失败:', error);
                appStore.showNotification(error.message || '删除Key失败', 'error');
                throw error;
            } finally {
                appStore.decrementActiveRequests();
            }
        },
        
        async toggleKeyStatus(keyString, currentStatus) {
            return this.updateKey(keyString, { is_enabled: !currentStatus });
        },
    },
});