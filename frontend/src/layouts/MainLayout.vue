<template>
  <div class="min-h-screen bg-gray-50 dark:bg-gray-950 transition-colors duration-300">
    <!-- Navigation -->
    <AppNavigation />

    <!-- Main Content -->
    <div class="md:pl-64 flex flex-col min-h-screen">
      <!-- Header (Mobile Only or simplified for Desktop) -->
      <header class="sticky top-0 z-40 bg-white/80 dark:bg-gray-900/80 backdrop-blur-md border-b border-gray-200 dark:border-gray-800 md:hidden">
        <div class="flex items-center justify-between px-4 py-3">
          <span class="text-lg font-bold text-gray-800 dark:text-white">Gemini Proxy</span>
          <ViewSwitcher />
        </div>
      </header>

      <!-- Desktop Header Actions (Optional, if needed outside sidebar) -->
      <div class="hidden md:flex justify-end p-4 absolute top-0 right-0 z-40">
        <ViewSwitcher />
      </div>

      <!-- Page Content -->
      <main class="flex-1 p-4 md:p-8 pb-24 md:pb-8 max-w-7xl mx-auto w-full">
        <router-view v-slot="{ Component }">
          <transition
            name="fade"
            mode="out-in"
          >
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <GlobalNotification />
  </div>
</template>

<script setup>
import AppNavigation from '@/components/AppNavigation.vue';
import ViewSwitcher from '@/components/ViewSwitcher.vue';
import GlobalNotification from '@/components/common/GlobalNotification.vue';
</script>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
