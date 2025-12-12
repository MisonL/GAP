import { describe, it, expect } from 'vitest'
import App from '@/App.vue'

// 简单烟雾测试：确认根组件可以被正常导入

describe('App root component', () => {
  it('should be defined', () => {
    expect(App).toBeTruthy()
  })
})
