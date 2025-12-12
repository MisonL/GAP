# UV 包管理器使用指南

## 🚀 UV 是什么？

UV 是一个极快的 Python 包和项目管理器，用 Rust 编写，是 pip 和 virtualenv 的现代替代品。

## 📦 基本使用命令

### 环境管理
```bash
# 创建虚拟环境
uv venv

# 激活环境
# Linux/Mac:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# 删除虚拟环境
rm -rf .venv
```

### 依赖安装
```bash
# 安装生产依赖
uv pip install -e .

# 安装开发依赖
uv pip install -e ".[dev]"

# 安装特定组的依赖
uv pip install -e ".[test]"
uv pip install -e ".[lint]"

# 更新依赖
uv lock --upgrade

# 同步依赖（根据锁文件）
uv pip sync
```

### 开发命令
```bash
# 运行代码格式化
uv run black src/ tests/

# 排序导入
uv run isort src/ tests/

# 代码检查
uv run flake8 src/ tests/

# 类型检查
uv run mypy src/

# 运行测试
uv run pytest
uv run pytest --cov=src
uv run pytest -m "not slow"

# 安全检查
uv run bandit -r src/

# 代码质量全面检查
uv run pre-commit run --all-files
```

### 开发服务器
```bash
# 启动开发服务器
uv run uvicorn src.gap.main:app --reload --host 0.0.0.0 --port 8000

# 启动生产服务器
uv run gunicorn src.gap.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

## 🛠️ 项目结构优化

### 依赖分组
- **默认依赖**: 生产运行必需的包
- **dev**: 开发、测试、代码质量工具
- **test**: 仅测试相关工具
- **docs**: 文档生成工具
- **lint**: 代码质量检查工具

### 开发工具配置
所有工具配置都在 `pyproject.toml` 中：
- Black (代码格式化)
- isort (导入排序)
- flake8 (代码检查)
- mypy (类型检查)
- pytest (测试框架)
- coverage (覆盖率)

## 🔄 迁移说明

### 从 pip 迁移
```bash
# 之前
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 现在
uv pip install -e ".[dev]"
```

### 性能优势
- **速度**: 比 pip 快 10-100 倍
- **缓存**: 智能包缓存和共享
- **并发**: 并发下载和安装
- **Rust**: 内存安全，高性能

## 💡 最佳实践

1. **总是使用锁文件**: `uv.lock` 确保依赖版本一致
2. **使用虚拟环境**: `uv venv` 创建独立环境
3. **分组管理依赖**: 通过 `[dev]`, `[test]` 等分组
4. **定期更新**: `uv lock --upgrade` 获取最新版本
5. **代码质量**: 运行 `uv run pre-commit` 提交前检查

## 🔧 故障排除

### 常见问题
```bash
# 依赖冲突解决
uv pip install --force-reinstall -e ".[dev]"

# 清理缓存
uv cache clean

# 重新安装所有依赖
uv pip sync --reinstall
```

### 版本兼容性
- 项目要求 Python >= 3.10
- 推荐使用 Python 3.11+ 以获得最佳性能
- 所有依赖版本都在 `pyproject.toml` 中明确定义

---

## 📋 快速开始

```bash
# 1. 创建并激活环境
uv venv && source .venv/bin/activate

# 2. 安装依赖
uv pip install -e ".[dev]"

# 3. 运行开发服务器
uv run uvicorn src.gap.main:app --reload

# 4. 运行测试
uv run pytest

# 5. 代码质量检查
uv run black src/ && uv run isort src/
```

🎉 现在你已经完全使用 UV 管理项目依赖了！