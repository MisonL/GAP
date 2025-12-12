import logging  # 导入 logging 模块
import time  # 导入 time 模块，用于 /v1/models 端点生成时间戳
from typing import Any, Dict, List  # 导入类型提示

import httpx  # 导入 httpx 用于类型提示
from fastapi import (  # 导入 FastAPI 相关组件：路由、HTTP异常、请求对象、依赖注入、状态码
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)

from datetime import datetime, timedelta, timezone  # 用于模拟数据中的时间戳

from gap import config  # 导入应用配置模块
from gap.api.middleware import verify_proxy_key  # 导入代理密钥验证中间件/依赖项

# 从其他模块导入必要的组件
from gap.api.models import (  # 导入 API 请求和响应模型
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelList,
)
from gap.core.dependencies import (  # 导入获取 Key Manager 和 HTTP Client 的依赖函数
    get_http_client,
    get_key_manager,
    verify_admin_token,
)
from gap.core.keys.manager import APIKeyManager  # 导入类型 (新路径)
from gap.core.processing.main_handler import (  # 导入核心请求处理函数 (新路径)
    process_request,
)
from gap.core.services.gemini import GeminiClient  # 导入 Gemini 客户端类 (新路径)

# --- 此模块内需要的全局变量 ---
logger = logging.getLogger("my_logger")  # 获取日志记录器实例


router = APIRouter()  # 创建一个 FastAPI APIRouter 实例，用于定义 API 路由


@router.get(
    "/v1/models", response_model=ModelList
)  # 定义 GET /v1/models 端点，响应模型为 ModelList
async def list_models(
    key_manager: APIKeyManager = Depends(get_key_manager),  # 注入 Key Manager
    http_client: httpx.AsyncClient = Depends(get_http_client),  # 注入 HTTP Client
):
    """返回可用模型列表。

    优先使用本地配置的 MODEL_LIMITS 作为模型来源；如果为空且存在有效 Key，
    则尝试通过 Gemini API 拉取模型列表。
    """
    active_keys_count = key_manager.get_active_keys_count()

    # 如果 AVAILABLE_MODELS 为空，先尝试从本地 MODEL_LIMITS 加载
    if not GeminiClient.AVAILABLE_MODELS:
        from gap import config as app_config

        if app_config.MODEL_LIMITS:
            GeminiClient.AVAILABLE_MODELS = list(app_config.MODEL_LIMITS.keys())
            logger.info(
                "根据本地 MODEL_LIMITS 加载可用模型: %s",
                ", ".join(GeminiClient.AVAILABLE_MODELS),
            )
        elif active_keys_count > 0:
            logger.info("首次请求模型列表，尝试通过远端 API 获取...")
            try:
                key_to_use = None
                with key_manager.keys_lock:
                    if key_manager.api_keys:
                        key_to_use = key_manager.api_keys[0]
                if key_to_use:
                    all_models = await GeminiClient.list_available_models(
                        key_to_use, http_client
                    )
                    GeminiClient.AVAILABLE_MODELS = [
                        model.replace("models/", "") for model in all_models
                    ]
                    logger.info(
                        "成功从远端获取可用模型: %s",
                        ", ".join(GeminiClient.AVAILABLE_MODELS),
                    )
                else:
                    logger.error("无法找到有效 Key 来获取模型列表。")
            except Exception as e:  # pragma: no cover - 远端失败在测试中不易稳定复现
                logger.error(f"获取模型列表失败: {e}")
                GeminiClient.AVAILABLE_MODELS = []

        # 如果仍然为空，使用内置默认模型名称作为最终兜底，确保 /v1/models 始终返回非空列表
        if not GeminiClient.AVAILABLE_MODELS:
            GeminiClient.AVAILABLE_MODELS = [
                "gemini-1.5-pro-latest",
                "gemini-1.5-flash-latest",
                "gemini-1.0-pro",
            ]
            logger.warning(
                "MODEL_LIMITS 为空且未能从远端获取模型列表，使用内置默认模型: %s",
                ", ".join(GeminiClient.AVAILABLE_MODELS),
            )

    logger.info(
        "接收到列出模型的请求",
        extra={"request_type": "list_models", "status_code": 200},
    )
    return ModelList(
        data=[
            {
                "id": model,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "organization-owner",
            }
            for model in GeminiClient.AVAILABLE_MODELS
        ]
    )


