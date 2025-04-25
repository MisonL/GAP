# -*- coding: utf-8 -*-
"""
数据库相关的工具函数和常量，用于避免循环导入。
包括数据库连接获取和表初始化函数。
Database-related utility functions and constants to avoid circular imports.
Includes database connection retrieval and table initialization functions.
"""
import sqlite3 # 导入 sqlite3 模块 (Import sqlite3 module)
import logging # 导入 logging 模块 (Import logging module)
import os # 导入 os 模块 (Import os module)
import tempfile # 导入 tempfile 模块 (Import tempfile module)
import asyncio # 导入 asyncio (Import asyncio)
from contextlib import asynccontextmanager # 改为异步上下文管理器 (Changed to asynchronous context manager)
from typing import Optional # 为类型提示添加 (Added for type hints)
from datetime import datetime, timezone # 新增：用于有效期检查 (New: Used for expiration check)

# 导入配置以获取默认值
# Import configuration to get default values
from .. import config as app_config # 导入 app_config 模块 (Import app_config module)

logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

# --- 数据库路径配置 ---
# --- Database Path Configuration ---
_db_path_env = os.environ.get('CONTEXT_DB_PATH') # 从环境变量获取数据库路径 (Get database path from environment variable)
DATABASE_PATH: str # 数据库文件路径 (Database file path)
IS_MEMORY_DB: bool # 是否为内存数据库的标志 (Flag indicating if it's an in-memory database)

if _db_path_env: # 如果设置了数据库路径环境变量 (If database path environment variable is set)
    # 尝试使用基于文件的数据库
    # Attempt to use a file-based database
    temp_db_path = _db_path_env # 临时存储路径 (Temporary storage path)
    temp_is_memory = False # 临时标记为非内存数据库 (Temporarily mark as not in-memory database)
    try:
        db_dir = os.path.dirname(temp_db_path) # 获取数据库文件所在目录 (Get the directory of the database file)
        if db_dir: # 如果指定了目录 (If a directory is specified)
             os.makedirs(db_dir, exist_ok=True) # 创建目录（如果不存在） (Create directory (if it doesn't exist))
             # 测试写入权限
             # Test write permissions
             perm_test_file = os.path.join(db_dir, ".perm_test") # 创建一个临时测试文件路径 (Create a temporary test file path)
             with open(perm_test_file, "w") as f: # 尝试写入文件 (Attempt to write to the file)
                 f.write("test")
             os.remove(perm_test_file) # 删除测试文件 (Delete the test file)
        # 权限似乎正常，最终确定设置
        # Permissions seem normal, finalize settings
        DATABASE_PATH = temp_db_path # 设置最终数据库路径 (Set final database path)
        IS_MEMORY_DB = temp_is_memory # 设置最终内存模式标志 (Set final memory mode flag)
        logger.info(f"上下文存储：使用文件数据库 -> {DATABASE_PATH}") # Log using file database
    except OSError as e:
        logger.error(f"无法创建或写入数据库目录 {os.path.dirname(temp_db_path)}: {e}。将回退到内存数据库。") # Log error and fallback to memory database
        DATABASE_PATH = "file::memory:?cache=shared" # 回退到共享内存数据库 (Fallback to shared memory database)
        IS_MEMORY_DB = True # 设置为内存数据库 (Set to in-memory database)
        logger.info("上下文存储：回退到共享内存数据库 (file::memory:?cache=shared)") # Log fallback
    except Exception as e:
         logger.error(f"检查数据库路径时发生错误 ({temp_db_path}): {e}。将回退到内存数据库。") # Log error during path check and fallback
         DATABASE_PATH = "file::memory:?cache=shared" # 回退到共享内存数据库 (Fallback to shared memory database)
         IS_MEMORY_DB = True # 设置为内存数据库 (Set to in-memory database)
         logger.info("上下文存储：回退到共享内存数据库 (file::memory:?cache=shared)") # Log fallback
