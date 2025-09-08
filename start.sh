#!/bin/bash
# GAP (Gemini API Proxy) 启动脚本

echo "🚀 启动 Gemini API 代理服务..."

# 检查Python环境
echo "🔍 检查Python环境..."
python3 --version || { echo "❌ Python3 未安装"; exit 1; }

# 检查后端依赖
echo "📦 检查后端依赖..."
cd backend
python3 -c "import src.gap.main" 2>/dev/null || {
    echo "📥 安装后端依赖..."
    python3 -m pip install -e .
}

# 检查前端构建
echo "🎨 检查前端构建..."
if [ ! -f "../frontend/dist/index.html" ]; then
    echo "⚠️  前端未构建，使用占位页面..."
    mkdir -p ../frontend/dist
    cat > ../frontend/dist/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <title>GAP - Gemini API Proxy</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; text-align: center; }
        .container { max-width: 600px; margin: 0 auto; }
        .logo { font-size: 2em; font-weight: bold; color: #4285f4; margin-bottom: 20px; }
        .status { background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }
        .api-info { text-align: left; background: #e8f0fe; padding: 15px; border-radius: 8px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">GAP</div>
        <h1>Gemini API Proxy</h1>
        <div class="status">
            <h3>✅ 服务运行正常</h3>
            <p>API服务已成功启动</p>
        </div>
        <div class="api-info">
            <h4>可用API端点:</h4>
            <ul>
                <li><strong>OpenAI兼容API:</strong> <code>/v1/chat/completions</code></li>
                <li><strong>Gemini原生API:</strong> <code>/v2/models/{model}:generateContent</code></li>
                <li><strong>模型列表:</strong> <code>/v1/models</code></li>
                <li><strong>健康检查:</strong> <code>/healthz</code></li>
                <li><strong>API文档:</strong> <code>/docs</code></li>
            </ul>
        </div>
    </div>
</body>
</html>
EOF
fi

echo "🎯 启动服务..."
python3 -m src.gap.main