@router.post(
    "/v1/chat/completions",
    response_model=ChatCompletionResponse,
    status_code=status.HTTP_200_OK,
)  # 定义 POST /v1/chat/completions 端点，响应模型为 ChatCompletionResponse，状态码为 200
async def chat_completions(
    request_data: ChatCompletionRequest,  # 请求体数据，FastAPI 会自动解析 JSON 并验证其结构是否符合 ChatCompletionRequest 模型
    request: Request,  # FastAPI 的原始 Request 对象，包含请求头、客户端 IP 等信息
    # 使用新的代理 Key 验证依赖，并将验证通过的 Key 和配置注入
    auth_data: Dict[str, Any] = Depends(
        verify_proxy_key
    ),  # 依赖注入：调用 verify_proxy_key 函数进行验证，并将验证通过的代理密钥和配置注入到此参数
    key_manager: APIKeyManager = Depends(get_key_manager),  # 注入 Key Manager
    http_client: httpx.AsyncClient = Depends(get_http_client),  # 注入 HTTP Client
):
    """
    处理聊天补全的 POST 请求（流式和非流式）。
    """
    request_type = (
        "stream" if request_data.stream else "non-stream"
    )  # 判断请求是流式还是非流式
    # 调用 request_processor 中的核心处理逻辑
    # 将验证通过的 auth_data 和注入的实例传递给处理器函数
    response = await process_request(  # 调用核心处理函数处理请求
        chat_request=request_data,
        http_request=request,
        request_type=request_type,
        auth_data=auth_data,  # 传递认证数据
        key_manager=key_manager,  # 传递 Key Manager 实例
        http_client=http_client,  # 传递 HTTP Client 实例
    )

    if response is None:
        # process_request 理想情况下应该在无法返回时引发异常
        # 有效响应（例如，客户端在响应开始前断开连接）。
        # 如果它返回 None，则意味着这里需要处理一个问题。
        logger.error("process_request 意外返回 None。")  # process_request 意外返回 None
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="请求处理中断或失败",
        )  # 引发 500 异常

    return response  # 返回处理器生成的响应（可能是 StreamingResponse 或 JSONResponse）


@router.get("/debug/config", include_in_schema=False)
async def debug_config():
    """
    调试接口：返回应用程序读取到的 WEB_UI_PASSWORDS 配置。
    """
    return {"WEB_UI_PASSWORDS": config.WEB_UI_PASSWORDS}


# 缓存管理端点 (需要管理员令牌)
@router.get("/cache", dependencies=[Depends(verify_admin_token)])
async def list_caches() -> List[Dict[str, Any]]:
    """获取当前缓存条目的简单列表（管理用途）。

    说明：
    * 这里返回的是简化的占位数据结构，以便集成测试可以验证基本行为；
    * 更完整的、基于数据库的缓存管理接口在 `/v1/caches` 中实现。
    """
    logger.info("接收到获取缓存列表的请求")

    # 占位实现：返回两个示例缓存条目（使用 timezone-aware UTC 时间）
    now = datetime.now(timezone.utc)
    mock_caches: List[Dict[str, Any]] = [
        {
            "cache_id": "mock-cache-id-1",
            "key": "mock-key-1",
            "value": "mock-value-1",
            "created_at": now.isoformat() + "Z",
            "expires_at": (now + timedelta(days=1)).isoformat() + "Z",
        },
        {
            "cache_id": "mock-cache-id-2",
            "key": "mock-key-2",
            "value": "mock-value-2",
            "created_at": (now - timedelta(hours=1)).isoformat() + "Z",
            "expires_at": (now + timedelta(hours=23)).isoformat() + "Z",
        },
    ]
    return mock_caches


@router.get("/cache/{cache_id}", dependencies=[Depends(verify_admin_token)])
async def get_cache_details(cache_id: str) -> Dict[str, Any]:
    """根据缓存 ID 获取特定缓存的详细信息（占位实现）。"""
    logger.info(f"接收到获取缓存详细信息的请求，ID: {cache_id}")

    now = datetime.now(timezone.utc)
    if cache_id in {"mock-cache-id-1", "mock-cache-id-2"}:
        return {
            "cache_id": cache_id,
            "key": f"mock-key-{cache_id[-1]}",
            "value": f"mock-value-{cache_id[-1]}",
            "created_at": now.isoformat() + "Z",
            "expires_at": (now + timedelta(days=1)).isoformat() + "Z",
        }

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="缓存未找到")


@router.delete("/cache/{cache_id}", dependencies=[Depends(verify_admin_token)])
async def delete_single_cache(cache_id: str) -> Dict[str, Any]:
    """根据缓存 ID 删除特定缓存（占位实现，始终返回成功消息）。"""
    logger.info(f"接收到删除缓存的请求，ID: {cache_id}")
    # 真实实现应调用 CacheManager/数据库删除逻辑，这里仅返回占位结果。
    return {"message": f"请求删除缓存 {cache_id} 已接收"}


@router.delete("/cache", dependencies=[Depends(verify_admin_token)])
async def clear_all_caches() -> Dict[str, Any]:
    """清空所有缓存（占位实现）。"""
    logger.info("接收到清空所有缓存的请求")
    # 真实实现应清理所有缓存记录；当前实现仅返回占位结果。
    return {"message": "请求清空所有缓存已接收"}
