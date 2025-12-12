#!/bin/bash
set -e

# GAP 开发环境脚本
# 用于快速设置和启动开发环境

echo "🚀 GAP 开发环境设置脚本"
echo "========================="

# 检查 Python 版本
echo "检查 Python 环境..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未找到，请先安装 Python 3.10+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
if [[ $(echo "$PYTHON_VERSION < 3.10" | bc -l) -eq 1 ]]; then
    echo "❌ Python 版本过低 ($PYTHON_VERSION)，需要 Python 3.10+"
    exit 1
fi

echo "✅ Python 版本: $(python3 --version)"

# 检查 UV
echo "检查 UV 包管理器..."
if ! command -v uv &> /dev/null; then
    echo "📦 安装 UV..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

echo "✅ UV 版本: $(uv --version)"

# 设置项目目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "📁 项目目录: $PROJECT_DIR"
cd "$PROJECT_DIR"

# 创建并激活虚拟环境
if [ ! -d ".venv" ]; then
    echo "🔨 创建虚拟环境..."
    uv venv --python 3.10
fi

echo "🔌 激活虚拟环境..."
source .venv/bin/activate

# 安装依赖
echo "📦 安装项目依赖..."
uv pip install -e ".[dev]"

# 数据库迁移（如果需要）
if [ "$1" = "--migrate" ]; then
    echo "🗃️ 运行数据库迁移..."
    uv run alembic upgrade head
fi

# 代码质量检查
echo "🧹 运行代码质量检查..."
if uv run black --check src/ tests/ 2>/dev/null && \
   uv run isort --check-only src/ tests/ 2>/dev/null; then
    echo "✅ 代码格式检查通过"
else
    echo "⚠️ 代码需要格式化，正在自动修复..."
    uv run black src/ tests/
    uv run isort src/ tests/
    echo "✅ 代码格式化完成"
fi

# 启动开发服务器
echo "🌐 启动开发服务器..."
echo "访问 http://localhost:8000"
echo "API 文档: http://localhost:8000/docs"
echo ""
echo "按 Ctrl+C 停止服务器"
echo ""

# 启动 FastAPI 开发服务器
# 设置 PYTHONPATH 确保 src/gap 模块能被正确导入
export PYTHONPATH="$PROJECT_DIR/src:$PYTHONPATH"
cd "$PROJECT_DIR"
uv run uvicorn src.gap.main:app --reload --host 0.0.0.0 --port 8000