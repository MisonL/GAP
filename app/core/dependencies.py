# 存放项目依赖项的模块，用于解决循环导入问题
from fastapi import Request # 导入 Request 类
from app.core.key_manager_class import APIKeyManager # 导入 APIKeyManager 类
import httpx # 导入 httpx 库

# 依赖注入函数
def get_key_manager(request: Request) -> APIKeyManager:
    """
    FastAPI 依赖项，用于获取 APIKeyManager 实例。
    """
    return request.app.state.key_manager

def get_http_client(request: Request) -> httpx.AsyncClient:
    """
    FastAPI 依赖项，用于获取 httpx.AsyncClient 实例。
    """
    return request.app.state.http_client