from app.core.context_store import load_context_as_gemini
# -*- coding: utf-8 -*-
"""
处理 Gemini 原生 API (v2) 相关的路由。
"""
import logging # 导入日志模块
from fastapi import APIRouter, Request, HTTPException, status, Depends, Path # 导入 FastAPI 相关组件
from fastapi.responses import JSONResponse # 导入 JSONResponse
from typing import Dict, Any # 导入类型提示

# 导入自定义模块
from app.core.gemini import GeminiClient # 导入 GeminiClient
from app.core.response_wrapper import ResponseWrapper # 导入响应包装类
from app.core.context_store import load_context, save_context, convert_openai_to_gemini_contents, convert_gemini_to_storage_format # 导入上下文管理函数和转换函数
from app.core.key_manager_class import APIKeyManager # 导入类型
import httpx # 导入 httpx 用于类型提示
# 导入依赖注入函数
from app.core.dependencies import get_key_manager, get_http_client
# 导入请求工具函数
from app.api.rate_limit_utils import check_rate_limits_and_update_counts, update_token_counts
from app.core.request_helpers import get_client_ip, get_current_timestamps
from app import config as app_config # 导入应用配置
from app.core.db_utils import IS_MEMORY_DB # 导入数据库模式标志
from app.config import ENABLE_CONTEXT_COMPLETION # 导入全局上下文补全配置

# 导入认证依赖项
from app.api.middleware import verify_proxy_key # 导入代理 Key 验证依赖

# 导入 Pydantic 模型
from app.api.models import GeminiGenerateContentRequestV2, GeminiGenerateContentResponseV2 # 导入 v2 请求和响应模型

logger = logging.getLogger('my_logger') # 获取日志记录器实例

v2_router = APIRouter() # 创建 APIRouter 实例

