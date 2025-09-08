<template>
  <div class="forbidden-view">
    <h1>403 - 禁止访问</h1>
    <p>抱歉，您没有权限访问此页面。</p>
    <router-link to="/">返回首页</router-link>
  </div>
</template>

<script setup>
// 可以在这里添加一些逻辑，例如记录日志
console.log('[ForbiddenView.vue] <script setup> executed.');
</script>

<style scoped>
.forbidden-view {
  text-align: center;
  padding: 50px;
  color: #c0392b; /* 红色调，表示禁止 */
}

h1 {
  font-size: 4em; /* 与 401 类似 */
  margin-bottom: 10px;
}

p {
  font-size: 1.4em;
  color: #555;
  margin-bottom: 20px;
}

a {
  font-size: 1.2em;
  color: #3498db;
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}
</style>