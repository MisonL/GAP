# -*- coding: utf-8 -*-
"""
处理 Gemini 原生 API (v2) 相关的路由。
Handles Gemini native API (v2) related routes.
"""
import logging # 导入日志模块 (Import logging module)
from fastapi import APIRouter, Request, HTTPException, status, Depends, Path # 导入 FastAPI 相关组件 (Import FastAPI related components)
from fastapi.responses import JSONResponse # 导入 JSONResponse (Import JSONResponse)
from typing import Dict, Any # 导入类型提示 (Import type hints)

# 导入自定义模块
# Import custom modules
from ..core.gemini import GeminiClient # 导入 GeminiClient (Import GeminiClient)
from ..core.response_wrapper import wrap_gemini_response # 导入响应包装函数 (Import response wrapping function)
from ..core.context_store import load_context, save_context, convert_openai_to_gemini_contents, convert_gemini_to_storage_format # 导入上下文管理函数和转换函数 (Import context management functions and conversion functions)
from ..core.utils import key_manager_instance # 导入 Key Manager 实例 (Import Key Manager instance)
from ..core.tracking import track_usage # 导入使用情况跟踪函数 (Import usage tracking function)
from ..core.db_utils import IS_MEMORY_DB # 导入数据库模式标志 (Import database mode flag)
from ..config import ENABLE_CONTEXT_COMPLETION # 导入全局上下文补全配置 (Import global context completion configuration)

# 导入认证依赖项
# Import authentication dependency
from .middleware import verify_proxy_key # 导入代理 Key 验证依赖 (Import proxy key verification dependency)

# 导入 Pydantic 模型
# Import Pydantic models
from .models import GeminiGenerateContentRequestV2, GeminiGenerateContentResponseV2 # 导入 v2 请求和响应模型 (Import v2 request and response models)

logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

# 创建 APIRouter 实例
# Create APIRouter instance
v2_router = APIRouter() # 创建 APIRouter 实例 (Create APIRouter instance)

