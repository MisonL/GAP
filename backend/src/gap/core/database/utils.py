# -*- coding: utf-8 -*-
"""
数据库工具函数。
包含数据库初始化、连接管理、以及针对数据库模型的 CRUD (创建、读取、更新、删除) 操作。
"""
import logging # 导入日志模块
import aiosqlite # 导入异步 SQLite 驱动
from typing import Dict, Any, List, Tuple, Optional, AsyncGenerator # 导入类型提示
from datetime import datetime, timezone # 导入日期时间处理
from sqlalchemy.orm import sessionmaker, Session # 导入 SQLAlchemy 同步会话 (可能用于某些旧代码或特定场景)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession # 导入 SQLAlchemy 异步引擎和会话
from gap.core.database.models import Base, UserKeyAssociation, KeyScore, Setting, ApiKey # 导入数据库模型
from sqlalchemy import select, update, delete # 导入 SQLAlchemy 查询、更新、删除构造器
from sqlalchemy.dialects import sqlite # 导入 SQLite 方言 (可能用于特定查询)
from sqlalchemy.sql import text # 导入用于执行原生 SQL 的 text 函数
from gap.core.tracking import key_scores_cache, cache_lock # 导入 Key 分数缓存和锁 (路径不变)
from contextlib import asynccontextmanager # 导入异步上下文管理器
import sqlalchemy # 导入 SQLAlchemy 核心库
import sqlalchemy.exc # 导入 SQLAlchemy 异常

# 配置日志记录
logger = logging.getLogger("my_logger") # 获取日志记录器实例

# --- 数据库路径和 URL 配置 ---
# 使用 os 模块动态确定数据库文件的绝对路径，增强可移植性
import os
# _current_dir = os.path.dirname(os.path.abspath(__file__)) # 获取当前文件所在目录的绝对路径
# _project_root = os.path.abspath(os.path.join(_current_dir, '..', '..')) # 获取项目根目录 (假设 utils.py 在 app/core/database/ 下)
# DATABASE_PATH = os.path.join(_project_root, 'app', 'data', 'context_store.db') # 拼接数据库文件的绝对路径

# --- 数据库路径和 URL 配置 (Hugging Face Spaces 部署优化) ---
# 根据 .clinerules/deployment-preferences.md，默认使用内存数据库
# 检查环境变量 HF_SPACE_ID 来判断是否在 Hugging Face 环境中
# 或者引入自定义环境变量 APP_DB_MODE 来控制数据库模式
# 同时考虑 app.config.KEY_STORAGE_MODE 的设置
from gap import config as app_config # 导入应用配置

# --- 调试日志：打印相关环境变量和配置值 ---
logger.debug(f"环境变量 HF_SPACE_ID: {os.getenv('HF_SPACE_ID')}")
logger.debug(f"环境变量 APP_DB_MODE: {os.getenv('APP_DB_MODE')}")
logger.debug(f"环境变量 KEY_STORAGE_MODE: {os.getenv('KEY_STORAGE_MODE')}")
logger.debug(f"从 app.config 导入的 KEY_STORAGE_MODE: {app_config.KEY_STORAGE_MODE}")
# --- 结束调试日志 ---

IS_HF_ENV = bool(os.getenv("HF_SPACE_ID")) # 简单判断是否在 Hugging Face 环境
use_memory_db_reason = []

if IS_HF_ENV:
    use_memory_db_reason.append("Hugging Face Environment (HF_SPACE_ID set)")
if os.getenv("APP_DB_MODE") == "memory":
    use_memory_db_reason.append("APP_DB_MODE=memory")
# 检查从 config 模块解析后的 KEY_STORAGE_MODE
if app_config.KEY_STORAGE_MODE == "memory":
    use_memory_db_reason.append(f"config.KEY_STORAGE_MODE is '{app_config.KEY_STORAGE_MODE}' (可能是默认值或环境变量设置)")


if use_memory_db_reason:
    DATABASE_PATH = ":memory:" # 内存数据库
    logger.info(f"最终决定使用内存数据库。原因: {'; '.join(use_memory_db_reason)}")
