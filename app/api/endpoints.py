import asyncio # 导入 asyncio 模块
import json # 导入 json 模块
import logging # 导入 logging 模块
import time # 导入 time 模块，用于 /v1/models 端点生成时间戳
from typing import List, Dict, Any, Optional # 导入类型提示
from fastapi import APIRouter, HTTPException, Request, Depends, status # 导入 FastAPI 相关组件：路由、HTTP异常、请求对象、依赖注入、状态码
from fastapi.responses import StreamingResponse # 导入流式响应对象
from app import config # 导入应用配置模块

# 从其他模块导入必要的组件
from app.api.models import ChatCompletionRequest, ChatCompletionResponse, ModelList # 导入 API 请求和响应模型
from app.core.gemini import GeminiClient # 导入 Gemini 客户端类
from app.core.key_manager_class import APIKeyManager # 导入类型
import httpx # 导入 httpx 用于类型提示
from app.api.middleware import verify_proxy_key # 导入代理密钥验证中间件/依赖项
# 导入处理器函数
from app.api.request_processing import process_request # 导入核心请求处理函数
# 导入依赖注入函数

from app.core.dependencies import get_key_manager, get_http_client # 导入获取 Key Manager 和 HTTP Client 的依赖函数
# --- 此模块内需要的全局变量 ---
logger = logging.getLogger('my_logger') # 获取日志记录器实例


router = APIRouter() # 创建一个 FastAPI APIRouter 实例，用于定义 API 路由


@router.get("/v1/models", response_model=ModelList) # 定义 GET /v1/models 端点，响应模型为 ModelList
async def list_models(
    key_manager: APIKeyManager = Depends(get_key_manager), # 注入 Key Manager
    http_client: httpx.AsyncClient = Depends(get_http_client) # 注入 HTTP Client
):
    """
    处理获取可用模型列表的 GET 请求。
    """
    active_keys_count = key_manager.get_active_keys_count() # 获取当前有效的 API 密钥数量
    # 如果 GeminiClient.AVAILABLE_MODELS 为空，则确保填充它
    if not GeminiClient.AVAILABLE_MODELS and active_keys_count > 0: # 如果可用模型列表为空且有活跃 Key
        logger.info("首次请求模型列表，尝试获取...") # 首次请求模型列表，尝试获取
        try:
            key_to_use = None # 初始化要使用的 Key
            with key_manager.keys_lock: # 使用锁安全地访问密钥列表
                 if key_manager.api_keys: key_to_use = key_manager.api_keys[0] # 如果有有效密钥，选择第一个用于获取模型列表
            if key_to_use: # 如果找到了要使用的 Key (If a key to use is found)
                # 使用注入的 http_client 调用静态方法
                all_models = await GeminiClient.list_available_models(key_to_use, http_client) # 调用 Gemini 客户端获取所有可用模型
                # 确保 AVAILABLE_MODELS 被正确更新
                GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models] # 清理模型名称（移除 "models/" 前缀）并存储到类变量
                logger.info(f"成功获取可用模型: {GeminiClient.AVAILABLE_MODELS}") # 成功获取可用模型
            else: logger.error("无法找到有效 Key 来获取模型列表。") # 无法找到有效 Key 来获取模型列表
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}") # 记录获取模型列表失败错误
            GeminiClient.AVAILABLE_MODELS = [] # 获取模型列表失败时，重置为空列表

    # 使用标准日志记录
    logger.info("接收到列出模型的请求", extra={'request_type': 'list_models', 'status_code': 200}) # 接收到列出模型的请求
    # 返回列表，确保使用可能已更新的 AVAILABLE_MODELS
    return ModelList(data=[{"id": model, "object": "model", "created": int(time.time()), "owned_by": "organization-owner"} for model in GeminiClient.AVAILABLE_MODELS]) # 构建并返回符合 OpenAI API 格式的模型列表响应


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse, status_code=status.HTTP_200_OK) # 定义 POST /v1/chat/completions 端点，响应模型为 ChatCompletionResponse，状态码为 200
async def chat_completions(
    request_data: ChatCompletionRequest, # 请求体数据，FastAPI 会自动解析 JSON 并验证其结构是否符合 ChatCompletionRequest 模型
    request: Request, # FastAPI 的原始 Request 对象，包含请求头、客户端 IP 等信息
    # 使用新的代理 Key 验证依赖，并将验证通过的 Key 和配置注入
    auth_data: Dict[str, Any] = Depends(verify_proxy_key), # 依赖注入：调用 verify_proxy_key 函数进行验证，并将验证通过的代理密钥和配置注入到此参数
    key_manager: APIKeyManager = Depends(get_key_manager), # 注入 Key Manager
    http_client: httpx.AsyncClient = Depends(get_http_client) # 注入 HTTP Client
):
    """
    处理聊天补全的 POST 请求（流式和非流式）。
    """
    request_type = 'stream' if request_data.stream else 'non-stream' # 判断请求是流式还是非流式
    # 调用 request_processor 中的核心处理逻辑
    # 将验证通过的 auth_data 和注入的实例传递给处理器函数
    response = await process_request( # 调用核心处理函数处理请求
        chat_request=request_data,
        http_request=request,
        request_type=request_type,
        auth_data=auth_data, # 传递认证数据
        key_manager=key_manager, # 传递 Key Manager 实例
        http_client=http_client # 传递 HTTP Client 实例
    )

    if response is None:
        # process_request 理想情况下应该在无法返回时引发异常
        # 有效响应（例如，客户端在响应开始前断开连接）。
        # 如果它返回 None，则意味着这里需要处理一个问题。
        logger.error("process_request 意外返回 None。") # process_request 意外返回 None
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="请求处理中断或失败") # 引发 500 异常

    return response # 返回处理器生成的响应（可能是 StreamingResponse 或 JSONResponse）

@router.get("/debug/config", include_in_schema=False)
async def debug_config():
    """
    调试接口：返回应用程序读取到的 WEB_UI_PASSWORDS 配置。
    """
    return {"WEB_UI_PASSWORDS": config.WEB_UI_PASSWORDS}

