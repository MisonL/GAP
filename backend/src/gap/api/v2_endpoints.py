# -*- coding: utf-8 -*-
"""
处理 Gemini 原生 API (v2) 相关的路由。
"""
import logging  # 导入日志模块
from typing import Any, Dict, Optional  # 导入类型提示

import httpx  # 导入 httpx 用于类型提示
from fastapi import (  # 导入 FastAPI 相关组件
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Request,
    status,
)
from fastapi.responses import JSONResponse  # 导入 JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession  # 导入异步数据库会话类型

from gap import config as app_config  # 导入应用配置

# 导入认证依赖项
from gap.api.middleware import verify_proxy_key  # 导入代理 Key 验证依赖

# 导入 Pydantic 模型
from gap.api.models import (  # 导入 v2 请求和响应模型
    GeminiGenerateContentRequestV2,
    GeminiGenerateContentResponseV2,
)
from gap.config import ENABLE_CONTEXT_COMPLETION  # 导入全局上下文补全配置
from gap.core.context.store import (  # 导入上下文管理函数和转换函数 (新路径)
    ContextStore,
    convert_gemini_to_storage_format,
    load_context,
    load_context_as_gemini,
    save_context,
)
# 导入依赖注入函数
from gap.core.dependencies import get_db_session, get_http_client, get_key_manager
from gap.core.keys.manager import APIKeyManager  # 导入类型 (新路径)

# 复用 v1 的模型名称校验逻辑
from gap.core.processing.request_prep import validate_model_name
from gap.core.processing.utils import (  # (新路径)
    check_rate_limits_and_update_counts,
    update_token_counts,
)

# 导入自定义模块
from gap.core.services.gemini import GeminiClient  # Gemini 客户端

# 导入请求工具函数和处理工具函数
from gap.core.utils.request_helpers import (  # (新路径)
    get_client_ip,
    get_current_timestamps,
)

logger = logging.getLogger("my_logger")  # 获取日志记录器实例

v2_router = APIRouter()  # 创建 APIRouter 实例


async def _load_and_inject_context_v2(
    proxy_key: str,
    request_body: GeminiGenerateContentRequestV2,
    enable_context: bool,
    db: AsyncSession,
    context_store: ContextStore | None = None,
):
    """加载历史上下文并注入到请求体中。"""
    if not enable_context:
        logger.debug(f"Key {proxy_key[:8]}... 的上下文补全已禁用，跳过加载和注入。")
        return

    # 加载历史上下文并转换为 Gemini 格式
    if context_store is not None:
        loaded = await context_store.retrieve_context(
            user_id=proxy_key,
            context_key=proxy_key,
            db=db,
        )
        gemini_context = loaded or []
    else:
        gemini_context = await load_context_as_gemini(
            proxy_key, db=db
        )  # 回退到旧实现
    if gemini_context:  # 如果存在上下文历史
        # 将上下文注入到当前请求内容的开头
        request_body.contents = gemini_context + request_body.contents  # 注入上下文
        logger.debug(
            f"为 Key {proxy_key[:8]}... 注入了 {len(gemini_context)} 条上下文消息。"
        )  # 记录注入的上下文数量
    else:
        logger.debug(
            f"Key {proxy_key[:8]}... 没有找到上下文或加载失败，跳过注入。"
        )  # 没有找到上下文或加载失败


