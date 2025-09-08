# GAP 前端应用

> Gemini API Proxy 前端 - 基于 Vue 3 + TypeScript 的现代化 Web 应用

## 🚀 快速开始

### 环境要求
- Node.js 18+
- npm 9+ 或 yarn 1.22+

### 安装依赖
```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 或使用 yarn
yarn install
```

### 开发环境启动
```bash
# 启动开发服务器
npm run dev

# 启动并指定端口
npm run dev -- --port 3000

# 启动并监听所有接口
npm run dev-host
```

### 构建生产版本
```bash
# 构建生产版本
npm run build

# 预览构建结果
npm run preview

# 构建并分析包大小
npm run analyze
```

## 📁 项目结构

```
frontend/
├── 📁 src/                    # 源代码目录
│   ├── 📄 main.js            # 应用入口
│   ├── 📄 App.vue            # 根组件
│   ├── 📁 assets/            # 静态资源
│   ├── 📁 components/        # Vue组件
│   │   ├── 📁 common/        # 通用组件
│   │   └── 📁 specific/      # 特定功能组件
│   ├── 📁 composables/       # 组合式函数
│   ├── 📁 constants/         # 常量定义
│   ├── 📁 layouts/           # 布局组件
│   ├── 📁 router/            # Vue Router配置
│   ├── 📁 services/          # API服务层
│   ├── 📁 stores/            # Pinia状态管理
│   ├── 📁 types/             # TypeScript类型定义
│   └── 📁 views/             # 页面视图
├── 📁 public/                # 公共资源
├── 📁 tests/                 # 测试文件
├── 📁 scripts/               # 构建脚本
└── 📄 package.json          # 项目配置
```

## 🛠️ 开发命令

### 开发服务器
```bash
# 开发模式
npm run dev

# 开发模式(指定端口)
npm run dev -- --port 5173

# 开发模式(监听所有接口)
npm run dev-host
```

### 代码质量
```bash
# 代码检查
npm run lint

# 自动修复
npm run lint -- --fix

# 格式化代码
npm run format

# 类型检查
npm run type-check
```

### 测试
```bash
# 运行单元测试
npm run test:unit

# 运行端到端测试
npm run test:e2e

# 运行带UI的测试
npm run test:unit -- --ui

# 运行带覆盖率的测试
npm run test:coverage
```

### 构建和部署
```bash
# 构建生产版本
npm run build

# 预览构建结果
npm run preview

# 构建并分析包大小
npm run analyze

# 构建并部署到服务器
npm run build && npm run preview
```

## 🎯 技术栈

### 核心框架
- **Vue 3** - 渐进式JavaScript框架
- **TypeScript** - 类型安全的JavaScript
- **Vite** - 下一代前端构建工具

### UI组件库
- **Element Plus** - Vue 3组件库
- **Tailwind CSS** - 实用优先的CSS框架
- **Heroicons** - 精美SVG图标

### 状态管理
- **Pinia** - Vue状态管理
- **Vue Router** - 官方路由管理器

### 工具库
- **Axios** - HTTP客户端
- **VueUse** - Vue组合式工具库
- **Day.js** - 日期处理库
- **ECharts** - 图表可视化

## 🎨 功能特性

### 核心功能
- **API密钥管理** - 密钥添加、编辑、删除
- **使用统计** - 实时API使用数据
- **缓存管理** - Redis缓存监控和清理
- **对话历史** - 上下文存储和检索
- **响应式UI** - 移动端完美适配

### 界面特性
- **深色/浅色主题** - 自动切换
- **实时通知** - 操作反馈
- **数据可视化** - 图表和统计
- **搜索过滤** - 快速查找
- **批量操作** - 高效管理

## 🔧 开发配置

### 环境变量
创建 `.env` 文件：
```bash
# API基础URL
VITE_API_BASE_URL=http://localhost:8000

# 开发模式
VITE_DEV_MODE=true

# 功能开关
VITE_ENABLE_ANALYTICS=false
```

### VS Code配置
安装推荐扩展：
- Vue Language Features (Volar)
- TypeScript Vue Plugin
- ESLint
- Prettier
- Tailwind CSS IntelliSense

### 代码风格
项目使用：
- **ESLint** - 代码规范
- **Prettier** - 代码格式化
- **Stylelint** - CSS规范
- **Husky** - Git hooks

## 📱 响应式设计

### 断点系统
- **xs**: < 768px (手机)
- **sm**: ≥ 768px (平板)
- **md**: ≥ 992px (小型桌面)
- **lg**: ≥ 1200px (桌面)
- **xl**: ≥ 1920px (大型桌面)

### 组件适配
- **移动端优先** - 移动优先设计
- **触摸优化** - 大按钮和手势支持
- **性能优化** - 懒加载和代码分割

## 🧪 测试策略

### 测试类型
- **单元测试** - 组件和工具函数
- **集成测试** - API交互测试
- **端到端测试** - 用户流程测试
- **视觉测试** - UI一致性测试

### 测试命令
```bash
# 运行所有测试
npm run test

# 运行特定测试
npm run test:unit Button.spec.ts

# 调试测试
npm run test:unit -- --debug
```

## 🚀 部署指南

### 环境构建
```bash
# 生产构建
npm run build

# 构建分析
npm run analyze

# 部署到服务器
rsync -avz dist/ user@server:/var/www/gap/
```

### Docker部署
```bash
# 构建镜像
docker build -t gap-frontend .

# 运行容器
docker run -p 80:80 gap-frontend
```

### CI/CD配置
```yaml
# GitHub Actions示例
name: Deploy Frontend
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      - run: npm ci
      - run: npm run build
      - run: npm run test:unit
```

## 📊 性能优化

### 构建优化
- **代码分割** - 路由级和组件级
- **懒加载** - 图片和组件
- **缓存策略** - 浏览器和CDN缓存
- **压缩优化** - Gzip和Brotli

### 运行时优化
- **虚拟滚动** - 大数据列表
- **防抖节流** - 输入和滚动事件
- **内存管理** - 组件卸载清理

## 🔍 调试指南

### 开发调试
```bash
# 启用Vue DevTools
export VITE_DEVTOOLS=true

# 查看构建分析
npm run analyze

# 性能监控
npm run dev -- --profile
```

### 生产调试
```bash
# 查看控制台错误
# 使用Sentry监控
# 性能分析工具
```

## 🤝 贡献指南

### 开发规范
1. **代码规范** - 遵循ESLint规则
2. **提交规范** - 使用Conventional Commits
3. **分支规范** - feature/前缀
4. **测试规范** - 覆盖率>80%

### 提交规范
```bash
# 提交格式
git commit -m "feat: add user authentication"
git commit -m "fix: resolve button click issue"
git commit -m "docs: update API documentation"
```

## 📞 支持

- **Issues**: [GitHub Issues](https://github.com/MisonL/GAP/issues)
- **Discussions**: [GitHub Discussions](https://github.com/MisonL/GAP/discussions)
- **邮箱**: 1360962086@qq.com
- **文档**: [项目文档](../docs/)

## 📦 相关命令速查

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动开发服务器 |
| `npm run build` | 构建生产版本 |
| `npm run test:unit` | 运行单元测试 |
| `npm run test:e2e` | 运行端到端测试 |
| `npm run lint` | 代码检查 |
| `npm run format` | 代码格式化 |
| `npm run analyze` | 构建分析 |