else:
    # 默认使用共享内存数据库
    # Default to shared in-memory database
    DATABASE_PATH = "file::memory:?cache=shared" # SQLite 共享内存数据库 URI (SQLite shared in-memory database URI)
    IS_MEMORY_DB = True # 设置为内存数据库 (Set to in-memory database)
    logger.info("上下文存储：使用共享内存数据库 (file::memory:?cache=shared)") # Log using shared in-memory database

DEFAULT_CONTEXT_TTL_DAYS = getattr(app_config, 'DEFAULT_CONTEXT_TTL_DAYS', 7) # 从配置获取默认 TTL 天数 (Get default TTL days from config)

# --- 内存模式下的共享连接 ---
# --- Shared Connection in Memory Mode ---
_shared_memory_conn: Optional[sqlite3.Connection] = None # 用于缓存共享内存连接 (Used to cache the shared memory connection)
db_lock = asyncio.Lock() # 为共享内存数据库访问创建一个锁 (Create a lock for shared memory database access)

# --- 内部表创建逻辑 ---
# --- Internal Table Creation Logic ---
def _create_tables_if_not_exist(conn: sqlite3.Connection):
    """
    在给定的连接上创建所有必需的表（如果它们不存在）。
    Creates all necessary tables on the given connection if they do not exist.
    """
    try:
        cursor = conn.cursor() # 获取游标 (Get cursor)
        # logger.debug(f"在连接 {id(conn)} 上检查/创建表...")
        # 创建 proxy_keys 表
        # Create proxy_keys table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS proxy_keys (
                key TEXT PRIMARY KEY,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                expires_at DATETIME NULL, -- Key 的过期时间，NULL 表示永不过期
                enable_context_completion BOOLEAN DEFAULT TRUE -- 是否启用上下文补全
            )
        """)

        # 检查并添加 enable_context_completion 列（如果不存在）
        try:
            cursor.execute("SELECT enable_context_completion FROM proxy_keys LIMIT 0") # Use LIMIT 0 to check column existence without fetching data
        except sqlite3.OperationalError:
            logger.info("Adding 'enable_context_completion' column to proxy_keys table...")
            cursor.execute("ALTER TABLE proxy_keys ADD COLUMN enable_context_completion BOOLEAN DEFAULT TRUE")
            conn.commit() # Commit the ALTER TABLE
            logger.info("'enable_context_completion' column added.")

        # 创建 contexts 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contexts (
                proxy_key TEXT PRIMARY KEY,
                contents TEXT NOT NULL,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(proxy_key) REFERENCES proxy_keys(key) ON DELETE CASCADE
            )
        """)
        # 创建 settings 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # 为 last_used 添加索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_context_last_used ON contexts(last_used)")
        # 设置默认 TTL (使用 INSERT OR IGNORE 避免查询)
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                       ('context_ttl_days', str(DEFAULT_CONTEXT_TTL_DAYS)))

        # 不再需要在这里插入固定的 memory_mode_context key，
        # 因为 save_context 会处理实际使用的 key

        conn.commit() # 提交事务 (Commit transaction)
        # logger.info(f"在连接 {id(conn)} 上调用了 conn.commit() (表创建)。")
    except sqlite3.Error as e:
        logger.error(f"在连接 {id(conn)} 上创建表时出错: {e}", exc_info=True) # 记录创建表错误 (Log error during table creation)
        # 让调用者处理错误传播
        # Let the caller handle error propagation