else:
    # 文件数据库逻辑
    logger.info(f"尝试使用文件数据库。内存条件评估: HF Env: {IS_HF_ENV}, APP_DB_MODE env: '{os.getenv('APP_DB_MODE')}', config.KEY_STORAGE_MODE: '{app_config.KEY_STORAGE_MODE}'")
    
    custom_db_path_from_env = app_config.CONTEXT_DB_PATH # 从配置中获取用户指定的路径
    
    if custom_db_path_from_env:
        logger.info(f"检测到环境变量 CONTEXT_DB_PATH 设置为: '{custom_db_path_from_env}'")
        # 如果用户指定了路径，尝试使用它
        # 需要确保路径的目录存在
        db_dir = os.path.dirname(custom_db_path_from_env)
        if db_dir: # 如果路径包含目录部分
            try:
                os.makedirs(db_dir, exist_ok=True)
                DATABASE_PATH = custom_db_path_from_env
                logger.info(f"使用 CONTEXT_DB_PATH 指定的数据库路径: {DATABASE_PATH}")
            except PermissionError as e:
                logger.error(f"根据 CONTEXT_DB_PATH 创建目录 '{db_dir}' 时发生权限错误: {e}。将回退到默认路径或内存数据库。")
                DATABASE_PATH = None # 标记为 None，以便后续逻辑回退
            except Exception as e:
                logger.error(f"根据 CONTEXT_DB_PATH 创建目录 '{db_dir}' 时发生未知错误: {e}。将回退到默认路径或内存数据库。")
                DATABASE_PATH = None # 标记为 None
        else: # 如果路径只是文件名，则在当前工作目录创建 (或需要进一步定义行为)
            DATABASE_PATH = custom_db_path_from_env
            logger.info(f"使用 CONTEXT_DB_PATH 指定的数据库文件名 (将在当前目录创建): {DATABASE_PATH}")
            # 注意：直接在当前目录创建可能不是最佳实践，但遵循了优先使用环境变量的原则。
            # 更好的做法是，如果只提供文件名，则在默认应用数据目录中使用该文件名。

    else: # 如果 CONTEXT_DB_PATH 未设置，则使用默认逻辑
        DATABASE_PATH = None # 确保在进入默认逻辑前为 None

    if DATABASE_PATH is None: # 如果 CONTEXT_DB_PATH 尝试失败或未设置
        logger.info("CONTEXT_DB_PATH 未设置或使用失败，尝试默认应用数据目录。")
        _home_dir = os.path.expanduser("~")
        _app_data_dir = os.path.join(_home_dir, '.gemini_api_proxy', 'data')
        try:
            os.makedirs(_app_data_dir, exist_ok=True)
            DATABASE_PATH = os.path.join(_app_data_dir, 'context_store.db')
            logger.info(f"默认数据库路径设置为: {DATABASE_PATH}")
        except PermissionError as e:
            logger.error(f"创建默认应用数据目录 '{_app_data_dir}' 时发生权限错误: {e}。将回退到内存数据库。")
            DATABASE_PATH = ":memory:"
        except Exception as e:
            logger.error(f"创建默认应用数据目录时发生未知错误: {e}。将回退到内存数据库。")
            DATABASE_PATH = ":memory:"

if DATABASE_PATH == ":memory:":
    DATABASE_URL = "sqlite+aiosqlite:///:memory:" # 内存数据库的 URL
else:
    DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_PATH}" # 文件数据库的 URL

logger.info(f"最终数据库路径: {DATABASE_PATH}")
logger.info(f"最终数据库 URL: {DATABASE_URL}")
DEFAULT_CONTEXT_TTL_DAYS = 30 # 定义默认的上下文生存时间 (天数)
IS_MEMORY_DB = DATABASE_PATH == ':memory:' # 判断是否使用内存数据库的布尔常量

