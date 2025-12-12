<template>
  <nav class="app-navigation">
    <!-- Desktop Sidebar -->
    <div class="hidden md:flex flex-col w-64 h-screen fixed left-0 top-0 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 z-50">
      <div class="p-6 flex items-center gap-3 border-b border-gray-200 dark:border-gray-800">
        <div class="text-2xl animate-bounce">
          🚀
        </div>
        <span class="text-xl font-bold text-gray-800 dark:text-white">Gemini Proxy</span>
      </div>
      
      <ul class="flex-1 flex flex-col gap-2 p-4">
        <li
          v-for="item in navItems"
          :key="item.name"
        >
          <router-link 
            :to="{ name: item.routeName }" 
            class="flex items-center gap-3 px-4 py-3 rounded-xl text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-primary transition-all duration-200"
            active-class="bg-primary/10 text-primary font-medium"
          >
            <span class="text-xl">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </router-link>
        </li>
        
        <li>
          <a
            href="/docs"
            target="_blank"
            class="flex items-center gap-3 px-4 py-3 rounded-xl text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-primary transition-all duration-200"
          >
            <span class="text-xl">📚</span>
            <span>API 文档</span>
          </a>
        </li>
      </ul>

      <div class="p-4 border-t border-gray-200 dark:border-gray-800">
        <button 
          class="flex items-center gap-3 px-4 py-3 w-full rounded-xl text-red-500 hover:bg-red-50 dark:hover:bg-red-900/10 transition-all duration-200"
          @click="handleLogout" 
        >
          <span class="text-xl">🚪</span>
          <span>退出登录</span>
        </button>
      </div>
    </div>

    <!-- Mobile Bottom Nav -->
    <div class="md:hidden fixed bottom-0 left-0 right-0 bg-white/90 dark:bg-gray-900/90 backdrop-blur-lg border-t border-gray-200 dark:border-gray-800 z-50 pb-safe">
      <ul class="flex justify-around items-center p-2">
        <li
          v-for="item in navItems"
          :key="item.name"
        >
          <router-link 
            :to="{ name: item.routeName }" 
            class="flex flex-col items-center gap-1 p-2 rounded-lg text-gray-500 dark:text-gray-400"
            active-class="text-primary"
          >
            <span class="text-2xl">{{ item.icon }}</span>
            <span class="text-xs font-medium">{{ item.label }}</span>
          </router-link>
        </li>
        <li>
          <button
            class="flex flex-col items-center gap-1 p-2 rounded-lg text-gray-500 dark:text-gray-400"
            @click="handleLogout"
          >
            <span class="text-2xl">🚪</span>
            <span class="text-xs font-medium">退出</span>
          </button>
        </li>
      </ul>
    </div>
  </nav>
</template>

<script setup>
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/authStore';

const router = useRouter();
const authStore = useAuthStore();

const navItems = [
  { name: 'dashboard', routeName: 'dashboard', label: '仪表盘', icon: '📊' },
  { name: 'keys', routeName: 'keys', label: 'Keys', icon: '🔑' },
  { name: 'context', routeName: 'context', label: '上下文', icon: '💾' },
  { name: 'report', routeName: 'report', label: '报告', icon: '📈' },
  { name: 'config', routeName: 'config', label: '配置', icon: '⚙️' },
];

const handleLogout = () => {
  authStore.logout();
  router.push({ name: 'Login' });
};
</script>

<style scoped>
.pb-safe {
  padding-bottom: env(safe-area-inset-bottom);
}
</style>
