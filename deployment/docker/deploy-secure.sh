#!/bin/bash

# GAP 安全部署脚本
# Gemini API Proxy - Secure Deployment Script

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
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

# 检查依赖
check_dependencies() {
    log_info "检查依赖..."

    # 检查 Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装"
        exit 1
    fi

    # 检查 Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose 未安装"
        exit 1
    fi

    # 检查 Docker 版本
    DOCKER_VERSION=$(docker --version | sed 's/.*version //;s/,.*//g')
    log_info "Docker 版本: $DOCKER_VERSION"

    COMPOSE_VERSION=$(docker-compose --version | sed 's/.*version //;s/,.*//g')
    log_info "Docker Compose 版本: $COMPOSE_VERSION"

    log_success "依赖检查完成"
}

# 环境安全检查
security_check() {
    log_info "执行环境安全检查..."

    # 检查 .env 文件权限
    if [ -f "../../.env" ]; then
        ENV_PERMS=$(stat -c "%a" "../../.env")
        if [ "$ENV_PERMS" != "600" ]; then
            log_warning ".env 文件权限不安全 (当前: $ENV_PERMS, 建议: 600)"
            log_info "修复 .env 文件权限..."
            chmod 600 "../../.env"
        fi
    fi

    # 检查是否有敏感信息泄漏
    log_info "检查敏感信息泄漏..."
    if grep -r "SECRET_KEY\|PASSWORD\|TOKEN\|API_KEY" --include="*.py" --include="*.js" --include="*.ts" ../../src/ | grep -v "_example\|sample\|test" | head -5; then
        log_warning "发现潜在的硬编码敏感信息"
    fi

    log_success "安全检查完成"
}

# 构建安全镜像
build_secure_image() {
    log_info "构建安全Docker镜像..."

    # 使用 BuildKit 进行安全构建
    export DOCKER_BUILDKIT=1

    # 构建镜像
    if docker build \
        --build-arg BUILDKIT_INLINE_CACHE=1 \
        --tag "gemini-proxy:secure" \
        --file "deployment/docker/Dockerfile" \
        ../../; then
        log_success "安全镜像构建完成"
    else
        log_error "镜像构建失败"
        exit 1
    fi

    # 扫描镜像漏洞
    log_info "扫描镜像安全漏洞..."
    if command -v docker scan &> /dev/null; then
        docker scan gemini-proxy:secure || log_warning "Docker Scan 失败或不可用"
    else
        log_warning "Docker Scan 不可用，跳过漏洞扫描"
    fi
}

# 运行安全扫描
run_security_scan() {
    log_info "运行应用安全扫描..."

    # 创建安全扫描目录
    mkdir -p security-reports

    # 运行 Safety (依赖漏洞检查)
    log_info "运行 Safety 检查..."
    if command -v safety &> /dev/null; then
        safety check --json --output security-reports/safety-report.json || true
    fi

    # 运行 Bandit (Python 安全检查)
    log_info "运行 Bandit 检查..."
    if command -v bandit &> /dev/null; then
        bandit -r ../../backend/src -f json -o security-reports/bandit-report.json || true
    fi

    log_success "安全扫描完成，报告保存在 security-reports/ 目录"
}

# 部署应用
deploy_application() {
    log_info "部署应用..."

    # 创建必要的目录
    mkdir -p ../../data
    mkdir -p ../../logs

    # 设置目录权限
    chmod 755 ../../data
    chmod 755 ../../logs

    # 使用 Docker Compose 部署
    if docker-compose -f docker-compose.yml up -d; then
        log_success "应用部署完成"
    else
        log_error "应用部署失败"
        exit 1
    fi
}

