# 虚拟环境指南

## Brief overview

此规则文件包含关于在 `./venv` 虚拟环境中运行项目的指南。

## Development workflow

- 运行项目或安装依赖时，必须激活项目根目录下的 `./venv` 虚拟环境。

- 确保所有项目依赖都安装在此虚拟环境中 (`pip install -r requirements.txt`)。

- 启动应用程序的命令应在激活虚拟环境后执行。

## Other guidelines

- 在执行任何 Python 相关命令（如 `pip` 或 `uvicorn`）之前，请先激活虚拟环境。
