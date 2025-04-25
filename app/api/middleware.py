import logging # 导入日志模块 (Import logging module)
from fastapi import Request, HTTPException, status # 导入 FastAPI 相关组件 (Import FastAPI related components)

# 从其他模块导入必要的组件
# Import necessary components from other modules
from .. import config as app_config # 导入 config (Import config)
# 导入 context_store 以验证 Key (文件模式)
# Import context_store to validate Key (file mode)
from ..core import context_store # 导入 context_store 模块 (Import context_store module)
# 导入 db_utils 以检查数据库模式
# Import db_utils to check database mode
from ..core.db_utils import IS_MEMORY_DB # 导入是否为内存数据库的标志 (Import flag indicating if it's an in-memory database)

# 从 core.utils 导入 key_manager_instance
# Import key_manager_instance from core.utils
from ..core.utils import key_manager_instance # 导入 Key Manager 实例 (Import Key Manager instance)
from typing import Dict, Any # 导入 Dict 和 Any 用于类型提示 (Import Dict and Any for type hints)

# 获取日志记录器实例
# Get logger instance
logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

# 如果需要，以后可以在此处添加其他中间件函数或依赖项。
# Other middleware functions or dependencies can be added here if needed in the future.
async def verify_proxy_key(request: Request) -> Dict[str, Any]:
    """
    FastAPI 依赖项函数，用于验证 API 请求的 Authorization 头，并返回 Key 及其配置。
    - 如果使用内存数据库 (IS_MEMORY_DB=True)，则验证 Bearer 令牌是否等于 WEB_UI_PASSWORDS 中的一个。
    - 如果使用文件数据库 (IS_MEMORY_DB=False)，则验证 Bearer 令牌是否是数据库中有效的、活动的代理 Key，并获取其配置。
    FastAPI dependency function to verify the Authorization header of API requests and return the Key along with its configuration.
    - If using in-memory database (IS_MEMORY_DB=True), verifies if the Bearer token equals one of the WEB_UI_PASSWORDS.
    - If using file-based database (IS_MEMORY_DB=False), verifies if the Bearer token is a valid, active proxy key in the database and fetches its configuration.

    Args:
        request: FastAPI 请求对象。The FastAPI request object.

    Returns:
        Dict[str, Any]: 包含 'key' (str) 和 'config' (Dict[str, Any]) 的字典。A dictionary containing 'key' (str) and 'config' (Dict[str, Any]).

    Raises:
        HTTPException: 如果认证失败。If authentication fails.
    """
    auth_header: str | None = request.headers.get("Authorization") # 从请求头获取 Authorization 字段 (Get Authorization header from request headers)
    # 检查标头是否存在且以 "Bearer " 开头
    # Check if the header exists and starts with "Bearer "
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # 未授权状态码 (Unauthorized status code)
            detail="未授权：缺少或无效的令牌格式。预期格式：'Bearer <token>'。", # 错误详情 (Error detail)
            headers={"WWW-Authenticate": "Bearer"}, # WWW-Authenticate 头 (WWW-Authenticate header)
        )
    # 提取令牌部分
    # Extract the token part
    try:
        token = auth_header.split(" ")[1] # 从 "Bearer <token>" 中提取令牌部分 (Extract the token part from "Bearer <token>")
    except IndexError:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # 未授权状态码 (Unauthorized status code)
            detail="未授权：'Bearer ' 后的令牌格式无效。", # 错误详情 (Error detail)
            headers={"WWW-Authenticate": "Bearer"}, # WWW-Authenticate 头 (WWW-Authenticate header)
        )

    # 根据数据库模式选择验证方式
    # Choose verification method based on database mode
    if IS_MEMORY_DB: # 检查当前是否为内存数据库模式 (Check if currently in memory database mode)
        # --- 内存数据库模式：使用 WEB_UI_PASSWORDS 验证 ---
        # --- In-memory Database Mode: Verify using WEB_UI_PASSWORDS ---
        if not app_config.WEB_UI_PASSWORDS: # 内存模式下必须设置 WEB_UI_PASSWORDS (PASSWORD 环境变量) (WEB_UI_PASSWORDS (PASSWORD environment variable) must be set in memory mode)
            logger.error("API 认证失败(内存模式)：未设置 WEB_UI_PASSWORDS (PASSWORD 环境变量)。") # Log authentication failure in memory mode
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, # 服务不可用状态码 (Service Unavailable status code)
                detail="服务配置错误：缺少 API 认证密码。", # 错误详情 (Error detail)
            )
        # 检查提供的令牌是否在配置的密码列表中
        # Check if the provided token is in the list of configured passwords
        if token not in app_config.WEB_UI_PASSWORDS:
            logger.warning(f"API 认证失败(内存模式)：提供的令牌与配置的密码不匹配。") # Log authentication failure in memory mode
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, # 未授权状态码 (Unauthorized status code)
                detail="未授权：无效的令牌。", # 错误详情 (Error detail)
                headers={"WWW-Authenticate": "Bearer"}, # WWW-Authenticate 头 (WWW-Authenticate header)
            )
        logger.debug(f"API 认证成功 (内存模式，使用 Key: {token[:8]}...).") # Log successful authentication in memory mode (DEBUG level)
        # 将验证通过的令牌（即用户提供的密码/key）存储在请求状态中
        # Store the validated token (i.e., the password/key provided by the user) in the request state
        request.state.proxy_key = token # 存储代理 Key 到请求状态 (Store proxy key to request state)
        # 在内存模式下，配置就是默认值
        # In memory mode, the configuration is the default value
        config_data = {'enable_context_completion': True} # 内存模式下默认启用 (Enabled by default in memory mode)
        return {"key": token, "config": config_data} # 返回 Key 和默认配置 (Return Key and default config)
    else:
        # --- 文件数据库模式：使用数据库中的代理 Key 验证并获取配置 ---
        # --- File-based Database Mode: Verify using proxy keys from the database and fetch configuration ---
        # 检查 Key 是否有效且活动
        # Check if the Key is valid and active
        if not await context_store.is_valid_proxy_key(token): # is_valid_proxy_key 现在是 async 的 (is_valid_proxy_key is now async)
            logger.warning(f"API 认证失败(文件模式)：提供的代理 Key 无效或非活动。Key: {token[:8]}...") # Log authentication failure
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, # 禁止访问状态码 (Forbidden status code)
                detail="未授权：无效或非活动的代理 API Key。", # 错误详情 (Error detail)
            )

        # Key 有效，获取其配置
        # Key is valid, fetch its configuration
        config_data = key_manager_instance.get_key_config(token) # 从 KeyManager 获取配置 (Get config from KeyManager)
        if config_data is None:
             # 如果 Key 在数据库中有效但在 KeyManager 中没有配置，这不应该发生，记录错误并返回默认配置
             # If the Key is valid in the database but has no configuration in KeyManager, this should not happen, log error and return default config
             logger.error(f"文件模式下，Key {token[:8]}... 在数据库中有效，但在 KeyManager 中找不到配置。返回默认配置。") # Log error
             config_data = {'enable_context_completion': True} # 返回默认配置 (Return default config)

        logger.debug(f"API 认证成功 (文件模式，使用代理 Key: {token[:8]}...)，配置: {config_data}") # Log successful authentication and config (DEBUG level)
        # 将有效的代理 Key 存储在 request state 中
        # Store the valid proxy key in the request state
        request.state.proxy_key = token # 存储代理 Key 到请求状态 (Store proxy key to request state)
        return {"key": token, "config": config_data} # 返回 Key 和配置 (Return Key and config)