# 部署后验证
post_deploy_verification() {
    log_info "执行部署后验证..."

    # 等待服务启动
    log_info "等待服务启动..."
    sleep 30

    # 检查容器状态
    CONTAINER_STATUS=$(docker inspect gemini-proxy-secure --format='{{.State.Status}}' 2>/dev/null || echo "not_found")

    if [ "$CONTAINER_STATUS" = "running" ]; then
        log_success "容器运行正常"

        # 检查健康状态
        HEALTH_STATUS=$(docker inspect gemini-proxy-secure --format='{{.State.Health.Status}}' 2>/dev/null || echo "no_healthcheck")
        log_info "健康检查状态: $HEALTH_STATUS"

        # 测试 API 端点
        log_info "测试 API 端点..."
        if curl -f --max-time 10 http://localhost:7860/healthz &>/dev/null; then
            log_success "API 端点响应正常"
        else
            log_warning "API 端点测试失败"
        fi

    else
        log_error "容器状态异常: $CONTAINER_STATUS"
        docker logs gemini-proxy-secure --tail 50
        exit 1
    fi
}

# 清理旧镜像
cleanup_old_images() {
    log_info "清理旧镜像..."

    # 清理未使用的镜像
    docker image prune -f

    # 保留最近的5个版本
    OLD_IMAGES=$(docker images gemini-proxy --format "table {{.Repository}}:{{.Tag}}" | tail -n +2 | tail -n +6)
    if [ -n "$OLD_IMAGES" ]; then
        echo "$OLD_IMAGES" | xargs docker rmi -f || true
    fi

    log_success "清理完成"
}

# 生成部署报告
generate_deployment_report() {
    log_info "生成部署报告..."

    cat > deployment-report.md << EOF
# GAP 安全部署报告

**部署时间**: $(date)
**部署版本**: $(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

## 镜像信息
- **镜像名称**: gemini-proxy:secure
- **镜像大小**: $(docker images gemini-proxy:secure --format "{{.Size}}")
- **镜像ID**: $(docker images gemini-proxy:secure --format "{{.ID}}")

## 容器状态
- **容器名称**: gemini-proxy-secure
- **运行状态**: $(docker inspect gemini-proxy-secure --format='{{.State.Status}}' 2>/dev/null || echo "not_found")
- **健康状态**: $(docker inspect gemini-proxy-secure --format='{{.State.Health.Status}}' 2>/dev/null || echo "no_healthcheck")
- **启动时间**: $(docker inspect gemini-proxy-secure --format='{{.State.StartedAt}}' 2>/dev/null || echo "N/A")

## 安全配置
- **运行用户**: $(docker inspect gemini-proxy-secure --format='{{.Config.User}}' 2>/dev/null || echo "unknown")
- **安全选项**: $(docker inspect gemini-proxy-secure --format='{{json .HostConfig.SecurityOpt}}' 2>/dev/null || echo "N/A")
- **只读文件系统**: $(docker inspect gemini-proxy-secure --format='{{.HostConfig.ReadonlyRootfs}}' 2>/dev/null || echo "false")

## 网络配置
- **网络**: $(docker inspect gemini-proxy-secure --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || echo "unknown")
- **端口映射**: $(docker port gemini-proxy-secure 2>/dev/null || echo "N/A")

## 资源使用
- **CPU使用**: $(docker stats gemini-proxy-secure --no-stream --format "table {{.CPUPerc}}" | tail -n +2 2>/dev/null || echo "N/A")
- **内存使用**: $(docker stats gemini-proxy-secure --no-stream --format "table {{.MemUsage}}" | tail -n +2 2>/dev/null || echo "N/A")

EOF

    log_success "部署报告已生成: deployment-report.md"
}

# 主函数
main() {
    log_info "开始 GAP 安全部署..."

    check_dependencies
    security_check
    build_secure_image
    run_security_scan
    deploy_application
    post_deploy_verification
    cleanup_old_images
    generate_deployment_report

    log_success "GAP 安全部署完成！"
    log_info "访问地址: http://localhost:7860"
    log_info "健康检查: http://localhost:7860/healthz"
    log_info "查看日志: docker logs -f gemini-proxy-secure"
}

# 错误处理
trap 'log_error "部署过程中发生错误，退出码: $?"' ERR

# 执行主函数
main "$@"