import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue'; // App.vue 已创建
import router from './router'; // router/index.js 已创建

// 导入全局样式 (如果需要，例如 reset.css 或全局 utility class)
// import './assets/main.css'; // main.css 稍后创建

const app = createApp(App); // 使用 App 组件
const pinia = createPinia();

app.use(pinia);
app.use(router); // 启用路由

app.mount('#app'); // 挂载应用

// 仅在开发或测试环境下将 Pinia 实例暴露给 window，方便调试和测试
if (process.env.NODE_ENV === 'development' || process.env.NODE_ENV === 'test') {
  window.__pinia = pinia;
}

// 为了能先运行，暂时只初始化 Pinia 并导出 app 实例
// 实际挂载和路由使用将在 App.vue 和 router/index.js 创建后完成
// console.log('Vue app initialized with Pinia and Router, and mounted.'); // 日志可以调整或移除

// export default app; // 通常 main.js 不需要导出 app 实例，除非有特殊用途