# --- 数据库连接管理 ---
@asynccontextmanager # 使用异步上下文管理器装饰器
async def get_db_connection() -> AsyncGenerator[aiosqlite.Connection, None]:
    """
    (可能已废弃/特定用途) 获取一个原生的 aiosqlite 数据库连接。
    使用 asynccontextmanager 确保连接在使用后能被正确关闭。
    注意：项目主要应使用 SQLAlchemy 的 AsyncSession。
    """
    conn = None # 初始化连接变量
    try:
        # 连接到数据库文件
        conn = await aiosqlite.connect(DATABASE_PATH) # 建立异步连接
        logger.info("数据库连接已获取 (类型: aiosqlite.Connection)。") # 记录日志
        yield conn # 返回连接对象供上下文使用
    except Exception as e:
        # 记录连接失败的错误
        logger.error(f"获取 aiosqlite 数据库连接失败: {e}", exc_info=True)
        raise # 重新抛出异常
    finally:
        # 无论是否发生异常，只要连接成功建立，就关闭连接
        if conn is not None:
            await conn.close() # 关闭连接
            logger.debug("aiosqlite 数据库连接已关闭。") # 记录关闭日志

# --- 数据库初始化 ---
async def initialize_db_tables() -> None:
    """
    初始化数据库表。如果表已存在，则不会重复创建。
    此函数应在应用启动时调用。
    """
    try:
        # 调用内部的初始化函数
        await _initialize_db_tables()
    except Exception as e:
        # 记录初始化失败的错误
        logger.error(f"初始化数据库表失败: {e}", exc_info=True)
        raise # 重新抛出异常，以便应用启动时能感知到问题

async def _initialize_db_tables() -> None:
    """
    内部函数：使用 SQLAlchemy 的异步引擎和 Base.metadata 来创建所有定义的表。
    """
    # 创建 SQLAlchemy 异步引擎实例
    # echo=False 关闭 SQL 语句的日志输出，生产环境应保持关闭
    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        # 使用引擎的 begin() 方法创建一个异步事务块
        async with engine.begin() as conn:
            # 在异步事务中同步运行 Base.metadata.create_all
            # 这会检查数据库中是否存在 Base 中定义的所有表，如果不存在则创建
            await conn.run_sync(Base.metadata.create_all)
        # 记录初始化成功的日志
        logger.info("所有通过 SQLAlchemy Base 定义的数据库表已成功初始化/验证。")
    except Exception as e:
        # 记录使用 SQLAlchemy 初始化失败的错误
        logger.error(f"使用 SQLAlchemy 初始化数据库表失败: {e}", exc_info=True)
        raise # 重新抛出异常
    finally:
        # 无论成功或失败，最后都关闭引擎及其连接池
        await engine.dispose()
        logger.debug("SQLAlchemy 异步引擎已关闭。") # 记录引擎关闭日志


# --- ApiKey CRUD (创建、读取、更新、删除) 操作 ---

async def add_api_key(
    db: AsyncSession, # 异步数据库会话
    key_string: str, # 要添加的 Key 字符串
    description: Optional[str] = None, # Key 的描述 (可选)
    expires_at: Optional[datetime] = None, # Key 的过期时间 (可选, 应为 UTC datetime)
    is_active: bool = True, # Key 是否激活 (默认 True)
    enable_context_completion: bool = True, # 是否启用上下文补全 (默认 True)
    user_id: Optional[str] = None # 关联的用户 ID (可选)
) -> Optional[ApiKey]:
    """
    向数据库异步添加一个新的 API Key 记录。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。
        key_string (str): 要添加的 API Key 字符串。
        description (Optional[str]): Key 的描述信息。
        expires_at (Optional[datetime]): Key 的过期时间 (UTC)。如果提供，请确保是 aware datetime。
        is_active (bool): Key 是否激活。
        enable_context_completion (bool): 此 Key 是否启用上下文补全。
        user_id (Optional[str]): 与此 Key 关联的用户 ID。

    Returns:
        Optional[ApiKey]: 如果成功创建，返回包含数据库生成信息的 ApiKey 对象；
                          如果 Key 已存在或发生其他错误，则返回 None。
    """
    try:
        # 1. 检查 Key 是否已存在，避免重复添加
        stmt_check = select(ApiKey).where(ApiKey.key_string == key_string) # 构建查询语句
        result_check = await db.execute(stmt_check) # 执行查询
        existing_key = result_check.scalar_one_or_none() # 获取单个结果，不存在则为 None
        if existing_key: # 如果 Key 已存在
            logger.warning(f"尝试添加已存在的 API Key: {key_string[:8]}...") # 记录警告
            return None # 返回 None 表示未添加

        # 2. 创建新的 ApiKey ORM 对象
        new_api_key = ApiKey(
            key_string=key_string, # 设置 Key 字符串
            description=description, # 设置描述
            # 如果提供了 expires_at，确保它是 UTC 时间；否则为 None
            expires_at=expires_at.replace(tzinfo=timezone.utc) if expires_at else None,
            is_active=is_active, # 设置激活状态
            enable_context_completion=enable_context_completion, # 设置上下文补全状态
            user_id=user_id # 设置关联用户 ID
            # created_at 字段由数据库自动设置 (server_default=func.now())
        )
        # 3. 将新对象添加到会话中
        db.add(new_api_key)
        # 4. 提交事务以保存到数据库
        await db.commit()
        # 5. 刷新对象以获取数据库生成的 ID 和默认值 (如 created_at)
        await db.refresh(new_api_key)
        # 记录成功添加的日志
        logger.info(f"成功添加 API Key: {new_api_key.key_string[:8]}... (ID: {new_api_key.id})")
        return new_api_key # 返回创建的对象
    except sqlalchemy.exc.IntegrityError as e: # 捕获唯一约束冲突错误 (通常是 key_string 重复)
        await db.rollback() # 回滚事务
        logger.error(f"添加 API Key 时发生唯一约束冲突 (Key 可能已存在): {key_string[:8]}... - {e}", exc_info=False) # 记录错误 (不包含堆栈)
        return None # 返回 None
    except Exception as e: # 捕获其他可能的数据库异常
        await db.rollback() # 回滚事务
        logger.error(f"添加 API Key {key_string[:8]}... 失败: {e}", exc_info=True) # 记录详细错误日志
        return None # 返回 None