# --- 数据库连接 ---
# --- Database Connection ---
@asynccontextmanager # 改为异步上下文管理器 (Changed to asynchronous context manager)
async def get_db_connection(): # 改为异步函数 (Changed to asynchronous function)
    """
    获取数据库连接的上下文管理器。
    在内存模式下，返回一个共享的、持久的连接。
    在文件模式下，返回一个新的连接，并在退出时关闭。
    Context manager for getting a database connection.
    In memory mode, returns a shared, persistent connection.
    In file mode, returns a new connection and closes it on exit.
    """
    global _shared_memory_conn # Declare intent to modify the global variable
    conn = None # 初始化连接为 None (Initialize connection to None)
    lock_acquired = False # 跟踪锁是否已被获取 (Track if the lock has been acquired)
    is_shared_conn = False # 标记以防止关闭共享连接 (Flag to prevent closing the shared connection)

    try:
        if IS_MEMORY_DB: # 如果是内存数据库模式 (If it's memory database mode)
            if _shared_memory_conn is None: # 如果共享连接尚未创建 (If the shared connection has not been created yet)
                logger.info("内存数据库模式：创建共享连接...") # Log creating shared connection
                # 对于共享内存连接使用 check_same_thread=False，因为它可能被不同的线程/请求访问
                # For shared memory connections, use check_same_thread=False because it might be accessed by different threads/requests
                _shared_memory_conn = sqlite3.connect(DATABASE_PATH, timeout=10, check_same_thread=False, uri=True) # 创建共享内存连接 (Create shared memory connection)
                _shared_memory_conn.row_factory = sqlite3.Row # 设置行工厂以字典形式访问列 (Set row factory to access columns as dictionaries)
                _shared_memory_conn.execute("PRAGMA foreign_keys = ON;") # 启用外键约束 (Enable foreign key constraints)
                logger.info(f"内存数据库模式：在共享连接 {id(_shared_memory_conn)} 上创建表...") # Log creating tables on shared connection
                _create_tables_if_not_exist(_shared_memory_conn) # 仅在创建共享连接时创建一次表 (Create tables only once when creating the shared connection)
                logger.info(f"内存数据库模式：共享连接 {id(_shared_memory_conn)} 已初始化。") # Log shared connection initialized
            # logger.debug(f"内存数据库模式：返回共享连接 {id(_shared_memory_conn)}")
            await db_lock.acquire() # 在 yield 连接之前获取锁 (Acquire the lock before yielding the connection)
            lock_acquired = True # 标记锁已获取 (Mark lock as acquired)
            conn = _shared_memory_conn # 将连接设置为共享连接 (Set connection to the shared connection)
            is_shared_conn = True # 标记为共享连接 (Mark as shared connection)
            yield conn # 在持有锁的情况下 yield 连接 (Yield the connection while holding the lock)
        else:
            # 基于文件的数据库：为每个请求创建一个新连接
            # File-based database: Create a new connection for each request
            # logger.debug(f"文件数据库模式：创建新连接 ({DATABASE_PATH})...")
            conn = sqlite3.connect(DATABASE_PATH, timeout=10, check_same_thread=True) # 文件数据库使用 check_same_thread=True 以确保安全 (File database uses check_same_thread=True for safety)
            conn.row_factory = sqlite3.Row # 设置行工厂 (Set row factory)
            conn.execute("PRAGMA foreign_keys = ON;") # 启用外键约束 (Enable foreign key constraints)
            # 文件数据库不需要在此处创建表，initialize_db_tables 会在启动时处理一次
            # File database does not need to create tables here, initialize_db_tables will handle it once at startup
            # logger.debug(f"文件数据库连接 {id(conn)} 已准备好。")
            yield conn # Yield 新连接 (Yield the new connection)

    except sqlite3.Error as e:
        logger.error(f"数据库连接或设置错误 ({DATABASE_PATH}): {e}", exc_info=True) # 记录数据库连接或设置错误 (Log database connection or setup error)
        raise # 重新抛出异常以通知调用者 (Re-raise the exception to notify the caller)
    finally:
        # 释放锁（如果已获取）
        # Release the lock (if acquired)
        if lock_acquired:
            db_lock.release() # 释放锁 (Release the lock)
        if conn and not is_shared_conn: # 仅当不是共享内存连接时才关闭 (Only close if it's not a shared memory connection)
            # logger.debug(f"关闭文件数据库连接 {id(conn)}。")
            conn.close() # 关闭连接 (Close the connection)
        # else:
            # logger.debug(f"保持共享内存连接 {id(conn)} 打开。")


