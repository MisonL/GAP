import { createRouter, createWebHistory } from 'vue-router';
import MainLayout from '@/layouts/MainLayout.vue'; // 导入主布局
// 路由组件现在使用懒加载方式导入，以优化首次加载性能

const routes = [
    {
        path: '/login',
        name: 'login',
        component: () => import('@/views/LoginView.vue'), // 启用登录视图懒加载
        meta: { requiresAuth: false } // 明确允许匿名访问
    },
    {
        path: '/',
        component: MainLayout, // 使用 MainLayout
        meta: { requiresAuth: true },
        children: [
            {
                path: '', // 默认子路由，当访问 / 时渲染
                name: 'dashboard', // 更改名称为 dashboard
                component: () => import('@/views/Dashboard.vue'), // 使用 DashboardView 作为默认首页，并启用懒加载
                meta: { requiresAuth: true } // 已添加
            },
            {
                path: 'home', // 将 HomeView 移到 /home 路径下 (可选)
                name: 'Home',
                component: () => import('@/views/HomeView.vue') // 启用 HomeView 懒加载
            },
            {
                path: 'keys', // 路径可以自定义
                name: 'keys',
                component: () => import('@/views/ManageKeysView.vue'), // 启用 Key 管理视图懒加载
                meta: { requiresAuth: true } // 添加认证标记
            },
            {
                path: 'context',
                name: 'context',
                component: () => import('@/views/ManageContextView.vue'), // 启用上下文管理视图懒加载
                meta: { requiresAuth: true } // 添加认证标记
            },
            {
                path: 'report',
                name: 'report',
                component: () => import('@/views/ReportView.vue'), // 启用周期报告视图懒加载
                meta: { requiresAuth: true } // 添加认证标记
            },
            {
                path: 'traditional-list',
                name: 'traditional-list',
                component: () => import('@/views/TraditionalListView.vue'),
                meta: { requiresAuth: true } // 添加认证标记
            },
            {
                path: 'config',
                name: 'config',
                component: () => import('@/views/ConfigView.vue'),
                meta: { requiresAuth: true } // 添加认证标记
            }
        ]
    },
    // 错误页面
    {
        path: '/unauthorized',
        name: 'Unauthorized',
        component: () => import('@/views/UnauthorizedView.vue') // 启用 401 页面懒加载
    },
     {
        path: '/forbidden',
        name: 'Forbidden',
        component: () => import('@/views/ForbiddenView.vue') // 启用 403 页面懒加载
    },
    // 404 页面 (必须放在最后)
    {
        path: '/:pathMatch(.*)*',
        name: 'NotFound',
        component: () => import('@/views/NotFoundView.vue') // 启用 404 页面懒加载
    }
];

const router = createRouter({
    history: createWebHistory(import.meta.env.BASE_URL || '/'), // Vite 项目通常这样设置 history
    routes
});

// 导航守卫 (示例，逻辑待填充)
import { useAuthStore } from '@/stores/authStore';

router.beforeEach((to, from, next) => {
  const authStore = useAuthStore();
  
  // 添加调试日志
  console.log(`[路由守卫] 目标路径: ${to.path}, 认证状态: ${authStore.isAuthenticated}`);
  
  if (to.matched.some(record => record.meta.requiresAuth)) {
    if (!authStore.isAuthenticated) {
      console.log(`[路由守卫] 重定向到登录页，原因: 需要认证`);
      next({
        path: '/login',
        query: { redirect: to.fullPath }
      });
    } else {
      next();
    }
  } else if (to.path === '/login' && authStore.isAuthenticated) {
    console.log(`[路由守卫] 重定向到首页，原因: 已认证用户访问登录页`);
    next('/');
  } else {
    next();
  }
});

// 可以在路由创建后添加一些错误处理或日志
router.onError(error => {
    console.error('[Router Error]', error);
});

export default router;