async def get_all_api_keys_from_db(db: AsyncSession) -> List[ApiKey]:
    """
    从数据库异步获取所有 API 密钥对象。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。

    Returns:
        List[ApiKey]: 包含所有 ApiKey 对象的列表，按创建时间排序。如果出错则返回空列表。
    """
    try:
        # 构建查询语句，选择所有 ApiKey 记录，并按创建时间降序排序
        stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
        # 执行查询
        result = await db.execute(stmt)
        # 获取所有结果并将标量（ApiKey 对象）转换为列表
        api_keys = result.scalars().all()
        # 记录成功获取的 Key 数量
        logger.info(f"成功从数据库获取 {len(api_keys)} 个 API Key。")
        return list(api_keys) # 确保返回的是列表类型
    except Exception as e: # 捕获可能的数据库异常
        # 记录获取失败的错误日志
        logger.error(f"从数据库获取所有 API Key 失败: {e}", exc_info=True)
        return [] # 出错时返回空列表

async def get_api_key_by_string(db: AsyncSession, key_string: str) -> Optional[ApiKey]:
    """
    根据 Key 字符串从数据库异步获取单个 API Key 对象。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。
        key_string (str): 要查询的 API Key 字符串。

    Returns:
        Optional[ApiKey]: 如果找到匹配的 Key，则返回 ApiKey 对象；否则返回 None。
    """
    if not key_string: return None # 如果 key_string 为空，直接返回 None
    try:
        # 构建查询语句，根据 key_string 查找 ApiKey
        stmt = select(ApiKey).where(ApiKey.key_string == key_string)
        # 执行查询
        result = await db.execute(stmt)
        # 获取单个结果，如果不存在则为 None
        api_key = result.scalar_one_or_none()
        if api_key: # 如果找到了 Key
            logger.debug(f"成功获取 API Key: {key_string[:8]}...") # 记录调试日志
        else: # 如果未找到 Key
            logger.debug(f"未找到 API Key: {key_string[:8]}...") # 记录调试日志
        return api_key # 返回找到的对象或 None
    except Exception as e: # 捕获可能的数据库异常
        # 记录获取失败的错误日志
        logger.error(f"获取 API Key {key_string[:8]}... 失败: {e}", exc_info=True)
        return None # 出错时返回 None

