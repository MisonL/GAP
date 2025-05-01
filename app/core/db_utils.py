# -*- coding: utf-8 -*-
"""
数据库相关的工具函数和常量，用于避免循环导入。
包括数据库连接获取和表初始化函数。
"""
import aiosqlite # 导入 aiosqlite 模块
import logging # 导入 logging 模块
import os # 导入 os 模块
import tempfile # 导入 tempfile 模块
import asyncio # 导入 asyncio
from contextlib import asynccontextmanager # 改为异步上下文管理器
from typing import Optional, AsyncGenerator, Any # 为类型提示添加
from datetime import datetime, timezone # 新增：用于有效期检查

# 导入配置以获取默认值
from app import config as app_config # 导入 app_config 模块

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 数据库路径配置 ---
_db_path_env = os.environ.get('CONTEXT_DB_PATH') # 从环境变量获取数据库路径
DATABASE_PATH: str # 数据库文件路径
IS_MEMORY_DB: bool # 是否为内存数据库的标志

if _db_path_env: # 如果设置了数据库路径环境变量
    # 尝试使用基于文件的数据库
    temp_db_path = _db_path_env # 临时存储路径
    temp_is_memory = False # 临时标记为非内存数据库
    try:
        db_dir = os.path.dirname(temp_db_path) # 获取数据库文件所在目录
        if db_dir: # 如果指定了目录
             os.makedirs(db_dir, exist_ok=True) # 创建目录（如果不存在）
             # 测试写入权限
             perm_test_file = os.path.join(db_dir, ".perm_test") # 创建一个临时测试文件路径
             with open(perm_test_file, "w") as f: # 尝试写入文件
                 f.write("test")
             os.remove(perm_test_file) # 删除测试文件
        # 权限似乎正常，最终确定设置
        DATABASE_PATH = temp_db_path # 设置最终数据库路径
        IS_MEMORY_DB = temp_is_memory # 设置最终内存模式标志
        logger.info(f"上下文存储：使用文件数据库 -> {DATABASE_PATH}") # 使用文件数据库
    except OSError as e:
        logger.error(f"无法创建或写入数据库目录 {os.path.dirname(temp_db_path)}: {e}。将回退到内存数据库。") # 无法创建或写入数据库目录，回退到内存数据库
        DATABASE_PATH = "file::memory:?cache=shared" # 回退到共享内存数据库
        IS_MEMORY_DB = True # 设置为内存数据库
        logger.info("上下文存储：回退到共享内存数据库 (file::memory:?cache=shared)") # 回退到共享内存数据库
    except Exception as e:
         logger.error(f"检查数据库路径时发生错误 ({temp_db_path}): {e}。将回退到内存数据库。") # 检查数据库路径时发生错误，回退到内存数据库
         DATABASE_PATH = "file::memory:?cache=shared" # 回退到共享内存数据库
         IS_MEMORY_DB = True # 设置为内存数据库
         logger.info("上下文存储：回退到共享内存数据库 (file::memory:?cache=shared)") # 回退到共享内存数据库
else:
    # 默认使用共享内存数据库
    DATABASE_PATH = "file::memory:?cache=shared" # SQLite 共享内存数据库 URI
    IS_MEMORY_DB = True # 设置为内存数据库
    logger.info("上下文存储：使用共享内存数据库 (file::memory:?cache=shared)") # 使用共享内存数据库

DEFAULT_CONTEXT_TTL_DAYS = getattr(app_config, 'DEFAULT_CONTEXT_TTL_DAYS', 7) # 从配置获取默认 TTL 天数

# --- 内存模式下的共享连接 ---
_shared_memory_conn: Optional[aiosqlite.Connection] = None # 用于缓存共享内存连接
db_lock = asyncio.Lock() # 为共享内存数据库访问创建一个锁