# --- 公共数据库初始化函数 ---
# --- Public Database Initialization Function ---
# 注意：这个函数现在需要是 async 的，因为它调用了 async 的 get_db_connection
# Note: This function now needs to be async because it calls the async get_db_connection
async def initialize_db_tables():
    """
    显式初始化数据库表（如果不存在）。应在应用启动时调用一次。
    对于内存数据库，这将创建并缓存共享连接。
    对于文件数据库，这将确保文件和表已创建。
    Explicitly initializes database tables if they do not exist. Should be called once at application startup.
    For in-memory databases, this will create and cache the shared connection.
    For file-based databases, this will ensure the file and tables are created.
    """
    logger.info(f"开始显式数据库表初始化 ({DATABASE_PATH})...") # Log the start of explicit database table initialization
    try:
        # 只需通过异步上下文管理器获取连接即可处理初始化
        # Simply getting a connection through the asynchronous context manager handles initialization
        async with get_db_connection() as conn:
             # 对于内存数据库，这将创建/检索共享连接并确保表存在。
             # For in-memory databases, this will create/retrieve the shared connection and ensure tables exist.
             # 对于文件数据库，这将在首次连接时创建文件/表（如果它们不存在）。
             # For file-based databases, this will create the file/tables on the first connection if they do not exist.
             logger.info(f"数据库连接已获取 (类型: {'内存共享' if IS_MEMORY_DB else '文件'}, ID: {id(conn)})，初始化检查完成。") # Log that database connection is obtained and initialization check is complete
             pass # 连接已获取，get_db_connection 内部的初始化逻辑已处理 (Connection obtained, initialization logic inside get_db_connection is handled)
        logger.info(f"显式数据库表初始化完成 ({DATABASE_PATH})。") # Log that explicit database table initialization is complete
    except sqlite3.Error as e:
        logger.error(f"显式数据库表初始化失败 ({DATABASE_PATH}): {e}", exc_info=True) # Log failure of explicit database table initialization
        raise RuntimeError(f"无法初始化数据库表: {e}") # 启动时重新抛出严重错误 (Re-raise critical error at startup)
    except Exception as e: # 捕获连接期间其他可能的异常 (Catch other possible exceptions during connection)
        logger.error(f"显式数据库表初始化期间发生意外错误: {e}", exc_info=True) # Log unexpected error during initialization
        raise RuntimeError(f"无法初始化数据库表: {e}") # 启动时重新抛出严重错误 (Re-raise critical error at startup)

# --- Proxy Key Management Functions ---
# --- Proxy Key Management Functions ---
# 注意：所有使用 get_db_connection 的函数现在都需要是 async 的
# Note: All functions using get_db_connection now need to be async

async def get_all_proxy_keys() -> list[sqlite3.Row]:
    """
    获取所有代理 Key 及其信息。
    Gets all proxy keys and their information.
    """
    logger.debug("获取所有 proxy keys...") # Log getting all proxy keys (DEBUG level)
    try:
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            cursor = conn.cursor() # 获取游标 (Get cursor)
            # 在异步函数中执行数据库操作需要特殊处理，因为 sqlite3 本身不是异步的
            # Database operations in async functions require special handling as sqlite3 itself is not async
            # 推荐使用像 databases 或 aiosqlite 这样的库，但为了最小化更改，
            # It is recommended to use libraries like databases or aiosqlite, but to minimize changes,
            # 我们将使用 conn.execute 在默认的执行器中运行同步操作
            # we will use conn.execute to run synchronous operations in the default executor
            await asyncio.to_thread(cursor.execute, "SELECT key, description, created_at, is_active, expires_at, enable_context_completion FROM proxy_keys ORDER BY created_at DESC") # 添加 expires_at, enable_context_completion
            keys = await asyncio.to_thread(cursor.fetchall)
            logger.debug(f"成功获取 {len(keys)} 个 proxy keys。")
            return keys
    except sqlite3.Error as e:
        logger.error(f"获取所有 proxy keys 时出错: {e}", exc_info=True)
        return []