async def update_api_key(db: AsyncSession, key_string: str, updates: Dict[str, Any]) -> Optional[ApiKey]:
    """
    异步更新数据库中指定 API Key 的信息。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。
        key_string (str): 要更新的 API Key 字符串。
        updates (Dict[str, Any]): 一个字典，包含要更新的字段名和对应的新值。
                                  例如: {'description': '新描述', 'is_active': False}。

    Returns:
        Optional[ApiKey]: 如果成功更新，返回更新后的 ApiKey 对象；
                          如果 Key 不存在或发生错误，则返回 None。
    """
    if not key_string or not updates: return None # 如果 key_string 或 updates 为空，直接返回 None
    try:
        # 1. 先查询要更新的 Key 是否存在
        stmt_select = select(ApiKey).where(ApiKey.key_string == key_string)
        result_select = await db.execute(stmt_select)
        api_key_to_update = result_select.scalar_one_or_none() # 获取要更新的对象

        if not api_key_to_update: # 如果 Key 不存在
            logger.warning(f"尝试更新不存在的 API Key: {key_string[:8]}...") # 记录警告
            return None # 返回 None

        # 2. 过滤掉不允许直接更新的字段 (如 id, key_string, created_at)
        # 确保只更新模型中存在的、且允许修改的字段
        allowed_updates = {
            k: v for k, v in updates.items()
            if hasattr(ApiKey, k) and k not in ['id', 'key_string', 'created_at']
        }

        # 3. 特殊处理 expires_at 字段，确保存入数据库的是 UTC 时间
        if 'expires_at' in allowed_updates:
            expiry_value = allowed_updates['expires_at']
            if isinstance(expiry_value, datetime): # 如果是 datetime 对象
                # 确保它是 aware datetime (带时区信息)，并转换为 UTC
                if expiry_value.tzinfo is None:
                    logger.warning(f"更新 Key {key_string[:8]}... 的 expires_at 时提供了 naive datetime，假设为本地时间并转换为 UTC。建议提供 aware datetime。")
                    # 假设本地时区，转换为 UTC (这里可能需要更健壮的时区处理)
                    # 或者直接要求调用者提供 aware datetime
                    allowed_updates['expires_at'] = expiry_value.astimezone(timezone.utc)
                else:
                    allowed_updates['expires_at'] = expiry_value.astimezone(timezone.utc)
            elif expiry_value is None: # 允许将过期时间设置为 None (永不过期)
                pass # 保留 None 值
            else: # 如果提供的 expires_at 不是 datetime 或 None
                 logger.warning(f"更新 Key {key_string[:8]}... 时提供的 expires_at ('{expiry_value}') 不是有效的 datetime 对象或 None，已忽略此字段。") # 记录警告
                 del allowed_updates['expires_at'] # 从更新字典中移除无效的 expires_at

        # 4. 检查是否还有有效的更新字段
        if not allowed_updates:
            logger.warning(f"没有有效的字段需要为 Key {key_string[:8]}... 更新。") # 记录警告
            return api_key_to_update # 返回未修改的对象

        # 5. 执行更新操作
        stmt_update = (
            update(ApiKey) # 构建 UPDATE 语句
            .where(ApiKey.key_string == key_string) # 指定更新条件
            .values(**allowed_updates) # 设置要更新的值
            .execution_options(synchronize_session="fetch") # 选项：在执行后同步会话状态
        )
        await db.execute(stmt_update) # 执行更新语句
        await db.commit() # 提交事务
        await db.refresh(api_key_to_update) # 刷新对象以获取数据库中更新后的值
        logger.info(f"成功更新 API Key: {key_string[:8]}... 更新内容: {allowed_updates}") # 记录成功更新日志
        return api_key_to_update # 返回更新后的对象
    except Exception as e: # 捕获可能的数据库异常
        await db.rollback() # 回滚事务
        logger.error(f"更新 API Key {key_string[:8]}... 失败: {e}", exc_info=True) # 记录错误日志
        return None # 返回 None