# --- 内部表创建逻辑 ---
async def _create_tables_if_not_exist(conn: aiosqlite.Connection): # 改为异步函数，接受 aiosqlite 连接
    """如果表不存在，则创建数据库表。"""
    try:
        async with conn.cursor() as cursor:
            # 创建 proxy_keys 表
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS proxy_keys (
                    key TEXT PRIMARY KEY,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    expires_at DATETIME NULL, -- Key 的过期时间，NULL 表示永不过期
                    enable_context_completion BOOLEAN DEFAULT TRUE -- 是否启用上下文补全
                );
                """
            )

            try:
                # 检查 'enable_context_completion' 列是否存在，不获取数据
                await cursor.execute("SELECT enable_context_completion FROM proxy_keys LIMIT 0")
            except aiosqlite.OperationalError: # 捕获 aiosqlite 的错误
                logger.info("正在向 proxy_keys 表添加 'enable_context_completion' 列...")
                await cursor.execute("ALTER TABLE proxy_keys ADD COLUMN enable_context_completion BOOLEAN DEFAULT TRUE") # 使用 await
                await conn.commit() # 使用 await 提交 ALTER TABLE
                logger.info("'enable_context_completion' 列已添加。")

            # 创建 contexts 表
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS contexts (
                    proxy_key TEXT PRIMARY KEY,
                    contents TEXT NOT NULL,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(proxy_key) REFERENCES proxy_keys(key) ON DELETE CASCADE
                );
                """
            )
            # 创建 settings 表
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            # 创建索引
            await cursor.execute("CREATE INDEX IF NOT EXISTS idx_context_last_used ON contexts(last_used)") # 使用 await
            # 插入默认设置
            await cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                           ('context_ttl_days', str(DEFAULT_CONTEXT_TTL_DAYS))) # 使用 await


            await conn.commit() # 提交事务
    except aiosqlite.Error as e: # 捕获 aiosqlite 的错误
        logger.error(f"在连接 {id(conn)} 上创建表时出错: {e}", exc_info=True) # 在连接上创建表时出错
        # 让调用者处理错误传播

# --- Database Connection ---
@asynccontextmanager
async def get_db_connection() -> AsyncGenerator[aiosqlite.Connection, None]:
    """异步获取数据库连接。"""
    global _shared_memory_conn
    conn = None # 初始化连接为 None
    lock_acquired = False # 跟踪锁是否已被获取
    is_shared_conn = False # 标记以防止关闭共享连接

    try:
        if IS_MEMORY_DB: # 如果是内存数据库模式
            if _shared_memory_conn is None: # 如果共享连接尚未创建
                logger.info("内存数据库模式：创建共享连接...") # 内存数据库模式：创建共享连接
                # 对于共享内存连接使用 check_same_thread=False，因为它可能被不同的线程/请求访问
                _shared_memory_conn = await aiosqlite.connect(DATABASE_PATH, timeout=10, uri=True) # 使用 aiosqlite.connect
                _shared_memory_conn.row_factory = aiosqlite.Row # 设置 aiosqlite 行工厂
                await _shared_memory_conn.execute("PRAGMA foreign_keys = ON;") # 使用 await
                logger.info(f"内存数据库模式：在共享连接 {id(_shared_memory_conn)} 上创建表...") # 内存数据库模式：在共享连接上创建表
                await _create_tables_if_not_exist(_shared_memory_conn) # 仅在创建共享连接时创建一次表，使用 await
                logger.info(f"内存数据库模式：共享连接 {id(_shared_memory_conn)} 已初始化。") # 内存数据库模式：共享连接已初始化
            # logger.debug(f"内存数据库模式：返回共享连接 {id(_shared_memory_conn)}")
            await db_lock.acquire() # 在 yield 连接之前获取锁
            lock_acquired = True # 标记锁已获取
            conn = _shared_memory_conn # 将连接设置为共享连接
            is_shared_conn = True # 标记为共享连接
            yield conn # 在持有锁的情况下 yield 连接
        else:
            # 基于文件的数据库：为每个请求创建一个新连接
            # logger.debug(f"文件数据库模式：创建新连接 ({DATABASE_PATH})...")
            conn = await aiosqlite.connect(DATABASE_PATH, timeout=10) # 使用 aiosqlite.connect
            conn.row_factory = aiosqlite.Row # 设置 aiosqlite 行工厂
            await conn.execute("PRAGMA foreign_keys = ON;") # 使用 await
            # logger.debug(f"文件数据库连接 {id(conn)} 已准备好。")
            yield conn # Yield 新连接

    except aiosqlite.Error as e: # 捕获 aiosqlite 错误
        logger.error(f"数据库连接或设置错误 ({DATABASE_PATH}): {e}", exc_info=True) # 数据库连接或设置错误
        raise # 重新抛出异常以通知调用者
    finally:
        # 释放锁（如果已获取）
        if lock_acquired:
            db_lock.release() # 释放锁
        if conn and not is_shared_conn: # 仅当不是共享内存连接时才关闭
            # logger.debug(f"关闭文件数据库连接 {id(conn)}。")
            await conn.close() # 使用 await 关闭连接
        # else:
            # logger.debug(f"保持共享内存连接 {id(conn)} 打开。")


