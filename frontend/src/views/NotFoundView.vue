<template>
  <div class="not-found-view">
    <h1>404</h1>
    <p>抱歉，您访问的页面不存在。</p>
    <router-link to="/">返回首页</router-link>
  </div>
</template>

<script setup>
console.log('[NotFoundView.vue] <script setup> executed.');
</script>

<style scoped>
.not-found-view {
  text-align: center;
  padding: 50px;
}

h1 {
  font-size: 6em;
  color: #e74c3c;
  margin-bottom: 10px;
}

p {
  font-size: 1.5em;
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