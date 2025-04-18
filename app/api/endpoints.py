import asyncio
import json
import logging
import time # 导入 time 模块，用于 /v1/models 端点生成时间戳
import logging
from typing import List, Dict, Any, Optional # 导入类型提示，Literal 和 Tuple 已不再此模块使用
from fastapi import APIRouter, HTTPException, Request, Depends, status # 导入 FastAPI 相关组件：路由、HTTP异常、请求对象、依赖注入、状态码
from fastapi.responses import StreamingResponse # 导入流式响应对象
# 移除了未使用的导入: pytz, datetime, Counter, defaultdict, Form, HTMLResponse
from .. import config # 导入应用配置模块

# 从其他模块导入必要的组件
# 注意：移动后，相对导入路径需要调整
from .models import ChatCompletionRequest, ChatCompletionResponse, ModelList # 导入 API 请求和响应模型 (Choice, ResponseMessage 在 processor 中使用)
from ..core.gemini import GeminiClient # 导入 Gemini 客户端类
from ..core.utils import key_manager_instance as key_manager # 导入共享的密钥管理器实例，并重命名为 key_manager，用于 /v1/models
# verify_password 稍后可能被 Bearer token 认证取代 (此注释可能已过时)
from .middleware import verify_proxy_key # 导入代理密钥验证中间件/依赖项
# 导入处理器函数
from .request_processor import process_request # 导入核心请求处理函数
# 移除了先前由 root 或 process_request 使用的未使用的 config/tracking/log 导入
# safety_settings 现在可能由处理器使用，如果确认未使用则稍后移除
# from ..config import (
#     safety_settings,
#     safety_settings_g2
# )


# --- 此模块内需要的全局变量 ---
logger = logging.getLogger('my_logger') # 获取日志记录器实例
# key_manager 已在上面导入，用于 /v1/models


# --- APIRouter 实例 ---
router = APIRouter() # 创建一个 FastAPI APIRouter 实例，用于定义 API 路由

# --- 端点定义 ---

@router.get("/v1/models", response_model=ModelList)
async def list_models():
    """处理获取可用模型列表的 GET 请求。"""
    active_keys_count = key_manager.get_active_keys_count() # 获取当前有效的 API 密钥数量
    # 如果 GeminiClient.AVAILABLE_MODELS 为空，则确保填充它
    if not GeminiClient.AVAILABLE_MODELS and active_keys_count > 0:
        logger.info("首次请求模型列表，尝试获取...")
        try:
            key_to_use = None
            with key_manager.keys_lock: # 使用锁安全地访问密钥列表
                 if key_manager.api_keys: key_to_use = key_manager.api_keys[0] # 如果有有效密钥，选择第一个用于获取模型列表
            if key_to_use:
                all_models = await GeminiClient.list_available_models(key_to_use) # 调用 Gemini 客户端获取所有可用模型
                # 确保 AVAILABLE_MODELS 被正确更新
                GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models] # 清理模型名称（移除 "models/" 前缀）并存储到类变量
                logger.info(f"成功获取可用模型: {GeminiClient.AVAILABLE_MODELS}")
            else: logger.error("无法找到有效 Key 来获取模型列表。")
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            GeminiClient.AVAILABLE_MODELS = [] # 获取模型列表失败时，重置为空列表

    # 使用标准日志记录
    logger.info("接收到列出模型的请求", extra={'request_type': 'list_models', 'status_code': 200})
    # 返回列表，确保使用可能已更新的 AVAILABLE_MODELS
    return ModelList(data=[{"id": model, "object": "model", "created": int(time.time()), "owned_by": "organization-owner"} for model in GeminiClient.AVAILABLE_MODELS]) # 构建并返回符合 OpenAI API 格式的模型列表响应
# 移除了旧 process_request 错误处理的残留代码


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse, status_code=status.HTTP_200_OK)
async def chat_completions(
    request_data: ChatCompletionRequest, # 请求体数据，FastAPI 会自动解析 JSON 并验证其结构是否符合 ChatCompletionRequest 模型
    request: Request, # FastAPI 的原始 Request 对象，包含请求头、客户端 IP 等信息
    # 使用新的代理 Key 验证依赖，并将验证通过的 Key 注入
    proxy_key: str = Depends(verify_proxy_key) # 依赖注入：调用 verify_proxy_key 函数进行验证，并将验证通过的代理密钥注入到此参数
):
    """处理聊天补全的 POST 请求（流式和非流式）。"""
    request_type = 'stream' if request_data.stream else 'non-stream' # 判断请求是流式还是非流式
    # 调用 request_processor 中的核心处理逻辑
    # 将验证通过的 proxy_key 传递给处理器函数
    response = await process_request( # 调用核心处理函数处理请求
        chat_request=request_data,
        http_request=request,
        request_type=request_type,
        proxy_key=proxy_key # 将验证通过的代理密钥传递给处理器
    )

    if response is None:
        # process_request 理想情况下应该在无法返回时引发异常
        # 有效响应（例如，客户端在响应开始前断开连接）。
        # 如果它返回 None，则意味着这里需要处理一个问题。
        logger.error("process_request 意外返回 None。")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="请求处理中断或失败")

    return response # 返回处理器生成的响应（可能是 StreamingResponse 或 JSONResponse）

# 根据配置决定是否对根路径应用密码保护
# 移除了根路由处理器 (已移至 app/web/routes.py)
# 移除了 process_tool_calls 函数 (已移至 app/api/request_processor.py)