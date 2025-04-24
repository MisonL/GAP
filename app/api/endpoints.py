import asyncio # 导入 asyncio 模块 (Import asyncio module)
import json # 导入 json 模块 (Import json module)
import logging # 导入 logging 模块 (Import logging module)
import time # 导入 time 模块，用于 /v1/models 端点生成时间戳 (Import time module, used for generating timestamps in the /v1/models endpoint)
from typing import List, Dict, Any, Optional # 导入类型提示，Literal 和 Tuple 已不再此模块使用 (Import type hints, Literal and Tuple are no longer used in this module)
from fastapi import APIRouter, HTTPException, Request, Depends, status # 导入 FastAPI 相关组件：路由、HTTP异常、请求对象、依赖注入、状态码 (Import FastAPI related components: router, HTTPException, Request, Depends, status codes)
from fastapi.responses import StreamingResponse # 导入流式响应对象 (Import StreamingResponse object)
from .. import config # 导入应用配置模块 (Import application configuration module)

# 从其他模块导入必要的组件
# Import necessary components from other modules
# 注意：移动后，相对导入路径需要调整
# Note: After moving, relative import paths need to be adjusted
from .models import ChatCompletionRequest, ChatCompletionResponse, ModelList # 导入 API 请求和响应模型 (ChatCompletionRequest, ChatCompletionResponse, ModelList) (Choice, ResponseMessage 在 processor 中使用) (Choice, ResponseMessage are used in the processor)
from ..core.gemini import GeminiClient # 导入 Gemini 客户端类 (Import GeminiClient class)
from ..core.utils import key_manager_instance as key_manager # 导入共享的密钥管理器实例，并重命名为 key_manager，用于 /v1/models (Import the shared key manager instance, rename it to key_manager, used for /v1/models)
from .middleware import verify_proxy_key # 导入代理密钥验证中间件/依赖项 (Import proxy key verification middleware/dependency)
# 导入处理器函数
# Import processor function
from .request_processor import process_request # 导入核心请求处理函数 (Import the core request processing function)


# --- 此模块内需要的全局变量 ---
# --- Global Variables Needed in This Module ---
logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)
# key_manager 已在上面导入，用于 /v1/models
# key_manager is already imported above, used for /v1/models


# --- APIRouter 实例 ---
# --- APIRouter Instance ---
router = APIRouter() # 创建一个 FastAPI APIRouter 实例，用于定义 API 路由 (Create a FastAPI APIRouter instance for defining API routes)

# --- 端点定义 ---
# --- Endpoint Definitions ---

