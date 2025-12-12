# 🚀 GAP 部署指南

本指南详细介绍了 GAP (Gemini API Proxy) 项目的多种部署方式，包括 Docker 容器化部署和本地开发环境部署。

## 📋 部署前准备

### 系统要求

#### Docker 部署

- **Docker**: 20.10+
- **Docker Compose**: 2.0+
- **内存**: 最低 2GB，推荐 4GB+
- **存储**: 最低 5GB 可用空间

#### 本地部署

- **Python**: 3.11+ (推荐使用 uv)
- **Node.js**: 18.0+ (使用 pnpm)
- **内存**: 最低 4GB，推荐 8GB+
- **存储**: 最低 2GB 可用空间

### 必需文件检查

确保项目根目录包含以下关键文件：

```bash
# 项目配置
✓ .env.example              # 环境变量模板
✓ docker-compose.yml       # Docker 编排配置
✓ deploy.sh                 # 一键部署脚本

# 后端文件
✓ backend/requirements.txt  # Python 依赖
✓ backend/src/gap/main.py   # FastAPI 入口
✓ backend/Dockerfile        # 后端容器配置

# 前端文件
✓ frontend/package.json     # Node.js 依赖
✓ frontend/vite.config.js   # 构建配置
✓ frontend/Dockerfile        # 前端容器配置
```

## 🐳 Docker 容器化部署（推荐）

### 方式一：一键部署脚本

```bash
# 克隆项目
git clone <repository-url>
cd GAP

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件设置必要配置

# 一键部署
./deploy.sh docker

# 查看服务状态
curl http://localhost:7860/healthz
```

### 方式二：Docker Compose 手动部署

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 访问服务
# Web UI: http://localhost:7860
# API 文档: http://localhost:7860/docs
```

### Docker 服务管理

```bash
# 查看服务状态
docker-compose ps

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend

# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 完全清理（包括数据和镜像）
docker-compose down --volumes --remove-orphans
docker system prune -a
```

### Docker 配置优化

#### 生产环境配置

创建 `docker-compose.prod.yml`：

```yaml
version: "3.8"
services:
  backend:
    restart: always
    environment:
      - LOG_LEVEL=INFO
      - ENABLE_MONITORING=true
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 2G
        reservations:
          cpus: "0.5"
          memory: 1G

  frontend:
    restart: always
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M
```

#### 性能调优

```bash
# Docker 优化的 Dockerfile
FROM node:18-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci --only=production

FROM python:3.11-slim AS backend-builder
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
```

### 数据持久化

```yaml
# docker-compose.yml 中的持久化配置
volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  app_logs:
    driver: local

services:
  postgres:
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    volumes:
      - redis_data:/data

  app:
    volumes:
      - app_logs:/app/logs
      - ./logs:/app/logs
```

## 🔧 本地开发部署

### 方式一：一键部署脚本

```bash
# 使用本地 uv 部署
./deploy.sh local
```

### 方式二：手动本地部署

#### 后端设置

```bash
# 进入后端目录
cd backend

# 安装 uv (如果未安装)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建虚拟环境
uv venv

# 激活虚拟环境
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
uv pip install -r requirements.txt

# 配置环境变量
cp ../.env.example ../.env
# 编辑 .env 文件

# 启动开发服务器
uvicorn src.gap.main:app --reload --host 0.0.0.0 --port 8000
```

#### 前端设置

```bash
# 进入前端目录 (新终端)
cd frontend

# 安装 pnpm (如果未安装)
npm install -g pnpm

# 安装依赖
pnpm install

# 配置环境变量
echo "VITE_API_BASE_URL=http://localhost:8000" > .env.local

# 启动开发服务器
pnpm run dev
```

### 本地开发环境管理

```bash
# 后端管理
cd backend

# 查看进程
ps aux | grep uvicorn

# 停止服务
pkill -f "uvicorn.*gap"

# 查看日志tail -f logs/app.log

# 数据库迁移
uv run alembic upgrade head

# 运行测试
uv run pytest

# 前端管理
cd frontend

# 查看进程
ps aux | grep "vite\|npm"

# 构建生产版本
npm run build

# 预览构建结果
npm run preview

# 代码检查
npm run lint

# 类型检查
npm run type-check
```

## ☁️ 云平台部署

### Vercel (前端) + Railway (后端)

#### 后端部署到 Railway

```bash
# 1. 安装 Railway CLI
npm install -g @railway/cli

# 2. 登录
railway login

# 3. 部署
railway deploy
```

#### 前端部署到 Vercel

```bash
# 1. 安装 Vercel CLI
npm install -g vercel

# 2. 配置环境变量
echo "VITE_API_BASE_URL=https://your-backend.railway.app" > .env.production