async def delete_api_key(db: AsyncSession, key_string: str) -> bool:
    """
    从数据库异步删除指定的 API Key。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。
        key_string (str): 要删除的 API Key 字符串。

    Returns:
        bool: 如果成功删除 Key (或 Key 原本就不存在)，返回 True；如果发生错误，返回 False。
              注意：即使 Key 不存在，rowcount 也可能为 0，但操作本身没有错误。
              可以根据需求调整返回值逻辑，例如严格要求 rowcount > 0 才返回 True。
    """
    if not key_string: return False # 如果 key_string 为空，返回 False
    try:
        # 构建 DELETE 语句
        stmt = delete(ApiKey).where(ApiKey.key_string == key_string)
        # 执行删除语句
        result = await db.execute(stmt)
        # 提交事务
        await db.commit()
        # 检查受影响的行数
        if result.rowcount > 0: # 如果删除了至少一行
            logger.info(f"成功删除 API Key: {key_string[:8]}...") # 记录成功日志
            return True
        else: # 如果没有删除任何行 (Key 可能原本就不存在)
            logger.warning(f"尝试删除 API Key: {key_string[:8]}... 时未找到匹配项。") # 记录警告
            return True # 也可以认为操作成功完成（目标状态已达成）
    except Exception as e: # 捕获可能的数据库异常
        await db.rollback() # 回滚事务
        logger.error(f"删除 API Key {key_string[:8]}... 失败: {e}", exc_info=True) # 记录错误日志
        return False # 返回 False 表示删除失败

# --- 其他数据库函数 (部分可能需要审查或完善) ---

async def is_valid_proxy_key(db: AsyncSession, key: str) -> bool:
    """
    异步检查提供的代理 Key (字符串) 是否在数据库中存在且处于活动状态。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。
        key (str): 要检查的代理 Key 字符串。

    Returns:
        bool: 如果 Key 有效且激活，返回 True；否则返回 False。
    """
    # 调用 get_api_key_by_string 获取 Key 对象
    api_key_obj = await get_api_key_by_string(db, key)
    # 检查对象是否存在，并且其 is_active 属性为 True
    is_valid = bool(api_key_obj and api_key_obj.is_active)
    # 记录调试日志
    logger.debug(f"检查 Key '{key[:8]}...' 有效性: {is_valid}")
    return is_valid # 返回检查结果


async def get_key_id_by_cached_content_id(db: AsyncSession, cached_content_id: str) -> Optional[int]:
    """
    (需要实现) 根据缓存内容 ID 获取关联的 Key ID。
    目前是模拟实现。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。
        cached_content_id (str): 缓存内容的唯一 ID。

    Returns:
        Optional[int]: 关联的 Key ID，如果找不到或出错则返回 None。
    """
    # logger.warning("get_key_id_by_cached_content_id 函数尚未完全实现，返回模拟数据。") # 移除警告
    from gap.core.database.models import CachedContent # 导入模型
    try:
        # 假设 cached_content_id 是 CachedContent.content_id (通常是哈希或 Gemini cache name)
        # 或者，如果它可能是整数 CachedContent.id，则需要类型检查
        if isinstance(cached_content_id, int): # 如果传入的是整数 ID
            stmt = select(CachedContent.key_id).where(CachedContent.id == cached_content_id)
        else: # 否则按 content_id (字符串) 查询
            stmt = select(CachedContent.key_id).where(CachedContent.content_id == cached_content_id)
        
        result = await db.execute(stmt)
        key_id = result.scalar_one_or_none()
        if key_id is not None:
            logger.info(f"成功从缓存标识符 '{cached_content_id}' 获取到 key_id: {key_id}")
        else:
            logger.info(f"未从缓存标识符 '{cached_content_id}' 找到关联的 key_id。")
        return key_id
    except Exception as e:
        logger.error(f"根据缓存内容标识符 '{cached_content_id}' 获取 Key ID 失败: {e}", exc_info=True)
        return None

async def get_key_string_by_id(db: AsyncSession, key_id: int) -> Optional[str]:
    """
    根据 Key ID 获取 Key 字符串。
    """
    # logger.warning("get_key_string_by_id 函数尚未完全实现，返回模拟数据。") # 移除警告
    from gap.core.database.models import ApiKey # 导入模型
    try:
        stmt = select(ApiKey.key_string).where(ApiKey.id == key_id)
        result = await db.execute(stmt)
        key_string = result.scalar_one_or_none()
        if key_string:
            logger.info(f"成功为 Key ID {key_id} 获取到 Key 字符串: {key_string[:8]}...")
        else:
            logger.info(f"未为 Key ID {key_id} 找到对应的 Key 字符串。")
        return key_string
    except Exception as e:
        logger.error(f"根据 Key ID {key_id} 获取 Key 字符串失败: {e}", exc_info=True)
        return None