@router.get("/v1/models", response_model=ModelList) # 定义 GET /v1/models 端点，响应模型为 ModelList (Define GET /v1/models endpoint, response model is ModelList)
async def list_models():
    """
    处理获取可用模型列表的 GET 请求。
    Handles GET requests to get the list of available models.
    """
    active_keys_count = key_manager.get_active_keys_count() # 获取当前有效的 API 密钥数量 (Get the number of currently active API keys)
    # 如果 GeminiClient.AVAILABLE_MODELS 为空，则确保填充它
    # If GeminiClient.AVAILABLE_MODELS is empty, ensure it is populated
    if not GeminiClient.AVAILABLE_MODELS and active_keys_count > 0: # 如果可用模型列表为空且有活跃 Key (If available models list is empty and there are active keys)
        logger.info("首次请求模型列表，尝试获取...") # Log attempt to get model list for the first time
        try:
            key_to_use = None # 初始化要使用的 Key (Initialize key to use)
            with key_manager.keys_lock: # 使用锁安全地访问密钥列表 (Use lock for safe access to the key list)
                 if key_manager.api_keys: key_to_use = key_manager.api_keys[0] # 如果有有效密钥，选择第一个用于获取模型列表 (If there are valid keys, select the first one to get the model list)
            if key_to_use: # 如果找到了要使用的 Key (If a key to use is found)
                all_models = await GeminiClient.list_available_models(key_to_use) # 调用 Gemini 客户端获取所有可用模型 (Call Gemini client to get all available models)
                # 确保 AVAILABLE_MODELS 被正确更新
                # Ensure AVAILABLE_MODELS is updated correctly
                GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models] # 清理模型名称（移除 "models/" 前缀）并存储到类变量 (Clean up model names (remove "models/" prefix) and store in class variable)
                logger.info(f"成功获取可用模型: {GeminiClient.AVAILABLE_MODELS}") # Log successful retrieval of available models
            else: logger.error("无法找到有效 Key 来获取模型列表。") # Log error if no valid key is found to get model list
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}") # 记录获取模型列表失败错误 (Log error getting model list)
            GeminiClient.AVAILABLE_MODELS = [] # 获取模型列表失败时，重置为空列表 (Reset to empty list if getting model list fails)

    # 使用标准日志记录
    # Use standard logging
    logger.info("接收到列出模型的请求", extra={'request_type': 'list_models', 'status_code': 200}) # Log receiving list models request
    # 返回列表，确保使用可能已更新的 AVAILABLE_MODELS
    # Return the list, ensuring the potentially updated AVAILABLE_MODELS is used
    return ModelList(data=[{"id": model, "object": "model", "created": int(time.time()), "owned_by": "organization-owner"} for model in GeminiClient.AVAILABLE_MODELS]) # 构建并返回符合 OpenAI API 格式的模型列表响应 (Build and return a model list response in OpenAI API format)


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse, status_code=status.HTTP_200_OK) # 定义 POST /v1/chat/completions 端点，响应模型为 ChatCompletionResponse，状态码为 200 (Define POST /v1/chat/completions endpoint, response model is ChatCompletionResponse, status code is 200)
async def chat_completions(
    request_data: ChatCompletionRequest, # 请求体数据，FastAPI 会自动解析 JSON 并验证其结构是否符合 ChatCompletionRequest 模型 (Request body data, FastAPI automatically parses JSON and validates its structure against the ChatCompletionRequest model)
    request: Request, # FastAPI 的原始 Request 对象，包含请求头、客户端 IP 等信息 (FastAPI's raw Request object, containing headers, client IP, etc.)
    # 使用新的代理 Key 验证依赖，并将验证通过的 Key 注入
    # Use the new proxy key verification dependency and inject the validated key
    proxy_key: str = Depends(verify_proxy_key) # 依赖注入：调用 verify_proxy_key 函数进行验证，并将验证通过的代理密钥注入到此参数 (Dependency injection: calls verify_proxy_key function for validation and injects the validated proxy key into this parameter)
):
    """
    处理聊天补全的 POST 请求（流式和非流式）。
    Handles POST requests for chat completions (streaming and non-streaming).
    """
    request_type = 'stream' if request_data.stream else 'non-stream' # 判断请求是流式还是非流式 (Determine if the request is streaming or non-streaming)
    # 调用 request_processor 中的核心处理逻辑
    # Call the core processing logic in request_processor
    # 将验证通过的 proxy_key 传递给处理器函数
    # Pass the validated proxy_key to the processor function
    response = await process_request( # 调用核心处理函数处理请求 (Call the core processing function to process the request)
        chat_request=request_data,
        http_request=request,
        request_type=request_type,
        proxy_key=proxy_key # 将验证通过的代理密钥传递给处理器 (Pass the validated proxy key to the processor)
    )

    if response is None:
        # process_request 理想情况下应该在无法返回时引发异常
        # process_request should ideally raise an exception when it cannot return
        # 有效响应（例如，客户端在响应开始前断开连接）。
        # a valid response (e.g., client disconnects before response starts).
        # 如果它返回 None，则意味着这里需要处理一个问题。
        # If it returns None, it means there is an issue that needs to be handled here.
        logger.error("process_request 意外返回 None。") # Log unexpected None return from process_request
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="请求处理中断或失败") # 引发 500 异常 (Raise 500 exception)

    return response # 返回处理器生成的响应（可能是 StreamingResponse 或 JSONResponse） (Return the response generated by the processor (could be StreamingResponse or JSONResponse))

# 根据配置决定是否对根路径应用密码保护
# Decide whether to apply password protection to the root path based on configuration
