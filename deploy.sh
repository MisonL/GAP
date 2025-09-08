#!/bin/bash

# Gemini API代理 - 一键清理+重建部署脚本
# 支持Docker部署和本地uv部署两种模式
# 使用方法: ./deploy.sh [docker|local] 或直接运行进入交互式菜单

set -e

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# 通用函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查命令是否存在
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# 停止服务
stop_services() {
    log_info "🛑 停止所有服务..."
    
    # 停止Docker服务
    if [[ -f "deployment/docker/docker-compose.yml" ]]; then
        cd deployment/docker
        if command_exists docker-compose; then
            docker-compose down 2>/dev/null || true
        elif docker compose version >/dev/null 2>&1; then
            docker compose down 2>/dev/null || true
        fi
        cd ../..
    fi
    
    # 停止本地服务
    if [[ -f "logs/backend.pid" ]]; then
        kill $(cat logs/backend.pid) 2>/dev/null || true
        rm logs/backend.pid
    fi
    
    if [[ -f "logs/frontend.pid" ]]; then
        kill $(cat logs/frontend.pid) 2>/dev/null || true
        rm logs/frontend.pid
    fi
    
    log_success "✅ 所有服务已停止"
}

# 检查服务状态
check_status() {
    log_info "🔍 检查服务状态..."
    echo ""
    
    # 检查Docker服务
    if command_exists docker; then
        echo "🐳 Docker服务:"
        if docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(gap|gemini|proxy)" 2>/dev/null; then
            echo "   ✅ Docker容器正在运行"
        else
            echo "   ❌ 没有运行中的Docker容器"
        fi
    else
        echo "   ❌ Docker未安装"
    fi
    
    echo ""
    
    # 检查本地服务
    echo "🔧 本地服务:"
    if [[ -f "logs/backend.pid" ]] && kill -0 $(cat logs/backend.pid) 2>/dev/null; then
        echo "   ✅ 后端服务正在运行 (PID: $(cat logs/backend.pid))"
    else
        echo "   ❌ 后端服务未运行"
    fi
    
    if [[ -f "logs/frontend.pid" ]] && kill -0 $(cat logs/frontend.pid) 2>/dev/null; then
        echo "   ✅ 前端服务正在运行 (PID: $(cat logs/frontend.pid))"
    else
        echo "   ❌ 前端服务未运行"
    fi
    
    echo ""
    
    # 检查端口占用
    echo "🌐 端口状态:"
    if lsof -i :7860 2>/dev/null; then
        echo "   ✅ 端口7860 (Docker) 已被占用"
    else
        echo "   ❌ 端口7860 (Docker) 空闲"
    fi
    
    if lsof -i :8000 2>/dev/null; then
        echo "   ✅ 端口8000 (后端) 已被占用"
    else
        echo "   ❌ 端口8000 (后端) 空闲"
    fi
    
    if lsof -i :3000 2>/dev/null; then
        echo "   ✅ 端口3000 (前端) 已被占用"
    else
        echo "   ❌ 端口3000 (前端) 空闲"
    fi
    
    echo ""
    read -p "按回车键返回主菜单..."
    show_interactive_menu
}

# 清理环境
cleanup_environment() {
    log_info "🧹 开始清理环境..."
    echo ""
    
    echo "请选择清理级别："
    echo "1) 软清理 - 仅停止服务"
    echo "2) 标准清理 - 停止服务并清理容器"
    echo "3) 深度清理 - 停止服务、清理容器和镜像"
    echo "4) 返回主菜单"
    echo ""
    
    read -p "请输入选项 [1-4]: " cleanup_choice
    
    case $cleanup_choice in
        1)
            stop_services
            ;;
        2)
            stop_services
            if command_exists docker; then
                log_info "清理Docker容器..."
                docker system prune -f 2>/dev/null || true
            fi
            ;;
        3)
            stop_services
            if command_exists docker; then
                log_info "清理Docker容器和镜像..."
                docker system prune -af 2>/dev/null || true
                docker volume prune -f 2>/dev/null || true
            fi
            ;;
        4)
            show_interactive_menu
            ;;
        *)
            log_error "无效选项"
            cleanup_environment
            ;;
    esac
    
    read -p "按回车键返回主菜单..."
    show_interactive_menu
}

