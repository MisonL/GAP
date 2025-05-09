# -*- coding: utf-8 -*-
"""
API 请求认证中间件/依赖项。
定义了用于验证 API 请求中提供的代理 Key 的函数。
"""
import logging # 导入日志模块
from fastapi import Request, HTTPException, status # 导入 FastAPI 相关组件
from typing import Dict, Any # 导入类型提示

# 从其他模块导入必要的组件
from app import config as app_config # 导入应用配置
# 导入 context_store 用于在文件模式下验证 Key (注意：此依赖关系可能需要审查，验证逻辑最好统一在 KeyManager 中)
from app.core.context import store as context_store # (新路径)
# 导入数据库模式标志
from app.core.database.utils import IS_MEMORY_DB # (新路径)
# 导入 KeyManager 类型提示
from app.core.keys.manager import APIKeyManager # (新路径)

# 获取日志记录器实例
logger = logging.getLogger('my_logger')

async def verify_proxy_key(request: Request) -> Dict[str, Any]:
    """
    FastAPI 依赖项函数，用于验证 API 请求头中的 `Authorization: Bearer <token>`。

    验证逻辑根据 `KEY_STORAGE_MODE` 配置而不同：
    - **内存模式 (`IS_MEMORY_DB=True`)**: 验证提供的 `<token>` 是否存在于环境变量 `PASSWORD` (即 `config.WEB_UI_PASSWORDS`) 定义的密码列表中。
    - **数据库模式 (`IS_MEMORY_DB=False`)**: 验证提供的 `<token>` 是否是数据库中存在且状态为激活 (`is_active=True`) 的 API Key。

    成功验证后，会从 `APIKeyManager` 获取该 Key 的配置信息，并将 Key 和配置信息作为字典返回。
    同时，会将验证通过的 Key 存储在 `request.state.proxy_key` 中，供后续请求处理函数使用。

    Args:
        request (Request): FastAPI 请求对象，用于访问请求头和应用状态 (app.state)。

    Returns:
        Dict[str, Any]: 一个包含验证通过的 'key' (str) 和其对应 'config' (Dict[str, Any]) 的字典。

    Raises:
        HTTPException:
            - 401 Unauthorized: 如果 Authorization 头缺失、格式错误、令牌无效或不匹配。
            - 403 Forbidden: 如果令牌在数据库模式下无效或非活动。
            - 503 Service Unavailable: 如果内存模式下未配置 `PASSWORD` 环境变量。
    """
    # 1. 从请求头获取 Authorization 字段
    auth_header: str | None = request.headers.get("Authorization")

    # 2. 检查 Authorization 头是否存在且格式是否为 "Bearer <token>"
    if not auth_header or not auth_header.startswith("Bearer "):
        logger.warning("请求缺少有效的 Authorization Bearer header。") # 记录警告
        # 抛出 401 错误
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权：缺少或无效的令牌格式。预期格式：'Bearer <token>'。",
            headers={"WWW-Authenticate": "Bearer"}, # 按标准添加 WWW-Authenticate 头
        )

    # 3. 提取 token 部分
    try:
        # 按空格分割 "Bearer <token>" 并获取第二部分
        token = auth_header.split(" ")[1]
    except IndexError: # 如果分割后没有第二部分，说明格式错误
        logger.warning("Authorization Bearer header 格式无效，缺少 token。") # 记录警告
        # 抛出 401 错误
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权：'Bearer ' 后的令牌格式无效。",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. 根据存储模式进行验证
    if IS_MEMORY_DB: # --- 内存数据库模式 ---
        # 检查环境变量 PASSWORD (即 config.WEB_UI_PASSWORDS) 是否已配置
        if not app_config.WEB_UI_PASSWORDS:
            logger.error("API 认证失败(内存模式)：未设置 WEB_UI_PASSWORDS (PASSWORD 环境变量)。") # 记录严重错误
            # 抛出 503 服务不可用错误，因为这是配置问题
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="服务配置错误：缺少 API 认证密码。",
            )
        # 检查提供的 token 是否在配置的密码列表中
        if token not in app_config.WEB_UI_PASSWORDS:
            logger.warning(f"API 认证失败(内存模式)：提供的令牌与配置的密码不匹配。") # 记录警告
            # 抛出 401 错误
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权：无效的令牌。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # 内存模式验证通过
        logger.debug(f"API 认证成功 (内存模式，使用 Key: {token[:8]}...).") # 记录调试日志
        # 将验证通过的 token (密码) 存储在请求状态中
        request.state.proxy_key = token
        # 在内存模式下，返回一个默认的配置字典
        config_data = {'enable_context_completion': True} # 假设内存模式下默认启用上下文
        return {"key": token, "config": config_data} # 返回包含 key 和 config 的字典

    else: # --- 数据库模式 ---
        # 注意：这里调用了 context_store.is_valid_proxy_key，这可能不是最佳实践。
        # Key 的验证逻辑最好统一由 APIKeyManager 或专门的认证服务处理。
        # 暂时保留此逻辑，但标记为可能需要重构。
        logger.warning("verify_proxy_key 正在调用 context_store.is_valid_proxy_key 进行验证，建议将验证逻辑移至 KeyManager。")
        # 调用 context_store 中的函数验证 Key 是否存在于数据库且处于活动状态
        if not await context_store.is_valid_proxy_key(token): # 注意：is_valid_proxy_key 是异步的
            logger.warning(f"API 认证失败(数据库模式)：提供的代理 Key 无效或非活动。Key: {token[:8]}...") # 记录警告
            # 抛出 403 禁止访问错误
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="未授权：无效或非活动的代理 API Key。",
            )

        # --- Key 有效，获取其配置 ---
        try:
            # 从应用状态 (app.state) 中获取共享的 APIKeyManager 实例
            key_manager_instance: APIKeyManager = request.app.state.key_manager
            # 调用 KeyManager 的方法获取该 Key 的配置信息
            config_data = key_manager_instance.get_key_config(token)
        except AttributeError:
             # 如果无法从 app.state 获取 key_manager，说明应用启动或配置有问题
             logger.error("无法从 request.app.state 获取 key_manager 实例！")
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误：Key 管理器未正确初始化")

        # 检查是否成功获取到配置
        if config_data is None:
             # 理论上，如果 is_valid_proxy_key 返回 True，那么 Key 应该存在于 KeyManager 中。
             # 如果在这里找不到配置，可能表示状态不一致。记录错误并使用默认配置。
             logger.error(f"数据库模式下，Key {token[:8]}... 在数据库中有效，但在 KeyManager 中找不到配置。可能存在状态不一致。返回默认配置。")
             config_data = {'enable_context_completion': True} # 使用默认配置作为后备

        # 数据库模式验证通过
        logger.debug(f"API 认证成功 (数据库模式，使用代理 Key: {token[:8]}...)，配置: {config_data}") # 记录调试日志
        # 将验证通过的代理 Key 存储在请求状态中，供后续处理函数使用
        request.state.proxy_key = token
        # 返回包含 Key 和其配置的字典
        return {"key": token, "config": config_data}