# --- 公共数据库初始化函数 ---
async def initialize_db_tables():
    """显式初始化数据库表。"""
    logger.info(f"开始显式数据库表初始化 ({DATABASE_PATH})...")
    try:
        async with get_db_connection() as conn:
             # 对于内存数据库，这将创建/检索共享连接并确保表存在。
             # 对于文件数据库，这将在首次连接时创建文件/表（如果它们不存在）。
             logger.info(f"数据库连接已获取 (类型: {'内存共享' if IS_MEMORY_DB else '文件'}, ID: {id(conn)})，初始化检查完成。") # 数据库连接已获取，初始化检查完成
             pass # 连接已获取，get_db_connection 内部的初始化逻辑已处理
        logger.info(f"显式数据库表初始化完成 ({DATABASE_PATH})。") # 显式数据库表初始化完成
    except aiosqlite.Error as e: # 捕获 aiosqlite 错误
        logger.error(f"显式数据库表初始化失败 ({DATABASE_PATH}): {e}", exc_info=True) # 显式数据库表初始化失败
        raise RuntimeError(f"无法初始化数据库表: {e}") # 启动时重新抛出严重错误
    except Exception as e: # 捕获连接期间其他可能的异常
        logger.error(f"显式数据库表初始化期间发生意外错误: {e}", exc_info=True) # 显式数据库表初始化期间发生意外错误
        raise RuntimeError(f"无法初始化数据库表: {e}") # 启动时重新抛出严重错误

# --- Proxy Key Management Functions ---

async def get_all_proxy_keys() -> list[aiosqlite.Row]: # 返回 aiosqlite.Row 列表
    """获取所有 proxy keys。"""
    logger.debug("获取所有 proxy keys...")
    try:
        async with get_db_connection() as conn:
            async with conn.cursor() as cursor: # 使用异步游标
                await cursor.execute("SELECT key, description, created_at, is_active, expires_at, enable_context_completion FROM proxy_keys ORDER BY created_at DESC") # 使用 await
                keys = await cursor.fetchall() # 使用 await
                logger.debug(f"成功获取 {len(keys)} 个 proxy keys。")
                return keys
    except aiosqlite.Error as e: # 捕获 aiosqlite 错误
        logger.error(f"获取所有 proxy keys 时出错: {e}", exc_info=True)
        return []

async def get_proxy_key(key: str) -> Optional[aiosqlite.Row]: # 返回 aiosqlite.Row (Return aiosqlite.Row)
    """根据 Key 获取单个 proxy key 信息。"""
    if not key: return None
    try:
        async with get_db_connection() as conn: # 获取异步数据库连接
            async with conn.cursor() as cursor: # 使用异步游标
                await cursor.execute("SELECT key, description, created_at, is_active, expires_at, enable_context_completion FROM proxy_keys WHERE key = ?", (key,)) # 使用 await
                row = await cursor.fetchone() # 使用 await
                # if row:
                #     logger.debug(f"成功获取 proxy key: {key}。")
                # else:
                #     logger.debug(f"Proxy key 未找到: {key}。")
                return row # 返回行结果
    except aiosqlite.Error as e: # 捕获 aiosqlite 错误
        logger.error(f"获取 proxy key '{key}' 时出错: {e}", exc_info=True) # 获取单个 Key 错误
        return None # 出错时返回 None

# 注意：此函数现在需要是 async，因为它调用了 async 的 get_proxy_key
# Note: This function now needs to be async because it calls the async get_proxy_key
async def is_valid_proxy_key(key: str) -> bool:
    """检查 proxy key 是否有效（存在、活动且未过期）。"""
    key_info = await get_proxy_key(key)
    if not key_info or not key_info.get('is_active'):
        return False

    # 检查有效期
    expires_at_str = key_info.get('expires_at') # 获取过期时间字符串
    if expires_at_str: # 如果设置了过期时间
        try:
            # 假设存储的是 ISO 格式的 UTC 时间字符串
            # SQLite 可能返回不带时区的字符串，解析时需指定 UTC
            expires_at_dt = datetime.fromisoformat(expires_at_str).replace(tzinfo=timezone.utc) # 解析过期时间并设置为 UTC
            now_utc = datetime.now(timezone.utc) # 获取当前 UTC 时间
            if expires_at_dt < now_utc: # 如果已过期
                logger.info(f"Proxy key '{key[:8]}...' 已过期 (过期时间: {expires_at_str})。") # Proxy key 已过期
                return False # 返回 False
        except (ValueError, TypeError) as e:
            logger.error(f"无法解析 proxy key '{key[:8]}...' 的过期时间 '{expires_at_str}': {e}。视为无效。") # 无法解析 proxy key 的过期时间
            return False # 如果无法解析过期时间，视为无效

    # Key 存在、活动且未过期 (或无过期时间)
    # logger.debug(f"Key '{key[:8]}...' 验证通过。") # 减少日志 (Reduce logging)
    return True # 返回 True