# Docker部署模式
deploy_docker() {
    log_info "使用Docker部署模式..."
    
    # 检查Docker
    if ! command_exists docker; then
        log_error "请先安装Docker"
        exit 1
    fi

    # 检查Docker Compose
    if ! command_exists docker-compose && ! docker compose version >/dev/null 2>&1; then
        log_error "请先安装Docker Compose"
        exit 1
    fi

    # 检查必需文件
    if [[ ! -f "deployment/docker/docker-compose.yml" ]]; then
        log_error "缺少 deployment/docker/docker-compose.yml 文件"
        exit 1
    fi

    if [[ ! -f "deployment/docker/Dockerfile" ]]; then
        log_error "缺少 deployment/docker/Dockerfile 文件"
        exit 1
    fi

    # 检查.env文件
    if [[ ! -f ".env" ]]; then
        log_warning "缺少 .env 文件，将使用 .env.example"
        if [[ -f ".env.example" ]]; then
            cp .env.example .env
            log_success "已复制 .env.example 到 .env"
        else
            log_error "缺少 .env 和 .env.example 文件"
            exit 1
        fi
    fi

    # 使用docker compose或docker-compose
    if command_exists docker-compose; then
        DOCKER_COMPOSE="docker-compose"
    elif docker compose version >/dev/null 2>&1; then
        DOCKER_COMPOSE="docker compose"
    else
        log_error "未找到Docker Compose"
        exit 1
    fi

    # 清理旧容器和镜像
    log_info "🧹 清理旧容器和镜像..."
    
    # 强制清理可能占用端口的容器
    log_info "🔍 检查端口7860占用情况..."
    docker kill $(docker ps -q --filter "publish=7860") 2>/dev/null || true
    docker rm $(docker ps -aq --filter "publish=7860") 2>/dev/null || true

    # 清理本项目相关容器
    log_info "🧽 清理GAP项目相关容器..."
    docker kill $(docker ps -q --filter "name=gap" --filter "name=gemini" --filter "name=proxy") 2>/dev/null || true
    docker rm $(docker ps -aq --filter "name=gap" --filter "name=gemini" --filter "name=proxy") 2>/dev/null || true

    # 使用docker-compose清理
    log_info "🗑️  使用docker-compose清理..."
    cd deployment/docker
    $DOCKER_COMPOSE down --remove-orphans --volumes 2>/dev/null || true

    # 清理旧镜像
    log_info "🧹 清理旧镜像..."
    for image in gemini-api-proxy:latest gap-gemini-proxy:latest; do
        if docker images $image -q &> /dev/null; then
            docker rmi $image 2>/dev/null || true
        fi
    done

    # 构建并启动
    log_info "🏗️  构建镜像并启动服务..."
    $DOCKER_COMPOSE build --no-cache
    log_info "🚀 启动服务..."
    $DOCKER_COMPOSE up -d

    # 返回项目根目录
    cd ../..

    # 等待启动
    log_info "⏳ 等待服务启动..."
    sleep 5

    # 检查状态
    if curl -s http://localhost:7860/healthz > /dev/null; then
        log_success "✅ Docker部署成功！"
        echo "🌐 访问: http://localhost:7860"
        echo "📊 日志: cd deployment/docker && $DOCKER_COMPOSE logs -f"
        echo "🛑 停止: cd deployment/docker && $DOCKER_COMPOSE down"
    else
        log_error "❌ Docker启动失败，查看日志:"
        cd deployment/docker
        $DOCKER_COMPOSE logs --tail=50
        exit 1
    fi
}