# 3. 部署
vercel --prod
```

### AWS ECS 部署

#### ECS 任务定义

```json
{
  "family": "gap-app",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::account:role/ecsTaskExecutionRole",
  "containerDefinitions": [
    {
      "name": "gap-backend",
      "image": "your-registry/gap-backend:latest",
      "portMappings": [
        {
          "containerPort": 7860,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "SECRET_KEY",
          "value": "your-secret-key"
        }
      ]
    }
  ]
}
```

## ⚙️ 环境变量配置

### 基础配置

```dotenv
# 必需
SECRET_KEY=your_very_secure_random_secret_key_here

# 数据库
DATABASE_URL=postgresql://user:password@localhost:5432/gap
REDIS_URL=redis://localhost:6379/0

# API 密钥
GEMINI_API_KEYS=key1,key2,key3
KEY_STORAGE_MODE=database

# 认证
ADMIN_API_KEY=admin_secure_key
USERS_API_KEY=user_key_1,user_key_2  # 平台用户登录密钥

# 功能开关
ENABLE_NATIVE_CACHING=true
ENABLE_CONTEXT_COMPLETION=true
DISABLE_SAFETY_FILTERING=false
```

### 生产配置

```dotenv
# 生产环境优化
LOG_LEVEL=INFO
LOG_FILE=/var/log/gap/app.log
ENABLE_MONITORING=true
ENABLE_METRICS=true

# 性能配置
MAX_CONCURRENT_REQUESTS=100
REQUEST_TIMEOUT=30
DB_POOL_SIZE=20

# 安全配置
CORS_ORIGINS=https://yourdomain.com
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
```

### 开发配置

```dotenv
# 开发环境优化
LOG_LEVEL=DEBUG
LOG_FILE=logs/debug.log
AUTO_RELOAD=true

# 开发工具
ENABLE_PROFILER=true
ENABLE_DEBUG_BAR=true

# 测试数据库
DATABASE_URL=sqlite:///./test.db
REDIS_URL=redis://localhost:6379/1
```

## 🔍 健康检查和监控

### 健康检查端点

```bash
# 基础健康检查
curl http://localhost:7860/healthz

# 详细系统状态
curl http://localhost:7860/api/v1/status

# 数据库连接状态
curl http://localhost:7860/api/v1/health/database

# Redis 连接状态
curl http://localhost:7860/api/v1/health/redis
```

### 监控配置

#### Prometheus 指标

```yaml
# docker-compose.monitoring.yml
version: "3.8"
services:
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

#### 日志管理

```bash
# 日志轮转配置 - /etc/logrotate.d/gap
/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 root root
    postrotate
        systemctl reload gap
    endscript
}
```

## 🚨 问题排查

### 常见问题和解决方案

#### 服务无法启动

```bash
# 检查端口占用
netstat -tulpn | grep :7860

# 检查 Docker 状态
docker ps -a

# 检查日志
docker logs <container_name>
tail -f logs/error.log
```

#### 数据库连接失败

```bash
# 检查数据库连接
psql $DATABASE_URL

# 测试 Redis 连接
redis-cli -u $REDIS_URL ping
```

#### 内存不足

```bash
# 监控内存使用
docker stats
free -h
top

# 清理 Docker 资源
docker system prune -a
```

### 性能优化建议

#### 数据库优化

```sql
-- 数据库配置优化
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
```

#### Redis 缓存优化

```bash
# Redis 配置优化
redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
```

#### 应用级优化

```python
# 后端性能调优
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.gap.main:app",
        host="0.0.0.0",
        port=7860,
        workers=4,          # 工作进程数
        loop="uvloop",      # 高性能事件循环
        access_log=True,
        timeout_keep_alive=30
    )
```

## 📋 部署检查清单

### 部署前检查

- [ ] 环境变量已配置且有效
- [ ] 数据库和 Redis 可访问
- [ ] SSL 证书已配置（生产环境）
- [ ] 防火墙规则已设置
- [ ] 备份策略已制定

### 部署后验证

- [ ] 健康检查端点返回正常
- [ ] Web UI 可正常访问
- [ ] API 接口功能正常
- [ ] 日志记录正常工作
- [ ] 监控系统正常运行

### 安全检查

- [ ] 默认密码已更改
- [ ] API 密钥已配置
- [ ] HTTPS 已启用
- [ ] 跨域配置正确
- [ ] 敏感信息未暴露

## 📞 支持与帮助

- 📖 **详细文档**: [项目 Wiki](https://github.com/MisonL/GAP/wiki)
- 🐛 **问题反馈**: [GitHub Issues](https://github.com/MisonL/GAP/issues)
- 💬 **社区讨论**: [GitHub Discussions](https://github.com/MisonL/GAP/discussions)
- 📧 **技术支持**: 1360962086@qq.com

---

**提示**: 建议首次部署使用 Docker 模式，可以最大程度减少环境配置问题并保证部署一致性。
