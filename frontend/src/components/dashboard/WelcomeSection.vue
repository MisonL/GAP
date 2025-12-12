<template>
  <section class="welcome-section">
    <div class="welcome-content">
      <h2 class="welcome-title">
        欢迎使用 Gemini API 代理
        <span class="wave-emoji">👋</span>
      </h2>
      <p class="welcome-subtitle">
        现代化的API密钥管理和上下文缓存系统
      </p>
    </div>
  </section>
</template>

<style scoped>
.welcome-section {
  text-align: center;
  margin-bottom: 3rem;
}

.welcome-content {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border-radius: var(--radius-xl);
  padding: 2rem;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.welcome-title {
  font-size: 2.5rem;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.wave-emoji {
  animation: wave 2s ease-in-out infinite;
}

@keyframes wave {
  0%, 100% { transform: rotate(0deg); }
  25% { transform: rotate(20deg); }
  75% { transform: rotate(-20deg); }
}

.welcome-subtitle {
  font-size: 1.125rem;
  color: var(--text-secondary);
  margin: 0;
}
</style>
