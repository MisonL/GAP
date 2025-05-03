FROM python:3.11-slim

WORKDIR /app

# 1. 先复制依赖文件并安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. 再复制应用程序代码
# 将本地的 app 目录及其内容复制到容器的 /app/app 目录
COPY ./app ./app
COPY ./assets ./assets
# model_limits.json 包含在上面的 COPY ./app ./app 中

# 环境变量 (在 Hugging Face Spaces 中通过 Secrets 设置)
# ENV GEMINI_API_KEYS=your_key_1,your_key_2,your_key_3

# 启动命令保持不变，它会在 /app 目录下查找 app.main
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]