# 本地uv部署模式
deploy_local() {
    log_info "使用本地uv部署模式..."
    
    # 检查Python
    if ! command_exists python3; then
        log_error "请先安装Python 3.8+"
        exit 1
    fi

    # 检查uv
    if ! command_exists uv; then
        log_info "安装uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        source ~/.cargo/env
    fi

    # 检查必需文件
    if [[ ! -f "backend/requirements.txt" ]]; then
        log_error "缺少 backend/requirements.txt 文件"
        exit 1
    fi

    if [[ ! -f ".env" ]]; then
        log_warning "缺少 .env 文件，将使用 .env.example"
        if [[ -f ".env.example" ]]; then
            cp .env.example .env
            log_success "已复制 .env.example 到 .env"
        else
            log_error "缺少 .env 和 .env.example 文件"
            exit 1
        fi
    fi

    # 清理旧进程
    log_info "🧹 清理旧进程..."
    pkill -f "uvicorn.*gap" 2>/dev/null || true
    pkill -f "python.*main.py" 2>/dev/null || true

    # 设置后端
    log_info "🔧 设置后端环境..."
    cd backend
    
    # 创建虚拟环境（如果不存在）
    if [[ ! -d ".venv" ]]; then
        log_info "创建虚拟环境..."
        uv venv
    fi
    
    # 激活虚拟环境
    source .venv/bin/activate
    
    # 安装依赖
    log_info "📦 安装后端依赖..."
    uv pip install -r requirements.txt
    
    # 检查数据库
    log_info "🔍 检查数据库连接..."
    python -c "
import sys
sys.path.append('src')
from gap.core.database.utils import DATABASE_URL
from sqlalchemy import create_engine
engine = create_engine(DATABASE_URL.replace('postgresql+asyncpg', 'postgresql'))
try:
    engine.connect()
    print('✅ 数据库连接成功')
except Exception as e:
    print(f'❌ 数据库连接失败: {e}')
    sys.exit(1)
"

    # 运行数据库迁移
    log_info "🔄 运行数据库迁移..."
    alembic upgrade head || log_warning "数据库迁移失败，继续启动..."

    # 启动后端
    log_info "🚀 启动后端服务..."
    nohup uvicorn src.gap.main:app --host 0.0.0.0 --port 8000 > ../logs/backend.log 2>&1 &
    BACKEND_PID=$!
    echo $BACKEND_PID > ../logs/backend.pid
    
    # 等待后端启动
    log_info "⏳ 等待后端启动..."
    sleep 5
    
    if curl -s http://localhost:8000/healthz > /dev/null; then
        log_success "✅ 后端启动成功！"
    else
        log_error "❌ 后端启动失败"
        cat ../logs/backend.log
        exit 1
    fi

    # 设置前端
    log_info "🎨 设置前端环境..."
    cd ../frontend
    
    # 安装前端依赖
    log_info "📦 安装前端依赖..."
    npm install
    
    # 构建前端
    log_info "🏗️  构建前端..."
    npm run build
    
    # 启动前端
    log_info "🚀 启动前端服务..."
    nohup npm run preview -- --host 0.0.0.0 --port 3000 > ../logs/frontend.log 2>&1 &
    FRONTEND_PID=$!
    echo $FRONTEND_PID > ../logs/frontend.pid
    
    # 等待前端启动
    log_info "⏳ 等待前端启动..."
    sleep 3
    
    if curl -s http://localhost:3000 > /dev/null; then
        log_success "✅ 本地部署成功！"
        echo "🌐 后端: http://localhost:8000"
        echo "🌐 前端: http://localhost:3000"
        echo "📊 后端日志: tail -f logs/backend.log"
        echo "📊 前端日志: tail -f logs/frontend.log"
        echo "🛑 停止: ./deploy.sh stop"
    else
        log_error "❌ 前端启动失败"
        cat ../logs/frontend.log
        exit 1
    fi
}

# 显示帮助
show_help() {
    echo "使用方法: $0 [docker|local|stop|help]"
    echo ""
    echo "部署模式:"
    echo "  docker    使用Docker部署 (默认)"
    echo "  local     使用uv本地部署"
    echo "  stop      停止所有服务"
    echo "  help      显示帮助信息"
    echo ""
    echo "示例:"
    echo "  $0           # 使用Docker部署"
    echo "  $0 local     # 使用uv本地部署"
    echo "  $0 stop      # 停止所有服务"
    read -p "按回车键返回主菜单..."
    show_interactive_menu
}

