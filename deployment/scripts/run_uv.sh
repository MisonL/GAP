#!/bin/bash
# UV启动脚本 - 专为HuggingFace Spaces优化

# 设置环境变量
export HF_SPACE_ID="true"  # 强制HF Spaces模式
export KEY_STORAGE_MODE="memory"
export CONTEXT_STORAGE_MODE="memory"

# 检查必需的环境变量
if [[ -z "$SECRET_KEY" ]]; then
    echo "❌ 错误: SECRET_KEY 环境变量未设置"
    echo "请设置 SECRET_KEY 环境变量"
    exit 1
fi

if [[ -z "$GEMINI_API_KEYS" ]]; then
    echo "❌ 错误: GEMINI_API_KEYS 环境变量未设置"
    echo "请设置 GEMINI_API_KEYS 环境变量"
    exit 1
fi

if [[ -z "$PASSWORD" ]]; then
    echo "⚠️  警告: PASSWORD 环境变量未设置"
    echo "Web UI将无法登录，但API仍可工作"
fi

echo "🚀 启动Gemini API代理服务 (HuggingFace Spaces优化版)"
echo "📊 存储模式: 内存模式 (无持久化)"
echo "🔑 API Key模式: 内存模式"
echo "🌐 认证方式: JWT + localStorage"

# 使用UV启动服务
uv run uvicorn app.main:app --host 0.0.0.0 --port 7860 --workers 1