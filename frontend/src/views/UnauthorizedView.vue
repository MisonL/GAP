<template>
  <div class="unauthorized-view">
    <h1>401 - 未授权</h1>
    <p>抱歉，您需要登录才能访问此页面。</p>
    <router-link to="/login">
      返回登录页
    </router-link>
  </div>
</template>

<script setup>
// 可以在这里添加一些逻辑，例如记录日志，例如使用日志服务
// 注意：避免在生产环境中直接使用 console.log
</script>

<style scoped>
.unauthorized-view {
  text-align: center;
  padding: 50px;
  color: #e67e22; /* 橙色调，表示警告 */
}

h1 {
  font-size: 4em; /* 比 404 小一些 */
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