# 显示交互式菜单
show_interactive_menu() {
    echo ""
    echo "🚀 Gemini API代理 - 交互式部署菜单"
    echo "=================================="
    echo ""
    echo "请选择部署方式："
    echo ""
    echo "1) 🐳 Docker部署 (推荐)"
    echo "2) 🔧 本地uv部署"
    echo "3) 🛑 停止所有服务"
    echo "4) 📊 查看服务状态"
    echo "5) 🧹 清理环境"
    echo "6) ❓ 显示帮助"
    echo "7) 🚪 退出"
    echo ""
    
    read -p "请输入选项 [1-7]: " choice
    
    case $choice in
        1)
            deploy_docker
            ;;
        2)
            deploy_local
            ;;
        3)
            stop_services
            ;;
        4)
            check_status
            ;;
        5)
            cleanup_environment
            ;;
        6)
            show_help
            ;;
        7)
            log_info "感谢使用，再见！"
            exit 0
            ;;
        *)
            log_error "无效选项，请重新选择"
            show_interactive_menu
            ;;
    esac
}

# 检查服务状态
check_status() {
    log_info "🔍 检查服务状态..."
    echo ""
    
    # 检查Docker服务
    if command_exists docker; then
        echo "🐳 Docker服务:"
        if docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(gap|gemini|proxy)" 2>/dev/null; then
            echo "   ✅ Docker容器正在运行"
        else
            echo "   ❌ 没有运行中的Docker容器"
        fi
    else
        echo "   ❌ Docker未安装"
    fi
    
    echo ""
    
    # 检查本地服务
    echo "🔧 本地服务:"
    if [[ -f "logs/backend.pid" ]] && kill -0 $(cat logs/backend.pid) 2>/dev/null; then
        echo "   ✅ 后端服务正在运行 (PID: $(cat logs/backend.pid))"
    else
        echo "   ❌ 后端服务未运行"
    fi
    
    if [[ -f "logs/frontend.pid" ]] && kill -0 $(cat logs/frontend.pid) 2>/dev/null; then
        echo "   ✅ 前端服务正在运行 (PID: $(cat logs/frontend.pid))"
    else
        echo "   ❌ 前端服务未运行"
    fi
    
    echo ""
    
    # 检查端口占用
    echo "🌐 端口状态:"
    if lsof -i :7860 2>/dev/null; then
        echo "   ✅ 端口7860 (Docker) 已被占用"
    else
        echo "   ❌ 端口7860 (Docker) 空闲"
    fi
    
    if lsof -i :8000 2>/dev/null; then
        echo "   ✅ 端口8000 (后端) 已被占用"
    else
        echo "   ❌ 端口8000 (后端) 空闲"
    fi
    
    if lsof -i :3000 2>/dev/null; then
        echo "   ✅ 端口3000 (前端) 已被占用"
    else
        echo "   ❌ 端口3000 (前端) 空闲"
    fi
    
    echo ""
    read -p "按回车键返回主菜单..."
    show_interactive_menu
}

# 清理环境
cleanup_environment() {
    log_info "🧹 开始清理环境..."
    echo ""
    
    echo "请选择清理级别："
    echo "1) 软清理 - 仅停止服务"
    echo "2) 标准清理 - 停止服务并清理容器"
    echo "3) 深度清理 - 停止服务、清理容器和镜像"
    echo "4) 返回主菜单"
    echo ""
    
    read -p "请输入选项 [1-4]: " cleanup_choice
    
    case $cleanup_choice in
        1)
            stop_services
            ;;
        2)
            stop_services
            if command_exists docker; then
                log_info "清理Docker容器..."
                docker system prune -f 2>/dev/null || true
            fi
            ;;
        3)
            stop_services
            if command_exists docker; then
                log_info "清理Docker容器和镜像..."
                docker system prune -af 2>/dev/null || true
                docker volume prune -f 2>/dev/null || true
            fi
            ;;
        4)
            show_interactive_menu
            ;;
        *)
            log_error "无效选项"
            cleanup_environment
            ;;
    esac
    
    read -p "按回车键返回主菜单..."
    show_interactive_menu
}