async def get_proxy_key(key: str) -> Optional[sqlite3.Row]:
    """
    获取单个代理 Key 的信息。
    Gets information for a single proxy key.
    """
    # logger.debug(f"获取 proxy key: {key}...") # 减少日志噪音 (Reduce log noise)
    if not key: return None # 增加空 key 检查 (Added empty key check)
    try:
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            cursor = conn.cursor() # 获取游标 (Get cursor)
            await asyncio.to_thread(cursor.execute, "SELECT key, description, created_at, is_active, expires_at, enable_context_completion FROM proxy_keys WHERE key = ?", (key,)) # 添加 expires_at, enable_context_completion
            row = await asyncio.to_thread(cursor.fetchone)
            # if row:
            #     logger.debug(f"成功获取 proxy key: {key}。")
            # else:
            #     logger.debug(f"Proxy key 未找到: {key}。")
            return row # 返回行结果 (Return the row result)
    except sqlite3.Error as e:
        logger.error(f"获取 proxy key '{key}' 时出错: {e}", exc_info=True) # 记录获取单个 Key 错误 (Log error getting single key)
        return None # 出错时返回 None (Return None on error)

# 注意：此函数现在需要是 async，因为它调用了 async 的 get_proxy_key
# Note: This function now needs to be async because it calls the async get_proxy_key
async def is_valid_proxy_key(key: str) -> bool:
    """
    检查代理 Key 是否有效、处于活动状态且未过期 (从数据库)。
    Checks if a proxy key is valid, active, and not expired (from the database).
    """
    key_info = await get_proxy_key(key) # 使用 await 调用 (Call with await)
    if not key_info or not key_info.get('is_active'): # 如果 Key 不存在或不活动 (If key does not exist or is not active)
        # logger.debug(f"Key '{key[:8]}...' 无效或不活动。") # 减少日志 (Reduce logging)
        return False # 返回 False (Return False)

    # 检查有效期
    # Check expiration
    expires_at_str = key_info.get('expires_at') # 获取过期时间字符串 (Get expiration time string)
    if expires_at_str: # 如果设置了过期时间 (If expiration time is set)
        try:
            # 假设存储的是 ISO 格式的 UTC 时间字符串
            # Assume the stored string is in ISO format UTC time
            # SQLite 可能返回不带时区的字符串，解析时需指定 UTC
            # SQLite might return a string without timezone, need to specify UTC when parsing
            expires_at_dt = datetime.fromisoformat(expires_at_str).replace(tzinfo=timezone.utc) # 解析过期时间并设置为 UTC (Parse expiration time and set to UTC)
            now_utc = datetime.now(timezone.utc) # 获取当前 UTC 时间 (Get current UTC time)
            if expires_at_dt < now_utc: # 如果已过期 (If expired)
                logger.info(f"Proxy key '{key[:8]}...' 已过期 (过期时间: {expires_at_str})。") # Log that the key has expired
                return False # 返回 False (Return False)
        except (ValueError, TypeError) as e:
            logger.error(f"无法解析 proxy key '{key[:8]}...' 的过期时间 '{expires_at_str}': {e}。视为无效。") # 记录解析过期时间错误 (Log error parsing expiration time)
            return False # 如果无法解析过期时间，视为无效 (If expiration time cannot be parsed, consider it invalid)

    # Key 存在、活动且未过期 (或无过期时间)
    # Key exists, is active, and not expired (or has no expiration time)
    # logger.debug(f"Key '{key[:8]}...' 验证通过。") # 减少日志 (Reduce logging)
    return True # 返回 True (Return True)