async def get_user_last_used_key_id(db: AsyncSession, user_id: str) -> Optional[int]:
    """
    获取指定用户上次成功使用的 Key ID (用于粘性会话)。
    """
    # logger.warning("get_user_last_used_key_id 函数尚未完全实现，返回模拟数据。") # 移除警告
    from gap.core.database.models import UserKeyAssociation # 导入模型
    try:
        stmt = select(UserKeyAssociation.key_id)\
               .where(UserKeyAssociation.user_id == user_id)\
               .order_by(UserKeyAssociation.last_used_timestamp.desc())\
               .limit(1)
        result = await db.execute(stmt)
        key_id = result.scalar_one_or_none()
        if key_id is not None:
            logger.info(f"用户 '{user_id}' 上次使用的 Key ID: {key_id}")
        else:
            logger.info(f"未找到用户 '{user_id}' 上次使用的 Key ID。")
        return key_id
    except Exception as e:
        logger.error(f"获取用户 '{user_id}' 上次成功使用的 Key ID 失败: {e}", exc_info=True)
        return None

async def get_key_scores(model_name: str) -> Dict[str, float]:
    """
    (需要实现/可能已废弃) 获取指定模型的 Key 分数。
    目前从内存缓存 key_scores_cache 获取 (如果存在)。

    Args:
        model_name (str): 模型名称。

    Returns:
        Dict[str, float]: 包含 Key 字符串和对应分数的字典。
    """
    logger.debug("get_key_scores 函数可能依赖于内存缓存或未完全实现的数据库逻辑。") # 记录警告改为 debug
    try:
        # TODO: 实现从 KeyScore 表获取分数的逻辑，或者确认是否依赖内存缓存
        # 暂时从内存缓存获取
        with cache_lock: # 使用锁保护缓存访问
            scores = key_scores_cache.get(model_name, {}) # 获取模型对应的分数，默认为空字典
            return scores.copy() # 返回缓存的副本
    except Exception as e:
        logger.error(f"获取模型 '{model_name}' 的 Key 分数失败: {e}", exc_info=True) # 记录错误
        return {} # 出错时返回空字典

async def update_setting(db: AsyncSession, key: str, value: str):
    """
    (重复/可能已废弃) 更新或插入设置项。
    此函数与 set_setting 功能重复，且使用了原生 SQL。建议统一使用 set_setting。

    Args:
        db (AsyncSession): SQLAlchemy 异步数据库会话。
        key (str): 设置项的键。
        value (str): 设置项的值。
    """
    logger.warning("调用了可能重复或已废弃的 update_setting 函数，建议使用 set_setting。") # 记录警告
    try:
        # 使用 SQLAlchemy 的 text() 构造原生 SQL 更新语句 (不推荐，优先使用 ORM 或 Core API)
        # 注意：直接使用 text() 可能存在 SQL 注入风险，如果 key 或 value 来自外部输入。
        # 在这个特定场景下，key 和 value 通常是内部定义的，风险较低，但仍不推荐。
        # 推荐使用 SQLAlchemy 的 update() 构造器，如 update_api_key 函数所示。
        stmt = text("UPDATE settings SET value = :value WHERE key = :key") # 构造 SQL 语句
        parameters = {"key": key, "value": value} # 创建参数字典
        result = await db.execute(stmt, parameters) # 执行 SQL 语句
        if result.rowcount == 0: # 如果没有行被更新 (说明 key 不存在)
            # 如果 key 不存在，则插入新行 (同样使用原生 SQL)
            stmt_insert = text("INSERT INTO settings (key, value) VALUES (:key, :value)")
            await db.execute(stmt_insert, parameters)
            logger.info(f"设置 '{key}' 不存在，已插入新值 '{value}'") # 记录插入日志
        else:
            logger.info(f"设置 '{key}' 已更新为 '{value}' (通过 update_setting)") # 记录更新日志
        await db.commit() # 提交事务
    except Exception as e:
        logger.error(f"使用 update_setting 更新设置 '{key}' 时发生错误: {e}", exc_info=True) # 记录错误日志
        await db.rollback() # 回滚事务
