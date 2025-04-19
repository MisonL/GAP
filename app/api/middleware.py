import logging # 导入日志模块
from fastapi import Request, HTTPException, status

# 从其他模块导入必要的组件
from .. import config as app_config # 导入 config
# 导入 context_store 以验证 Key (文件模式)
from ..core import context_store
# 导入 db_utils 以检查数据库模式
from ..core.db_utils import IS_MEMORY_DB

# 获取日志记录器实例
logger = logging.getLogger('my_logger') # 获取日志记录器实例

async def verify_password(request: Request):
    """
    FastAPI 依赖项函数，用于验证 Authorization 头中的 Bearer 令牌
    是否与配置的 API 密钥 (PASSWORD) 匹配。
    """
    # 仅当在环境/配置中设置了 PASSWORD 时才强制执行密码检查
    if app_config.PASSWORD: # 检查是否在配置中设置了全局密码
        auth_header = request.headers.get("Authorization") # 从请求头获取 Authorization 字段
        # 检查标头是否存在且以 "Bearer " 开头
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="未授权：缺少或无效的令牌格式。预期格式：'Bearer <token>'。" # 翻译
            )
        # 提取令牌部分
        try:
            token = auth_header.split(" ")[1] # 从 "Bearer <token>" 中提取令牌部分
        except IndexError:
             raise HTTPException(
                status_code=401,
                detail="未授权：'Bearer ' 后的令牌格式无效。" # 翻译
            )
        # 将提取的令牌与配置的密码进行比较
        if token != app_config.PASSWORD: # 将提取的令牌与配置的密码进行比较
            raise HTTPException(status_code=401, detail="未授权：无效的令牌。")

# 如果需要，以后可以在此处添加其他中间件函数或依赖项。

async def verify_proxy_key(request: Request) -> str:
    """
    FastAPI 依赖项函数，用于验证 API 请求的 Authorization 头。
    - 如果使用内存数据库 (IS_MEMORY_DB=True)，则验证 Bearer 令牌是否等于 PASSWORD 环境变量。
    - 如果使用文件数据库 (IS_MEMORY_DB=False)，则验证 Bearer 令牌是否是数据库中有效的、活动的代理 Key。

    Returns:
        str: 验证通过的令牌 (PASSWORD 或 代理 Key)。

    Raises:
        HTTPException: 如果认证失败。
    """
    auth_header = request.headers.get("Authorization") # 从请求头获取 Authorization 字段
    # 检查标头是否存在且以 "Bearer " 开头
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权：缺少或无效的令牌格式。预期格式：'Bearer <token>'。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # 提取令牌部分
    try:
        token = auth_header.split(" ")[1] # 从 "Bearer <token>" 中提取令牌部分
    except IndexError:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权：'Bearer ' 后的令牌格式无效。",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 根据数据库模式选择验证方式
    if IS_MEMORY_DB: # 检查当前是否为内存数据库模式
        # --- 内存数据库模式：使用 WEB_UI_PASSWORDS 验证 ---
        if not app_config.WEB_UI_PASSWORDS: # 内存模式下必须设置 WEB_UI_PASSWORDS (PASSWORD 环境变量)
            logger.error("API 认证失败(内存模式)：未设置 WEB_UI_PASSWORDS (PASSWORD 环境变量)。")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="服务配置错误：缺少 API 认证密码。",
            )
        # 检查提供的令牌是否在配置的密码列表中
        if token not in app_config.WEB_UI_PASSWORDS:
            logger.warning(f"API 认证失败(内存模式)：提供的令牌与配置的密码不匹配。")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权：无效的令牌。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.debug(f"API 认证成功 (内存模式，使用 Key: {token[:8]}...).")
        # 将验证通过的令牌（即用户提供的密码/key）存储在请求状态中
        request.state.proxy_key = token
        return token
    else:
        # --- 文件数据库模式：使用数据库中的代理 Key 验证 ---
        # 保持现有逻辑不变
        if not await context_store.is_valid_proxy_key(token): # is_valid_proxy_key 现在是 async 的
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="未授权：无效或非活动的代理 API Key。",
            )
        logger.debug(f"API 认证成功 (文件模式，使用代理 Key: {token[:8]}...)。")
        # 将有效的代理 Key 存储在 request state 中
        request.state.proxy_key = token
        return token