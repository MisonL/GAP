<template>
  <transition name="notification">
    <div v-if="isVisible" :class="['global-notification', typeClass]">
      <div class="notification-content">
        <p>{{ message }}</p>
        <button @click="closeNotification" class="close-button">×</button>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue';
import { useNotificationStore } from '../../stores/notificationStore'; // 引入通知状态管理

const notificationStore = useNotificationStore();

const isVisible = ref(false);
const message = ref('');
const type = ref('info'); // 默认类型

let timeoutId = null; // 用于存储自动关闭的定时器ID

// 计算属性，根据通知类型返回对应的CSS类
const typeClass = computed(() => {
  return `notification-${type.value}`;
});

// 监听通知状态的变化
watch(() => notificationStore.notification, (newNotification) => {
  if (newNotification.message) {
    message.value = newNotification.message;
    type.value = newNotification.type || 'info';
    isVisible.value = true;
    startAutoClose(); // 启动自动关闭
  } else {
    closeNotification(); // 如果消息为空，则关闭通知
  }
}, { deep: true });

// 启动自动关闭定时器
const startAutoClose = () => {
  clearTimeout(timeoutId); // 清除之前的定时器
  timeoutId = setTimeout(() => {
    closeNotification();
  }, notificationStore.duration); // 使用store中定义的持续时间
};

// 关闭通知
const closeNotification = () => {
  isVisible.value = false;
  clearTimeout(timeoutId); // 清除定时器
  notificationStore.clearNotification(); // 清除store中的通知信息
};

// 组件挂载时，如果已有通知，则显示
onMounted(() => {
  if (notificationStore.notification.message) {
    message.value = notificationStore.notification.message;
    type.value = notificationStore.notification.type || 'info';
    isVisible.value = true;
    startAutoClose();
  }
});
</script>

<style scoped>
.global-notification {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  padding: 12px 20px;
  border-radius: 8px;
  color: white;
  font-size: 16px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  min-width: 300px;
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
}

.notification-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.notification-content p {
  margin: 0;
  flex-grow: 1;
}

.close-button {
  background: none;
  border: none;
  color: white;
  font-size: 20px;
  cursor: pointer;
  margin-left: 15px;
  padding: 0 5px;
  line-height: 1;
}

/* 通知类型样式 */
.notification-success {
  background-color: #4CAF50; /* 绿色 */
}

.notification-error {
  background-color: #F44336; /* 红色 */
}

.notification-warning {
  background-color: #FFC107; /* 橙色 */
  color: #333; /* 警告文本颜色 */
}

.notification-info {
  background-color: #2196F3; /* 蓝色 */
}

/* 动画效果 */
.notification-enter-active, .notification-leave-active {
  transition: all 0.5s ease;
}

.notification-enter-from, .notification-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-30px);
}

.notification-enter-to, .notification-leave-from {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}
</style>