async def add_proxy_key(key: str, description: str = "", expires_at: Optional[str] = None, enable_context_completion: bool = True) -> bool:
    """
    添加一个新的代理 Key。
    如果 Key 已存在，则不执行任何操作并返回 False。

    Args:
        key: 要添加的 Key。
        description: Key 的描述。
        expires_at: Key 的过期时间 (ISO 格式字符串)，None 表示永不过期。
        enable_context_completion: 是否启用上下文补全。
    """
    logger.info(f"尝试添加 proxy key: {key} (Expires: {expires_at}, EnableContext: {enable_context_completion})...")
    try:
        async with get_db_connection() as conn:
            cursor = conn.cursor()
            # 使用 INSERT OR IGNORE 避免因 Key 已存在而出错
            await asyncio.to_thread(
                cursor.execute,
                "INSERT OR IGNORE INTO proxy_keys (key, description, is_active, expires_at, enable_context_completion) VALUES (?, ?, ?, ?, ?)",
                (key, description, True, expires_at, enable_context_completion)
            )
            await asyncio.to_thread(conn.commit)
            # 检查是否真的添加了
            key_exists_after = await get_proxy_key(key)
            if key_exists_after:
                 logger.info(f"成功添加或已存在 proxy key: {key}。")
                 return True
            else:
                 # 理论上不应发生，除非 commit 失败
                 logger.error(f"添加 proxy key '{key}' 后未能找到，可能提交失败。")
                 return False

    except sqlite3.Error as e:
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
    更新代理 Key 的描述、激活状态、过期时间或上下文补全状态。
    至少需要提供 description, is_active, expires_at 或 enable_context_completion 中的一个。

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
        async with get_db_connection() as conn:
            cursor = conn.cursor()
            await asyncio.to_thread(cursor.execute, sql, tuple(params))
            rowcount = cursor.rowcount
            await asyncio.to_thread(conn.commit)
            if rowcount > 0:
                logger.info(f"成功更新 proxy key: {key}。")
                return True
            else:
                # 检查 key 是否存在以提供更准确的信息
                exists = await get_proxy_key(key)
                if not exists:
                    logger.warning(f"更新 proxy key '{key}' 失败：Key 未找到。")
                else:
                    logger.warning(f"更新 proxy key '{key}' 失败：值未改变。")
                return False
    except sqlite3.Error as e:
        logger.error(f"更新 proxy key '{key}' 时出错: {e}", exc_info=True)
        return False

async def delete_proxy_key(key: str) -> bool:
    """
    删除一个代理 Key。
    由于设置了 FOREIGN KEY ... ON DELETE CASCADE，关联的上下文也会被删除。
    Deletes a proxy key.
    Associated context will also be deleted due to FOREIGN KEY ... ON DELETE CASCADE.
    """
    logger.info(f"尝试删除 proxy key: {key}...") # Log attempt to delete proxy key
    try:
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            cursor = conn.cursor() # 获取游标 (Get cursor)
            await asyncio.to_thread(cursor.execute, "DELETE FROM proxy_keys WHERE key = ?", (key,)) # 在线程中执行删除操作 (Execute delete operation in a thread)
            rowcount = cursor.rowcount # 获取同步操作的 rowcount (Get rowcount of the synchronous operation)
            await asyncio.to_thread(conn.commit) # 在线程中提交事务 (Commit transaction in a thread)
            if rowcount > 0: # 如果删除了记录 (If records were deleted)
                logger.info(f"成功删除 proxy key: {key} (及其关联的上下文)。") # Log successful deletion
                return True # 返回 True (Return True)
            else:
                logger.warning(f"删除 proxy key '{key}' 失败：Key 未找到。") # Log warning if key not found
                return False # 返回 False (Return False)
    except sqlite3.Error as e:
        logger.error(f"删除 proxy key '{key}' 时出错: {e}", exc_info=True) # 记录删除 Key 错误 (Log error deleting key)
        return False # 出错时返回 False (Return False on error)
