import { defineStore } from 'pinia';
import { NOTIFICATION_TYPES } from '../constants/notificationConstants';

export const useNotificationStore = defineStore('notification', {
  state: () => ({
    notification: {
      message: '',
      type: NOTIFICATION_TYPES.INFO, // 使用常量
    },
    duration: 3000, // 通知显示时长，单位毫秒
  }),
  actions: {
    /**
     * 显示通知消息
     * @param {string} message - 通知内容
     * @param {string} type - 通知类型 ('success', 'error', 'warning', 'info')
     * @param {number} duration - 通知显示时长（可选），单位毫秒，默认为3000ms
     */
    showNotification(message, type = NOTIFICATION_TYPES.INFO, duration) {
      this.notification.message = message;
      this.notification.type = type;
      if (duration) {
        this.duration = duration;
      } else {
        this.duration = 3000; // 恢复默认时长
      }
    },
    /**
     * 清除通知消息
     */
    clearNotification() {
      this.notification.message = '';
      this.notification.type = NOTIFICATION_TYPES.INFO;
    },
  },
});