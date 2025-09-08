# 🚀 GAP 部署指南

本指南详细介绍了如何使用 `deploy.sh` 脚本进行一键部署，支持 Docker 和本地 uv 两种模式。

## 📋 部署前准备

### 系统要求
- **Docker模式**: Docker 20.10+ 和 Docker Compose 2.0+
- **本地模式**: Python 3.8+ 和 Node.js 18+

### 必需文件
确保项目根目录包含以下文件：
- `.env` 或 `.env.example` - 环境变量配置
- `backend/requirements.txt` - Python依赖
- `frontend/package.json` - Node.js依赖

## 🐳 Docker部署模式

### 快速开始
```bash
# 使用默认Docker部署
./deploy.sh docker

# 或简写
./deploy.sh
```

### 详细步骤
1. **环境检查**: 自动检测Docker和Docker Compose
2. **端口清理**: 自动清理占用7860端口的容器
3. **镜像构建**: 使用多阶段构建优化镜像大小
4. **服务启动**: 启动包含前后端的完整服务栈
5. **健康检查**: 自动验证服务是否正常运行

### Docker服务管理
```bash
# 查看服务状态
cd deployment/docker && docker-compose ps

# 查看实时日志
cd deployment/docker && docker-compose logs -f

# 停止服务
cd deployment/docker && docker-compose down

# 清理所有资源
cd deployment/docker && docker-compose down --volumes --remove-orphans
```

## 🔧 本地uv部署模式

### 快速开始
```bash
# 使用本地uv部署
./deploy.sh local
```

### 详细步骤
1. **环境检查**: 自动检测Python 3.8+和uv工具
2. **自动安装**: 如未安装uv，自动从官方脚本安装
3. **虚拟环境**: 自动创建和管理Python虚拟环境
4. **依赖安装**: 使用uv快速安装所有Python依赖
5. **数据库检查**: 验证数据库连接和运行迁移
6. **前后端启动**: 分别启动后端API和前端服务

### 本地服务管理
```bash
# 查看后端日志
tail -f logs/backend.log

# 查看前端日志
tail -f logs/frontend.log

# 停止所有服务
./deploy.sh stop

# 手动重启后端
pkill -f "uvicorn.*gap"
cd backend && source .venv/bin/activate && uvicorn src.gap.main:app --reload
```

## ⚙️ 环境变量配置

### 必需变量
```bash
# 数据库配置
DATABASE_URL=postgresql://user:pass@localhost:5432/gap_dev

# Redis配置
REDIS_URL=redis://localhost:6379/0

# 安全密钥
SECRET_KEY=your-very-secure-secret-key
JWT_SECRET_KEY=your-jwt-secret-key

# Gemini API密钥
GEMINI_API_KEY=your-gemini-api-key
```

### 部署相关变量
```bash
# 部署模式选择
KEY_STORAGE_MODE=database  # 或 memory
CONTEXT_STORAGE_MODE=database  # 或 memory

# 功能开关
ENABLE_NATIVE_CACHING=false
ENABLE_CONTEXT_COMPLETION=true

# 限流设置
MAX_REQUESTS_PER_MINUTE=60
MAX_REQUESTS_PER_DAY_PER_IP=600
```

## 🎯 部署模式对比

| 特性 | Docker模式 | 本地uv模式 |
|---|---|---|
| **隔离性** | 完全容器化隔离 | 系统级依赖 |
| **性能** | 中等（容器开销） | 高性能（原生） |
| **易用性** | 一键部署，无需配置 | 需要本地环境 |
| **维护** | 镜像更新即可 | 需要手动维护 |
| **资源占用** | 较高 | 较低 |
| **适用场景** | 生产环境、测试 | 开发环境、调试 |

## 🔍 故障排除

### Docker模式常见问题

#### 端口冲突
```bash
# 检查端口占用
sudo lsof -i :7860

# 强制清理占用端口的容器
./deploy.sh docker
```

#### 镜像构建失败
```bash
# 清理旧镜像后重试
docker system prune -a
./deploy.sh docker
```

#### 权限问题
```bash
# 修复Docker权限（Linux）
sudo usermod -aG docker $USER
# 重新登录后重试
```

### 本地模式常见问题

#### Python版本问题
```bash
# 检查Python版本
python3 --version

# 使用pyenv管理Python版本
pyenv install 3.11.0
pyenv global 3.11.0
```

#### uv安装问题
```bash
# 手动安装uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.cargo/env
```

#### 依赖安装失败
```bash
# 清理虚拟环境后重试
rm -rf backend/.venv
cd backend && uv venv && source .venv/bin/activate && uv pip install -r requirements.txt
```

## 📊 监控和日志

### 健康检查端点
- **后端健康检查**: http://localhost:8000/healthz
- **前端健康检查**: http://localhost:3000/health
- **Docker健康检查**: http://localhost:7860/healthz

### 日志文件位置
```
logs/
├── app.log          # 应用主日志
├── error.log        # 错误日志
├── access.log       # 访问日志
├── backend.log      # 本地模式后端日志
└── frontend.log     # 本地模式前端日志
```

### 性能监控
```bash
# Docker资源使用
docker stats

# 本地进程监控
htop
# 或
ps aux | grep gap
```

## 🔄 更新和回滚

### Docker更新
```bash
# 拉取最新代码
git pull origin main

# 重新部署
./deploy.sh docker
```

### 本地更新
```bash
# 拉取最新代码
git pull origin main

# 更新依赖
cd backend && source .venv/bin/activate && uv pip install -r requirements.txt
cd ../frontend && npm install

# 重启服务
./deploy.sh local
```

## 🛡️ 安全配置

### 生产环境建议
1. **使用HTTPS**: 配置Nginx反向代理
2. **设置强密码**: 使用复杂的环境变量值
3. **定期更新**: 保持依赖和镜像最新
4. **监控告警**: 设置资源使用和错误告警

### 防火墙配置（Linux）
```bash
# 开放端口
sudo ufw allow 7860/tcp

# 限制IP访问（可选）
sudo ufw allow from 192.168.1.0/24 to any port 7860
```

## 📞 技术支持

遇到问题请联系：
- **邮箱**: 1360962086@qq.com
- **Issues**: [GitHub Issues](https://github.com/MisonL/GAP/issues)
- **Discussions**: [GitHub Discussions](https://github.com/MisonL/GAP/discussions)

## 🎯 快速命令参考

```bash
# 部署
./deploy.sh docker      # Docker部署
./deploy.sh local       # 本地部署
./deploy.sh stop        # 停止服务
./deploy.sh help        # 查看帮助

# 日志查看
tail -f logs/app.log    # 实时日志
docker-compose logs -f  # Docker日志

# 状态检查
curl http://localhost:7860/healthz  # 健康检查
```