@v2_router.post("/models/{model}:generateContent", response_model=GeminiGenerateContentResponseV2) # 定义 POST 请求端点，指定响应模型
async def generate_content_v2(
    request: Request, # FastAPI 请求对象
    request_body: GeminiGenerateContentRequestV2, # 请求体，使用 Pydantic 模型进行验证
    model: str = Path(..., description="要使用的 Gemini 模型名称"), # 从路径参数获取模型名称
    auth_data: Dict[str, Any] = Depends(verify_proxy_key), # 依赖项：验证代理 Key 并获取 Key 和配置
    key_manager: APIKeyManager = Depends(get_key_manager), # 注入 Key Manager
    http_client: httpx.AsyncClient = Depends(get_http_client), # 注入 HTTP Client
):
    """
    处理 Gemini 原生 API 的 generateContent 请求 (/v2)。
    """
    proxy_key = auth_data.get("key") # 从认证数据中获取代理 Key
    key_config = auth_data.get("config", {}) # 从认证数据中获取 Key 配置，默认为空字典
    enable_context = key_config.get('enable_context_completion', ENABLE_CONTEXT_COMPLETION) # 获取 Key 的上下文补全配置，如果 Key 配置中没有则使用全局配置

    logger.info(f"收到 /v2/models/{model}:generateContent 请求，使用 Key: {proxy_key[:8]}..., 上下文补全: {enable_context}") # 记录收到的请求信息

    # 初始化 Gemini 客户端，传入共享的 http_client
    client = GeminiClient(api_key=proxy_key, http_client=http_client) # 使用代理 Key 初始化 Gemini 客户端

    # 获取并注入上下文 (如果启用)
    original_contents = request_body.contents # 保存原始请求内容
    if enable_context: # 如果启用了上下文补全
        # 加载历史上下文并转换为 Gemini 格式
        gemini_context = await load_context_as_gemini(proxy_key) # 加载并转换历史上下文
        if gemini_context: # 如果存在上下文历史
            # 将上下文注入到当前请求内容的开头
            request_body.contents = gemini_context + original_contents # 注入上下文
            logger.debug(f"为 Key {proxy_key[:8]}... 注入了 {len(gemini_context)} 条上下文消息。") # 记录注入的上下文数量
        else:
            logger.debug(f"Key {proxy_key[:8]}... 没有找到上下文或加载失败，跳过注入。") # 没有找到上下文或加载失败

    # --- 获取客户端 IP 和时间戳 ---
    client_ip = get_client_ip(request) # 获取客户端 IP
    _, today_date_str_pt = get_current_timestamps() # 获取 PT 日期字符串

    # --- 速率限制检查 ---
    limits = app_config.MODEL_LIMITS.get(model) # 获取模型限制
    if not check_rate_limits_and_update_counts(proxy_key, model, limits): # 检查并更新速率限制计数
        # 如果达到限制，check_rate_limits_and_update_counts 会记录警告
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, # 429 状态码
            detail=f"API Key for model '{model}' has reached rate limits. Please try again later." # 错误详情
        )

    # 调用 Gemini API
    try:
        # 将 Pydantic 模型转换为字典，以便传递给 GeminiClient
        request_payload = request_body.model_dump(exclude_none=True) # 转换为字典，排除 None 值
        logger.debug(f"调用 Gemini API，模型: {model}, Payload: {request_payload}") # 调用 Gemini API
        # 调用 GeminiClient 的 generate_content 方法
        gemini_response = await client.generate_content(model_name=model, request_payload=request_payload) # 调用 Gemini API
        logger.debug(f"收到 Gemini API 响应: {gemini_response}") # 收到 Gemini API 响应

        # --- 更新 Token 计数 ---
        prompt_tokens = None # 初始化 prompt_tokens
        if isinstance(gemini_response, dict) and 'usageMetadata' in gemini_response: # 检查响应是否为字典且包含 usageMetadata
            prompt_tokens = gemini_response['usageMetadata'].get('promptTokenCount') # 获取 promptTokenCount
        update_token_counts(proxy_key, model, limits, prompt_tokens, client_ip, today_date_str_pt) # 更新 token 计数

        # 存储上下文 (如果启用)
        if enable_context and gemini_response and gemini_response.get('candidates'): # 如果启用了上下文补全且响应有效
            # 提取用户请求内容和模型响应内容
            # 假设原始请求内容的最后一条是用户消息
            user_message_gemini = original_contents[-1] if original_contents else None # 获取用户消息
            # 假设响应的第一个候选的 content 是模型响应
            model_response_gemini = gemini_response['candidates'][0]['content'] if gemini_response.get('candidates') else None # 获取模型响应

            if user_message_gemini and model_response_gemini: # 如果用户消息和模型响应都存在
                # 将 Gemini 格式的用户请求和模型响应转换为存储格式 (OpenAI 格式)
                new_context_entry = convert_gemini_to_storage_format(user_message_gemini, model_response_gemini) # 转换格式
                if new_context_entry: # 如果转换成功
                    # 加载现有上下文，添加新条目，然后保存
                    existing_context = await load_context(proxy_key) # 重新加载现有上下文
                    updated_context = (existing_context or []) + new_context_entry # 合并新旧上下文
                    await save_context(proxy_key, updated_context) # 保存更新后的上下文
                    logger.debug(f"为 Key {proxy_key[:8]}... 存储了新的上下文回合。") # 存储了新的上下文回合
                else:
                    logger.warning(f"为 Key {proxy_key[:8]}... 转换 Gemini 请求/响应为存储格式失败，跳过上下文存储。") # 转换 Gemini 请求/响应为存储格式失败
            else:
                 logger.warning(f"为 Key {proxy_key[:8]}... 存储上下文失败：无法提取用户消息或模型响应。") # 存储上下文失败：无法提取用户消息或模型响应

        # 返回 Gemini 响应
        # 直接返回原始 Gemini 响应，不进行 OpenAI 包装
        return JSONResponse(content=gemini_response) # 返回 JSON 响应

    except HTTPException as e:
        # 捕获 FastAPI HTTPException 并重新抛出
        raise e
    except Exception as e:
        # 捕获其他所有异常，记录并返回 500 错误
        logger.error(f"处理 /v2/models/{model}:generateContent 请求时发生错误 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 处理 /v2/models/{model}:generateContent 请求时发生错误
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, # 内部服务器错误状态码
            detail=f"处理请求时发生内部错误: {e}" # 错误详情
        )