async def add_proxy_key(key: str, description: str = "", expires_at: Optional[str] = None, enable_context_completion: bool = True) -> bool:
    """添加一个新的 proxy key。"""
    logger.info(f"尝试添加 proxy key: {key} (Expires: {expires_at}, EnableContext: {enable_context_completion})...")
    try:
        async with get_db_connection() as conn: # 获取异步数据库连接
            async with conn.cursor() as cursor: # 使用异步游标
                # 使用 INSERT OR IGNORE 避免因 Key 已存在而出错
                await cursor.execute( # 使用 await
                    "INSERT OR IGNORE INTO proxy_keys (key, description, is_active, expires_at, enable_context_completion) VALUES (?, ?, ?, ?, ?)",
                    (key, description, True, expires_at, enable_context_completion)
                )
                await conn.commit() # 使用 await
            key_exists_after = await get_proxy_key(key) # 已经是异步函数
            if key_exists_after:
                 logger.info(f"成功添加或已存在 proxy key: {key}。")
                 return True
            else:
                 logger.error(f"添加 proxy key '{key}' 后未能找到，可能提交失败。")
                 return False

    except aiosqlite.Error as e: # 捕获 aiosqlite 错误
        logger.error(f"添加 proxy key '{key}' 时出错: {e}", exc_info=True)
        return False

async def update_proxy_key(
    key: str,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
    expires_at: Optional[str] = None,
    enable_context_completion: Optional[bool] = None # Add enable_context_completion parameter
) -> bool:
    """
    更新一个现有的 proxy key 的信息。

        Args:
            key: 要更新的 Key。
            description: 新的描述 (可选)。
            is_active: 新的激活状态 (可选)。
            expires_at: 新的过期时间 (ISO 格式字符串)，None 表示清除过期时间 (可选)。
            enable_context_completion: 是否启用上下文补全 (可选)。
    """
    if description is None and is_active is None and expires_at is None and enable_context_completion is None:
        logger.warning(f"更新 proxy key '{key}' 失败：未提供要更新的字段。")
        return False

    logger.info(f"尝试更新 proxy key: {key} (Description: {description}, Active: {is_active}, Expires: {expires_at}, EnableContext: {enable_context_completion})...")
    updates = []
    params = []

    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(is_active)
    if expires_at is not None:
        # Handle empty string for expires_at to mean clear it
        updates.append("expires_at = ?")
        params.append(expires_at if expires_at else None)
    if enable_context_completion is not None:
        updates.append("enable_context_completion = ?")
        params.append(enable_context_completion)

    if not updates:
         logger.warning(f"更新 proxy key '{key}' 失败：逻辑错误，没有有效的更新字段。")
         return False

    params.append(key)

    sql = f"UPDATE proxy_keys SET {', '.join(updates)} WHERE key = ?"

    try:
        async with get_db_connection() as conn: # 获取异步数据库连接
            async with conn.cursor() as cursor: # 使用异步游标
                await cursor.execute(sql, tuple(params)) # 使用 await
                rowcount = cursor.rowcount # 获取 rowcount
                await conn.commit() # 使用 await
            if rowcount > 0:
                logger.info(f"成功更新 proxy key: {key}。")
                return True
            else:
                exists = await get_proxy_key(key) # 已经是异步函数
                if not exists:
                    logger.warning(f"更新 proxy key '{key}' 失败：Key 未找到。")
                else:
                    # If the key exists but rowcount is 0, it means the values didn't change
                    logger.info(f"更新 proxy key '{key}'：值未改变。")
                    # Consider returning True here if no change is not an error
                    return True # Or False depending on desired behavior
                return False
    except aiosqlite.Error as e: # 捕获 aiosqlite 错误
        logger.error(f"更新 proxy key '{key}' 时出错: {e}", exc_info=True)
        return False

async def delete_proxy_key(key: str) -> bool:
    """删除一个 proxy key 及其关联的上下文。"""
    logger.info(f"尝试删除 proxy key: {key}...")
    try:
        async with get_db_connection() as conn:
            async with conn.cursor() as cursor: # 使用异步游标
                await cursor.execute("DELETE FROM proxy_keys WHERE key = ?", (key,)) # 使用 await
                rowcount = cursor.rowcount # 获取 rowcount
                await conn.commit() # 使用 await
            if rowcount > 0: # 如果删除了记录
                logger.info(f"成功删除 proxy key: {key} (及其关联的上下文)。") # 成功删除 proxy key (及其关联的上下文)
                return True # 返回 True
            else:
                logger.warning(f"删除 proxy key '{key}' 失败：Key 未找到。") # 删除 proxy key 失败：Key 未找到
                return False # 返回 False
    except aiosqlite.Error as e: # 捕获 aiosqlite 错误
        logger.error(f"删除 proxy key '{key}' 时出错: {e}", exc_info=True) # 删除 proxy key 错误
        return False # 出错时返回 False
