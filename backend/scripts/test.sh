#!/bin/bash
set -e

# GAP 测试脚本
# 用于运行完整的测试套件

echo "🧪 GAP 测试脚本"
echo "==============="

# 设置项目目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "📁 项目目录: $PROJECT_DIR"
cd "$PROJECT_DIR"

# 激活虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✅ 虚拟环境已激活"
else
    echo "❌ 虚拟环境不存在，请先运行 ./scripts/dev.sh"
    exit 1
fi

# 设置 PYTHONPATH
export PYTHONPATH="${PROJECT_DIR}/src:${PYTHONPATH}"
echo "🔧 PYTHONPATH 设置为: ${PYTHONPATH}"

# 运行不同类型的测试
case "${1:-all}" in
    "unit")
        echo "🔬 运行单元测试..."
        uv run pytest -m "unit" -v
        ;;
    "integration")
        echo "🔗 运行集成测试..."
        uv run pytest -m "integration" -v
        ;;
    "slow")
        echo "🐌 运行慢速测试..."
        uv run pytest -m "slow" -v
        ;;
    "coverage")
        echo "📊 运行测试并生成覆盖率报告..."
        uv run pytest --cov=src --cov-report=html --cov-report=term-missing --cov-fail-under=80
        echo "🌐 覆盖率报告: file://$PWD/htmlcov/index.html"
        ;;
    "type-check")
        echo "🔍 运行类型检查..."
        uv run mypy src/
        ;;
    "lint")
        echo "🧹 运行代码质量检查..."
        echo "• Black 代码格式检查..."
        uv run black --check src/ tests/
        echo "• isort 导入排序检查..."
        uv run isort --check-only src/ tests/
        echo "• flake8 代码规范检查..."
        uv run flake8 src/ tests/
        echo "✅ 代码质量检查通过"
        ;;
    "security")
        echo "🔒 运行安全检查..."
        uv run bandit -r src/
        ;;
    "format")
        echo "💅 代码格式化..."
        uv run black src/ tests/
        uv run isort src/ tests/
        echo "✅ 格式化完成"
        ;;
    "all")
        echo "🚀 运行完整测试套件..."
        echo "1️⃣ 代码质量检查..."
        uv run black --check src/ tests/
        uv run isort --check-only src/ tests/
        uv run flake8 src/ tests/

        echo "2️⃣ 类型检查..."
        uv run mypy src/

        echo "3️⃣ 安全检查..."
        uv run bandit -r src/ -f json -o security-report.json || true

        echo "4️⃣ 单元测试..."
        uv run pytest -m "not slow" --cov=src --cov-report=term-missing --cov-fail-under=80

        echo "🎉 所有测试通过！"
        ;;
    "fix")
        echo "🔧 自动修复代码问题..."
        uv run black src/ tests/
        uv run isort src/ tests/
        echo "✅ 代码已自动修复"
        ;;
    *)
        echo "用法: $0 {unit|integration|slow|coverage|type-check|lint|security|format|all|fix}"
        echo ""
        echo "选项说明:"
        echo "  unit        - 运行单元测试"
        echo "  integration - 运行集成测试"
        echo "  slow        - 运行慢速测试"
        echo "  coverage    - 运行测试并生成覆盖率报告"
        echo "  type-check  - 运行类型检查"
        echo "  lint        - 运行代码质量检查"
        echo "  security    - 运行安全检查"
        echo "  format      - 格式化代码"
        echo "  all         - 运行完整测试套件（默认）"
        echo "  fix         - 自动修复代码问题"
        exit 1
        ;;
esac