import logging # 导入日志模块
from fastapi import Request, HTTPException, status

# 从其他模块导入必要的组件
from .. import config as app_config # 导入 config
# 导入 context_store 以验证 Key (文件模式)
from ..core import context_store
# 导入 db_utils 以检查数据库模式
from ..core.db_utils import IS_MEMORY_DB

# 获取日志记录器实例
logger = logging.getLogger('my_logger')

async def verify_password(request: Request):
    """
    FastAPI 依赖项函数，用于验证 Authorization 头中的 Bearer 令牌
    是否与配置的 API 密钥 (PASSWORD) 匹配。
    """
    # 仅当在环境/配置中设置了 PASSWORD 时才强制执行密码检查
    if app_config.PASSWORD: # 修正：使用导入的 config
        auth_header = request.headers.get("Authorization")
        # 检查标头是否存在且以 "Bearer " 开头
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="未授权：缺少或无效的令牌格式。预期格式：'Bearer <token>'。" # 翻译
            )
        # 提取令牌部分
        try:
            token = auth_header.split(" ")[1]
        except IndexError:
             raise HTTPException(
                status_code=401,
                detail="未授权：'Bearer ' 后的令牌格式无效。" # 翻译
            )
        # 将提取的令牌与配置的密码进行比较
        if token != app_config.PASSWORD: # 修正：使用导入的 config
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
    auth_header = request.headers.get("Authorization")
    # 检查标头是否存在且以 "Bearer " 开头
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权：缺少或无效的令牌格式。预期格式：'Bearer <token>'。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # 提取令牌部分
    try:
        token = auth_header.split(" ")[1]
    except IndexError:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权：'Bearer ' 后的令牌格式无效。",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 根据数据库模式选择验证方式
    if IS_MEMORY_DB: # 使用从 db_utils 导入的常量
        # --- 内存数据库模式：使用 PASSWORD 验证 ---
        if not app_config.PASSWORD:
            logger.error("API 认证失败(内存模式)：未设置 PASSWORD 环境变量。")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="服务配置错误：缺少 API 认证密码。",
            )
        if token != app_config.PASSWORD:
            logger.warning(f"API 认证失败(内存模式)：提供的令牌与 PASSWORD 不匹配。")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权：无效的令牌。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.debug("API 认证成功 (内存模式，使用 PASSWORD)。")
        # 在内存模式下，我们仍然可以将 PASSWORD (作为 token) 存储在 state 中，
        # 以便上下文管理等功能（如果需要）可以基于它工作，尽管所有客户端共享它。
        request.state.proxy_key = token
        return token
    else:
        # --- 文件数据库模式：使用数据库中的代理 Key 验证 ---
        if not context_store.is_valid_proxy_key(token):
            # is_valid_proxy_key 内部会记录 Key 无效的警告
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, # 使用 403 表示令牌格式正确但无效/无权限
                detail="未授权：无效或非活动的代理 API Key。",
            )
        logger.debug(f"API 认证成功 (文件模式，使用代理 Key: {token[:8]}...)。")
        # 将有效的代理 Key 存储在 request state 中
        request.state.proxy_key = token
        return token