# 部署模式选择 - 如果没有参数则显示菜单
if [[ $# -eq 0 ]]; then
    show_interactive_menu
    exit 0
else
    DEPLOY_MODE=$1
fi

echo "🚀 Gemini API代理 - 清理+重建部署"
echo "📦 部署模式: ${DEPLOY_MODE}"

# Docker部署模式
deploy_docker() {
    log_info "使用Docker部署模式..."
    
    # 检查Docker
    if ! command_exists docker; then
        log_error "请先安装Docker"
        exit 1
    fi

    # 检查Docker Compose
    if ! command_exists docker-compose && ! docker compose version >/dev/null 2>&1; then
        log_error "请先安装Docker Compose"
        exit 1
    fi

    # 检查必需文件
    if [[ ! -f "deployment/docker/docker-compose.yml" ]]; then
        log_error "缺少 deployment/docker/docker-compose.yml 文件"
        exit 1
    fi

    if [[ ! -f "deployment/docker/Dockerfile" ]]; then
        log_error "缺少 deployment/docker/Dockerfile 文件"
        exit 1
    fi

    # 检查.env文件
    if [[ ! -f ".env" ]]; then
        log_warning "缺少 .env 文件，将使用 .env.example"
        if [[ -f ".env.example" ]]; then
            cp .env.example .env
            log_success "已复制 .env.example 到 .env"
        else
            log_error "缺少 .env 和 .env.example 文件"
            exit 1
        fi
    fi

    # 使用docker compose或docker-compose
    if command_exists docker-compose; then
        DOCKER_COMPOSE="docker-compose"
    elif docker compose version >/dev/null 2>&1; then
        DOCKER_COMPOSE="docker compose"
    else
        log_error "未找到Docker Compose"
        exit 1
    fi

    # 清理旧容器和镜像
    log_info "🧹 清理旧容器和镜像..."
    
    # 强制清理可能占用端口的容器
    log_info "🔍 检查端口7860占用情况..."
    docker kill $(docker ps -q --filter "publish=7860") 2>/dev/null || true
    docker rm $(docker ps -aq --filter "publish=7860") 2>/dev/null || true

    # 清理本项目相关容器
    log_info "🧽 清理GAP项目相关容器..."
    docker kill $(docker ps -q --filter "name=gap" --filter "name=gemini" --filter "name=proxy") 2>/dev/null || true
    docker rm $(docker ps -aq --filter "name=gap" --filter "name=gemini" --filter "name=proxy") 2>/dev/null || true

    # 使用docker-compose清理
    log_info "🗑️  使用docker-compose清理..."
    cd deployment/docker
    $DOCKER_COMPOSE down --remove-orphans --volumes 2>/dev/null || true

    # 清理旧镜像
    log_info "🧹 清理旧镜像..."
    for image in gemini-api-proxy:latest gap-gemini-proxy:latest; do
        if docker images $image -q &> /dev/null; then
            docker rmi $image 2>/dev/null || true
        fi
    done

    # 构建并启动
    log_info "🏗️  构建镜像并启动服务..."
    $DOCKER_COMPOSE build --no-cache
    log_info "🚀 启动服务..."
    $DOCKER_COMPOSE up -d

    # 返回项目根目录
    cd ../..

    # 等待启动
    log_info "⏳ 等待服务启动..."
    sleep 5

    # 检查状态
    if curl -s http://localhost:7860/healthz > /dev/null; then
        log_success "✅ Docker部署成功！"
        echo "🌐 访问: http://localhost:7860"
        echo "📊 日志: cd deployment/docker && $DOCKER_COMPOSE logs -f"
        echo "🛑 停止: cd deployment/docker && $DOCKER_COMPOSE down"
    else
        log_error "❌ Docker启动失败，查看日志:"
        cd deployment/docker
        $DOCKER_COMPOSE logs --tail=50
        exit 1
    fi
}

# 本地uv部署模式
deploy_local() {
    log_info "使用本地uv部署模式..."
    
    # 检查Python
    if ! command_exists python3; then
        log_error "请先安装Python 3.8+"
        exit 1
    fi

    # 检查uv
    if ! command_exists uv; then
        log_info "安装uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        source ~/.cargo/env
    fi

    # 检查必需文件
    if [[ ! -f "backend/requirements.txt" ]]; then
        log_error "缺少 backend/requirements.txt 文件"
        exit 1
    fi

    if [[ ! -f ".env" ]]; then
        log_warning "缺少 .env 文件，将使用 .env.example"
        if [[ -f ".env.example" ]]; then
            cp .env.example .env
            log_success "已复制 .env.example 到 .env"
        else
            log_error "缺少 .env 和 .env.example 文件"
            exit 1
        fi
    fi

    # 清理旧进程
    log_info "🧹 清理旧进程..."
    pkill -f "uvicorn.*gap" 2>/dev/null || true
    pkill -f "python.*main.py" 2>/dev/null || true

    # 设置后端
    log_info "🔧 设置后端环境..."
    cd backend
    
    # 创建虚拟环境（如果不存在）
    if [[ ! -d ".venv" ]]; then
        log_info "创建虚拟环境..."
        uv venv
    fi
    
    # 激活虚拟环境
    source .venv/bin/activate
    
    # 安装依赖
    log_info "📦 安装后端依赖..."
    uv pip install -r requirements.txt
    
    # 检查数据库
    log_info "🔍 检查数据库连接..."
    python -c "
import sys
sys.path.append('src')
from gap.core.database.utils import DATABASE_URL
from sqlalchemy import create_engine
engine = create_engine(DATABASE_URL.replace('postgresql+asyncpg', 'postgresql'))
try:
    engine.connect()
    print('✅ 数据库连接成功')
except Exception as e:
    print(f'❌ 数据库连接失败: {e}')
    sys.exit(1)
"

    # 运行数据库迁移
    log_info "🔄 运行数据库迁移..."
    alembic upgrade head || log_warning "数据库迁移失败，继续启动..."

    # 启动后端
    log_info "🚀 启动后端服务..."
    nohup uvicorn src.gap.main:app --host 0.0.0.0 --port 8000 > ../logs/backend.log 2>&1 &
    BACKEND_PID=$!
    echo $BACKEND_PID > ../logs/backend.pid
    
    # 等待后端启动
    log_info "⏳ 等待后端启动..."
    sleep 5
    
    if curl -s http://localhost:8000/healthz > /dev/null; then
        log_success "✅ 后端启动成功！"
    else
        log_error "❌ 后端启动失败"
        cat ../logs/backend.log
        exit 1
    fi

    # 设置前端
    log_info "🎨 设置前端环境..."
    cd ../frontend
    
    # 安装前端依赖
    log_info "📦 安装前端依赖..."
    npm install
    
    # 构建前端
    log_info "🏗️  构建前端..."
    npm run build
    
    # 启动前端
    log_info "🚀 启动前端服务..."
    nohup npm run preview -- --host 0.0.0.0 --port 3000 > ../logs/frontend.log 2>&1 &
    FRONTEND_PID=$!
    echo $FRONTEND_PID > ../logs/frontend.pid
    
    # 等待前端启动
    log_info "⏳ 等待前端启动..."
    sleep 3
    
    if curl -s http://localhost:3000 > /dev/null; then
        log_success "✅ 本地部署成功！"
        echo "🌐 后端: http://localhost:8000"
        echo "🌐 前端: http://localhost:3000"
        echo "📊 后端日志: tail -f logs/backend.log"
        echo "📊 前端日志: tail -f logs/frontend.log"
        echo "🛑 停止: ./deploy.sh stop"
    else
        log_error "❌ 前端启动失败"
        cat ../logs/frontend.log
        exit 1
    fi
}

# 主逻辑
case "$DEPLOY_MODE" in
    docker)
        deploy_docker
        ;;
    local)
        deploy_local
        ;;
    stop)
        stop_services
        ;;
    help)
        show_help
        ;;
    *)
        log_error "未知部署模式: $DEPLOY_MODE"
        show_help
        exit 1
        ;;
esac