import logging # 导入日志模块
from fastapi import Request, HTTPException, status # 导入 FastAPI 相关组件

# 从其他模块导入必要的组件
from app import config as app_config # 导入 config
# 导入 context_store 以验证 Key (文件模式)
from app.core import context_store # 导入 context_store 模块
# 导入 db_utils 以检查数据库模式
from app.core.db_utils import IS_MEMORY_DB # 导入是否为内存数据库的标志

# 从 core.utils 导入 key_manager_instance
from app.core.key_manager_class import key_manager_instance # 导入 Key Manager 实例
from typing import Dict, Any # 导入 Dict 和 Any 用于类型提示

# 获取日志记录器实例
logger = logging.getLogger('my_logger') # 获取日志记录器实例

async def verify_proxy_key(request: Request) -> Dict[str, Any]:
    """
    FastAPI 依赖项函数，用于验证 API 请求的 Authorization 头，并返回 Key 及其配置。
    - 如果使用内存数据库 (IS_MEMORY_DB=True)，则验证 Bearer 令牌是否等于 WEB_UI_PASSWORDS 中的一个。
    - 如果使用文件数据库 (IS_MEMORY_DB=False)，则验证 Bearer 令牌是否是数据库中有效的、活动的代理 Key，并获取其配置。

    Args:
        request: FastAPI 请求对象。

    Returns:
        Dict[str, Any]: 包含 'key' (str) 和 'config' (Dict[str, Any]) 的字典。

    Raises:
        HTTPException: 如果认证失败。
    """
    auth_header: str | None = request.headers.get("Authorization") # 从请求头获取 Authorization 字段
    # 检查标头是否存在且以 "Bearer " 开头
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # 未授权状态码
            detail="未授权：缺少或无效的令牌格式。预期格式：'Bearer <token>'。", # 错误详情
            headers={"WWW-Authenticate": "Bearer"}, # WWW-Authenticate 头
        )
    # 提取令牌部分
    try:
        token = auth_header.split(" ")[1] # 从 "Bearer <token>" 中提取令牌部分
    except IndexError:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # 未授权状态码
            detail="未授权：'Bearer ' 后的令牌格式无效。", # 错误详情
            headers={"WWW-Authenticate": "Bearer"}, # WWW-Authenticate 头
        )

    # 根据数据库模式选择验证方式
    if IS_MEMORY_DB: # 检查当前是否为内存数据库模式
        # --- 内存数据库模式：使用 WEB_UI_PASSWORDS 验证 ---
        if not app_config.WEB_UI_PASSWORDS: # 内存模式下必须设置 WEB_UI_PASSWORDS (PASSWORD 环境变量)
            logger.error("API 认证失败(内存模式)：未设置 WEB_UI_PASSWORDS (PASSWORD 环境变量)。") # API 认证失败(内存模式)：未设置 WEB_UI_PASSWORDS
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, # 服务不可用状态码
                detail="服务配置错误：缺少 API 认证密码。", # 错误详情
            )
        # 检查提供的令牌是否在配置的密码列表中
        if token not in app_config.WEB_UI_PASSWORDS:
            logger.warning(f"API 认证失败(内存模式)：提供的令牌与配置的密码不匹配。") # API 认证失败(内存模式)：提供的令牌与配置的密码不匹配
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, # 未授权状态码
                detail="未授权：无效的令牌。", # 错误详情
                headers={"WWW-Authenticate": "Bearer"}, # WWW-Authenticate 头
            )
        logger.debug(f"API 认证成功 (内存模式，使用 Key: {token[:8]}...).") # API 认证成功 (内存模式)
        # 将验证通过的令牌（即用户提供的密码/key）存储在请求状态中
        request.state.proxy_key = token # 存储代理 Key 到请求状态
        # 在内存模式下，配置就是默认值
        config_data = {'enable_context_completion': True} # 内存模式下默认启用
        return {"key": token, "config": config_data} # 返回 Key 和默认配置
    else:
        # --- 文件数据库模式：使用数据库中的代理 Key 验证并获取配置 ---
        if not await context_store.is_valid_proxy_key(token): # is_valid_proxy_key 现在是 async 的
            logger.warning(f"API 认证失败(文件模式)：提供的代理 Key 无效或非活动。Key: {token[:8]}...") # API 认证失败(文件模式)：提供的代理 Key 无效或非活动
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, # 禁止访问状态码
                detail="未授权：无效或非活动的代理 API Key。", # 错误详情
            )

        # Key 有效，获取其配置
        config_data = key_manager_instance.get_key_config(token) # 从 KeyManager 获取配置
        if config_data is None:
             # 如果 Key 在数据库中有效但在 KeyManager 中没有配置，这不应该发生，记录错误并返回默认配置
             logger.error(f"文件模式下，Key {token[:8]}... 在数据库中有效，但在 KeyManager 中找不到配置。返回默认配置。") # 文件模式下，Key 在数据库中有效，但在 KeyManager 中找不到配置
             config_data = {'enable_context_completion': True} # 返回默认配置

        logger.debug(f"API 认证成功 (文件模式，使用代理 Key: {token[:8]}...)，配置: {config_data}") # API 认证成功 (文件模式)
        # 将有效的代理 Key 存储在 request state 中
        request.state.proxy_key = token # 存储代理 Key 到请求状态
        return {"key": token, "config": config_data} # 返回 Key 和配置