# 定义 /v2/models/{model}:generateContent 端点
# Define the /v2/models/{model}:generateContent endpoint
@v2_router.post("/models/{model}:generateContent", response_model=GeminiGenerateContentResponseV2) # 定义 POST 请求端点，指定响应模型 (Define POST request endpoint, specify response model)
async def generate_content_v2(
    request: Request, # FastAPI 请求对象 (FastAPI request object)
    request_body: GeminiGenerateContentRequestV2, # 请求体，使用 Pydantic 模型进行验证 (Request body, validated using Pydantic model)
    model: str = Path(..., description="要使用的 Gemini 模型名称"), # 从路径参数获取模型名称 (Get model name from path parameter)
    auth_data: Dict[str, Any] = Depends(verify_proxy_key) # 依赖项：验证代理 Key 并获取 Key 和配置 (Dependency: verify proxy key and get Key and config)
):
    """
    处理 Gemini 原生 API 的 generateContent 请求 (/v2)。
    Handles Gemini native API generateContent requests (/v2).
    """
    proxy_key = auth_data.get("key") # 从认证数据中获取代理 Key (Get proxy key from authentication data)
    key_config = auth_data.get("config", {}) # 从认证数据中获取 Key 配置，默认为空字典 (Get Key config from authentication data, default to empty dictionary)
    enable_context = key_config.get('enable_context_completion', ENABLE_CONTEXT_COMPLETION) # 获取 Key 的上下文补全配置，如果 Key 配置中没有则使用全局配置 (Get Key's context completion config, use global config if not in Key config)

    logger.info(f"收到 /v2/models/{model}:generateContent 请求，使用 Key: {proxy_key[:8]}..., 上下文补全: {enable_context}") # 记录收到的请求信息 (Log received request information)

    # 初始化 Gemini 客户端
    # Initialize Gemini client
    client = GeminiClient(api_key=proxy_key) # 使用代理 Key 初始化 Gemini 客户端 (Initialize Gemini client with proxy key)

    # 获取并注入上下文 (如果启用)
    # Fetch and inject context (if enabled)
    original_contents = request_body.contents # 保存原始请求内容 (Save original request contents)
    if enable_context: # 如果启用了上下文补全 (If context completion is enabled)
        context_history = await load_context(proxy_key) # 加载存储的上下文 (Load stored context)
        if context_history: # 如果存在上下文历史 (If context history exists)
            # 将存储的 OpenAI 格式历史转换为 Gemini 格式
            # Convert stored OpenAI format history to Gemini format
            gemini_context = convert_openai_to_gemini_contents(context_history) # 转换格式 (Convert format)
            # 将上下文注入到当前请求内容的开头
            # Inject context at the beginning of the current request contents
            request_body.contents = gemini_context + original_contents # 注入上下文 (Inject context)
            logger.debug(f"为 Key {proxy_key[:8]}... 注入了 {len(gemini_context)} 条上下文消息。") # 记录注入的上下文数量 (Log number of injected context messages)
        else:
            logger.debug(f"Key {proxy_key[:8]}... 没有找到上下文，跳过注入。") # Log that no context was found

    # 调用 Gemini API
    # Call Gemini API
    try:
        # 将 Pydantic 模型转换为字典，以便传递给 GeminiClient
        # Convert Pydantic model to dictionary to pass to GeminiClient
        request_payload = request_body.model_dump(exclude_none=True) # 转换为字典，排除 None 值 (Convert to dictionary, exclude None values)
        logger.debug(f"调用 Gemini API，模型: {model}, Payload: {request_payload}") # 记录调用 API 的信息 (Log API call information)
        # 调用 GeminiClient 的 generate_content 方法
        # Call GeminiClient's generate_content method
        gemini_response = await client.generate_content(model_name=model, request_payload=request_payload) # 调用 Gemini API (Call Gemini API)
        logger.debug(f"收到 Gemini API 响应: {gemini_response}") # 记录收到的 API 响应 (Log received API response)

        # 跟踪使用情况
        # Track usage
        await track_usage(proxy_key, model, request_payload, gemini_response) # 跟踪使用情况 (Track usage)

        # 存储上下文 (如果启用)
        # Store context (if enabled)
        if enable_context and gemini_response and gemini_response.get('candidates'): # 如果启用了上下文补全且响应有效 (If context completion is enabled and response is valid)
            # 提取用户请求内容和模型响应内容
            # Extract user request content and model response content
            # 假设原始请求内容的最后一条是用户消息
            # Assume the last message in original request contents is the user message
            user_message_gemini = original_contents[-1] if original_contents else None # 获取用户消息 (Get user message)
            # 假设响应的第一个候选的 content 是模型响应
            # Assume the content of the first candidate in the response is the model response
            model_response_gemini = gemini_response['candidates'][0]['content'] if gemini_response.get('candidates') else None # 获取模型响应 (Get model response)

            if user_message_gemini and model_response_gemini: # 如果用户消息和模型响应都存在 (If both user message and model response exist)
                # 将 Gemini 格式的用户请求和模型响应转换为存储格式 (OpenAI 格式)
                # Convert Gemini format user request and model response to storage format (OpenAI format)
                new_context_entry = convert_gemini_to_storage_format(user_message_gemini, model_response_gemini) # 转换格式 (Convert format)
                if new_context_entry: # 如果转换成功 (If conversion is successful)
                    # 加载现有上下文，添加新条目，然后保存
                    # Load existing context, add new entry, then save
                    existing_context = await load_context(proxy_key) # 重新加载现有上下文 (Reload existing context)
                    updated_context = (existing_context or []) + new_context_entry # 合并新旧上下文 (Combine new and old context)
                    await save_context(proxy_key, updated_context) # 保存更新后的上下文 (Save updated context)
                    logger.debug(f"为 Key {proxy_key[:8]}... 存储了新的上下文回合。") # 记录存储的上下文回合 (Log stored context turn)
                else:
                    logger.warning(f"为 Key {proxy_key[:8]}... 转换 Gemini 请求/响应为存储格式失败，跳过上下文存储。") # Log warning for failed conversion
            else:
                 logger.warning(f"为 Key {proxy_key[:8]}... 存储上下文失败：无法提取用户消息或模型响应。") # Log warning for failed context storage

        # 返回 Gemini 响应
        # Return Gemini response
        # 直接返回原始 Gemini 响应，不进行 OpenAI 包装
        # Return the raw Gemini response directly, without OpenAI wrapping
        return JSONResponse(content=gemini_response) # 返回 JSON 响应 (Return JSON response)

    except HTTPException as e:
        # 捕获 FastAPI HTTPException 并重新抛出
        # Catch FastAPI HTTPException and re-raise
        raise e
    except Exception as e:
        # 捕获其他所有异常，记录并返回 500 错误
        # Catch all other exceptions, log and return 500 error
        logger.error(f"处理 /v2/models/{model}:generateContent 请求时发生错误 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 记录错误 (Log error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, # 内部服务器错误状态码 (Internal Server Error status code)
            detail=f"处理请求时发生内部错误: {e}" # 错误详情 (Error detail)
        )

# TODO: 未来可以添加其他 /v2 端点，例如 /v2/models (列出模型)
# TODO: Other /v2 endpoints can be added in the future, e.g., /v2/models (list models)