async def _save_context_after_v2_success(
    proxy_key: str,
    original_contents: list,
    gemini_response: Dict[str, Any],
    enable_context: bool,
    db: AsyncSession,
    context_store: ContextStore | None = None,
):
    """在 v2 API 调用成功后保存上下文。"""
    if (
        not enable_context
        or not gemini_response
        or not gemini_response.get("candidates")
    ):
        if enable_context:
            logger.debug(
                f"为 Key {proxy_key[:8]}... 跳过上下文存储：上下文补全未启用或响应无效。"
            )
        return

    # 提取用户请求内容和模型响应内容
    # 假设原始请求内容的最后一条是用户消息
    user_message_gemini = (
        original_contents[-1] if original_contents else None
    )  # 获取用户消息
    # 假设响应的第一个候选的 content 是模型响应
    model_response_gemini = (
        gemini_response.get("candidates", [{}])[0].get("content")
        if isinstance(gemini_response, dict)
        else None
    )

    # 规范化为字典结构，避免 SDK 对象导致的属性访问错误
    def _to_gemini_dict(obj: Any, default_role: str) -> Optional[Dict[str, Any]]:
        if obj is None:
            return None
        if isinstance(obj, dict):
            # 填充缺省 role
            if "role" not in obj:
                obj = {**obj, "role": default_role}
            return obj
        # 处理可能的 SDK 对象：obj.parts / obj.role
        role = getattr(obj, "role", default_role)
        parts = getattr(obj, "parts", None)
        if parts is not None:
            try:
                # 将 parts 转为普通列表/字典
                normalized_parts = []
                for p in parts:
                    if isinstance(p, dict):
                        normalized_parts.append(p)
                    else:
                        text = getattr(p, "text", None)
                        if text is not None:
                            normalized_parts.append({"text": text})
                return {"role": role, "parts": normalized_parts}
            except Exception:
                return None
        return None

    user_msg_dict = _to_gemini_dict(user_message_gemini, default_role="user")
    model_resp_dict = _to_gemini_dict(model_response_gemini, default_role="model")

    if user_msg_dict and model_resp_dict:
        try:
            new_context_entry = convert_gemini_to_storage_format(
                user_msg_dict, model_resp_dict
            )
            if new_context_entry:
                existing_context = await load_context(proxy_key, db=db)
                updated_context = (existing_context or []) + new_context_entry
                if context_store is not None:
                    if context_store.storage_mode == "memory":
                        await context_store.store_context(
                            user_id=proxy_key,
                            context_key=proxy_key,
                            context_value=updated_context,
                            ttl_seconds=None,
                            db=None,
                        )
                    else:
                        await context_store.store_context(
                            user_id=proxy_key,
                            context_key=proxy_key,
                            context_value=updated_context,
                            ttl_seconds=None,
                            db=db,
                        )
                else:
                    await save_context(proxy_key, updated_context, db=db)
                logger.debug(f"为 Key {proxy_key[:8]}... 存储了新的上下文回合。")
            else:
                logger.warning(
                    f"为 Key {proxy_key[:8]}... 转换 Gemini 请求/响应为存储格式失败，跳过上下文存储。"
                )
        except Exception as conv_err:
            logger.warning(
                f"上下文存储转换失败，已跳过 (Key {proxy_key[:8]}...): {conv_err}"
            )
    else:
        logger.debug(
            f"为 Key {proxy_key[:8]}... 跳过上下文存储（无法规范化用户/模型内容）。"
        )


