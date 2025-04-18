import asyncio
import json
import logging
import time # time 用于 /v1/models
import logging
from typing import List, Dict, Any, Optional # Literal, Tuple 不再在此处使用
from fastapi import APIRouter, HTTPException, Request, Depends, status
from fastapi.responses import StreamingResponse
# 移除了未使用的导入: pytz, datetime, Counter, defaultdict, Form, HTMLResponse
from .. import config # 保留 config 导入

# 从其他模块导入必要的组件
# 注意：移动后，相对导入路径需要调整
from .models import ChatCompletionRequest, ChatCompletionResponse, ModelList # Choice, ResponseMessage 由 processor 使用
from ..core.gemini import GeminiClient
from ..core.utils import key_manager_instance as key_manager # key_manager 用于 /v1/models
# verify_password 稍后可能被 Bearer token 认证取代 (此注释可能已过时)
from .middleware import verify_proxy_key # 导入正确的依赖项
# 导入处理器函数
from .request_processor import process_request
# 移除了先前由 root 或 process_request 使用的未使用的 config/tracking/log 导入
# safety_settings 现在可能由处理器使用，如果确认未使用则稍后移除
# from ..config import (
#     safety_settings,
#     safety_settings_g2
# )


# --- 此模块内需要的全局变量 ---
logger = logging.getLogger('my_logger') # logger 可能仍需要
# key_manager 已在上面导入，用于 /v1/models


# --- APIRouter 实例 ---
router = APIRouter()

# --- 端点定义 ---

@router.get("/v1/models", response_model=ModelList)
async def list_models():
    """处理获取可用模型列表的 GET 请求。"""
    active_keys_count = key_manager.get_active_keys_count()
    # 如果 GeminiClient.AVAILABLE_MODELS 为空，则确保填充它
    if not GeminiClient.AVAILABLE_MODELS and active_keys_count > 0:
        logger.info("首次请求模型列表，尝试获取...")
        try:
            key_to_use = None
            with key_manager.keys_lock: # 直接访问
                 if key_manager.api_keys: key_to_use = key_manager.api_keys[0]
            if key_to_use:
                all_models = await GeminiClient.list_available_models(key_to_use)
                # 确保 AVAILABLE_MODELS 被正确更新
                GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models]
                logger.info(f"成功获取可用模型: {GeminiClient.AVAILABLE_MODELS}")
            else: logger.error("无法找到有效 Key 来获取模型列表。")
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            GeminiClient.AVAILABLE_MODELS = [] # 失败时重置

    # 使用标准日志记录
    logger.info("接收到列出模型的请求", extra={'request_type': 'list_models', 'status_code': 200})
    # 返回列表，确保使用可能已更新的 AVAILABLE_MODELS
    return ModelList(data=[{"id": model, "object": "model", "created": int(time.time()), "owned_by": "organization-owner"} for model in GeminiClient.AVAILABLE_MODELS])
# 移除了旧 process_request 错误处理的残留代码


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse, status_code=status.HTTP_200_OK)
async def chat_completions(
    request_data: ChatCompletionRequest, # 重命名以避免与下面的 'request' 冲突
    request: Request, # 保留原始请求对象名称
    # 使用新的代理 Key 验证依赖，并将验证通过的 Key 注入
    proxy_key: str = Depends(verify_proxy_key)
):
    """处理聊天补全的 POST 请求（流式和非流式）。"""
    request_type = 'stream' if request_data.stream else 'non-stream'
    # 调用 request_processor 中的核心处理逻辑
    # 将验证通过的 proxy_key 传递给处理器函数
    response = await process_request(
        chat_request=request_data,
        http_request=request,
        request_type=request_type,
        proxy_key=proxy_key # Pass the injected proxy_key
    )

    if response is None:
        # process_request 理想情况下应该在无法返回时引发异常
        # 有效响应（例如，客户端在响应开始前断开连接）。
        # 如果它返回 None，则意味着这里需要处理一个问题。
        logger.error("process_request 意外返回 None。")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="请求处理中断或失败")

    return response

# 根据配置决定是否对根路径应用密码保护
# 移除了根路由处理器 (已移至 app/web/routes.py)
# 移除了 process_tool_calls 函数 (已移至 app/api/request_processor.py)