@v2_router.post(
    "/models/{model}:generateContent", response_model=GeminiGenerateContentResponseV2
)  # 定义 POST 请求端点，指定响应模型
async def generate_content_v2(
    request: Request,  # FastAPI 请求对象
    request_body: GeminiGenerateContentRequestV2,  # 请求体，使用 Pydantic 模型进行验证
    model: str = Path(
        ..., description="要使用的 Gemini 模型名称"
    ),  # 从路径参数获取模型名称
    auth_data: Dict[str, Any] = Depends(
        verify_proxy_key
    ),  # 依赖项：验证代理 Key 并获取 Key 和配置
    key_manager: APIKeyManager = Depends(get_key_manager),  # 注入 Key Manager
    http_client: httpx.AsyncClient = Depends(get_http_client),  # 注入 HTTP Client
    db: AsyncSession = Depends(get_db_session),  # 注入异步数据库会话
):
    """
    处理 Gemini 原生 API 的 generateContent 请求 (/v2)。
    """
    raw_key = auth_data.get("key")  # 从认证数据中获取代理 Key
    if not isinstance(raw_key, str) or not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing proxy key.",
        )
    proxy_key: str = raw_key
    key_config = auth_data.get("config", {})  # 从认证数据中获取 Key 配置，默认为空字典
    context_store: ContextStore | None = getattr(
        request.app.state, "context_store_manager", None
    )
    enable_context = key_config.get(
        "enable_context_completion", ENABLE_CONTEXT_COMPLETION
    )  # 获取 Key 的上下文补全配置，如果 Key 配置中没有则使用全局配置

    # 对 v2 路径中的模型名称做统一校验和规范化（与 /v1 行为保持一致）
    request_id = f"v2_{proxy_key[:8] if proxy_key else 'anon'}_{model}"
    model = validate_model_name(model, request_id)

    logger.info(
        "收到 /v2/models/%s:generateContent 请求，使用 Key: %s..., 上下文补全: %s",
        model,
        (proxy_key or "<none>")[:8],
        enable_context,
    )

    # 初始化 Gemini 客户端，传入共享的 http_client
    client = GeminiClient(
        api_key=proxy_key, http_client=http_client
    )  # 使用代理 Key 初始化 Gemini 客户端

    # 获取并注入上下文 (如果启用) - 委托给辅助函数
    original_contents = request_body.contents  # 保存原始请求内容
    await _load_and_inject_context_v2(
        proxy_key,
        request_body,
        enable_context,
        db,
        context_store=context_store,
    )

    # --- 获取客户端 IP 和时间戳 ---
    client_ip = get_client_ip(request)  # 获取客户端 IP
    _, today_date_str_pt = get_current_timestamps()  # 获取 PT 日期字符串

    # --- 速率限制检查 ---
    limits = app_config.MODEL_LIMITS.get(
        model
    )  # 获取模型限制（此时 model 已通过 validate_model_name 规范化）
    if not check_rate_limits_and_update_counts(
        proxy_key, model, limits
    ):  # 检查并更新速率限制计数
        # 如果达到限制，check_rate_limits_and_update_counts 会记录警告
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,  # 429 状态码
            detail=(
                f"API Key for model '{model}' has reached rate limits. "
                "Please try again later."
            ),  # 错误详情
        )

    # 调用 Gemini API
    try:
        # 将 Pydantic 模型转换为字典，以便传递给 GeminiClient
        request_payload = request_body.model_dump(
            exclude_none=True
        )  # 转换为字典，排除 None 值
        logger.debug(
            f"调用 Gemini API，模型: {model}, Payload: {request_payload}"
        )  # 调用 Gemini API
        # 调用 GeminiClient 的 generate_content 方法
        gemini_response = await client.generate_content(
            model_name=model, request_payload=request_payload
        )  # 调用 Gemini API
        logger.debug(f"收到 Gemini API 响应: {gemini_response}")  # 收到 Gemini API 响应

        # --- 更新 Token 计数 ---
        prompt_tokens = None  # 初始化 prompt_tokens
        if (
            isinstance(gemini_response, dict) and "usageMetadata" in gemini_response
        ):  # 检查响应是否为字典且包含 usageMetadata
            prompt_tokens = gemini_response["usageMetadata"].get(
                "promptTokenCount"
            )  # 获取 promptTokenCount
        update_token_counts(
            proxy_key, model, limits, prompt_tokens, client_ip, today_date_str_pt
        )  # 更新 token 计数

        # 存储上下文 (如果启用) - 委托给辅助函数
        await _save_context_after_v2_success(
            proxy_key,
            original_contents,
            gemini_response,
            enable_context,
            db,
            context_store=context_store,
        )

        # 返回 Gemini 响应
        # 直接返回原始 Gemini 响应，不进行 OpenAI 包装
        return JSONResponse(content=gemini_response)  # 返回 JSON 响应

    except HTTPException as e:
        # 捕获 FastAPI HTTPException 并重新抛出
        raise e
    except Exception as e:
        # 捕获其他所有异常，记录并返回 500 错误
        logger.error(
            "处理 /v2/models/%s:generateContent 请求时发生错误 (Key: %s...): %s",
            model,
            proxy_key[:8],
            e,
            exc_info=True,
        )  # 处理 /v2/models/{model}:generateContent 请求时发生错误
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,  # 内部服务器错误状态码
            detail=f"处理请求时发生内部错误: {e}",  # 错误详情
        )
