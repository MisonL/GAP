# -*- coding: utf-8 -*-
"""
数据库相关的工具函数和常量，用于避免循环导入。
包括数据库连接获取和表初始化函数。
"""
import sqlite3
import logging
import os
import tempfile
from contextlib import contextmanager
from typing import Optional # Added for type hinting

# 导入配置以获取默认值
from .. import config as app_config

logger = logging.getLogger('my_logger')

# --- 数据库路径配置 ---
_db_path_env = os.environ.get('CONTEXT_DB_PATH')
DATABASE_PATH: str
IS_MEMORY_DB: bool

if _db_path_env:
    # Attempt to use file-based database
    temp_db_path = _db_path_env
    temp_is_memory = False
    try:
        db_dir = os.path.dirname(temp_db_path)
        if db_dir:
             os.makedirs(db_dir, exist_ok=True)
             # Test write permissions
             perm_test_file = os.path.join(db_dir, ".perm_test")
             with open(perm_test_file, "w") as f:
                 f.write("test")
             os.remove(perm_test_file)
        # Permissions seem okay, finalize settings
        DATABASE_PATH = temp_db_path
        IS_MEMORY_DB = temp_is_memory
        logger.info(f"上下文存储：使用文件数据库 -> {DATABASE_PATH}")
    except OSError as e:
        logger.error(f"无法创建或写入数据库目录 {os.path.dirname(temp_db_path)}: {e}。将回退到内存数据库。")
        DATABASE_PATH = "file::memory:?cache=shared"
        IS_MEMORY_DB = True
        logger.info("上下文存储：回退到共享内存数据库 (file::memory:?cache=shared)")
    except Exception as e:
         logger.error(f"检查数据库路径时发生错误 ({temp_db_path}): {e}。将回退到内存数据库。")
         DATABASE_PATH = "file::memory:?cache=shared"
         IS_MEMORY_DB = True
         logger.info("上下文存储：回退到共享内存数据库 (file::memory:?cache=shared)")
else:
    # Default to shared memory database
    DATABASE_PATH = "file::memory:?cache=shared"
    IS_MEMORY_DB = True
    logger.info("上下文存储：使用共享内存数据库 (file::memory:?cache=shared)")

DEFAULT_CONTEXT_TTL_DAYS = getattr(app_config, 'DEFAULT_CONTEXT_TTL_DAYS', 7)

# --- Shared Connection for Memory Mode ---
_shared_memory_conn: Optional[sqlite3.Connection] = None

# --- 内部表创建逻辑 ---
def _create_tables_if_not_exist(conn: sqlite3.Connection):
    """在给定的连接上创建所有必需的表（如果它们不存在）。"""
    try:
        cursor = conn.cursor()
        # logger.debug(f"在连接 {id(conn)} 上检查/创建表...")
        # 创建 proxy_keys 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS proxy_keys (
                key TEXT PRIMARY KEY,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
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

        conn.commit()
        # logger.info(f"在连接 {id(conn)} 上调用了 conn.commit() (表创建)。")
    except sqlite3.Error as e:
        logger.error(f"在连接 {id(conn)} 上创建表时出错: {e}", exc_info=True)
        # Let the caller handle the error propagation

# --- 数据库连接 ---
@contextmanager
def get_db_connection():
    """
    获取数据库连接的上下文管理器。
    在内存模式下，返回一个共享的、持久的连接。
    在文件模式下，返回一个新的连接，并在退出时关闭。
    """
    global _shared_memory_conn # Declare intent to modify the global variable
    conn = None
    is_shared_conn = False # Flag to prevent closing the shared connection

    try:
        if IS_MEMORY_DB:
            if _shared_memory_conn is None:
                logger.info("内存数据库模式：创建共享连接...")
                # Use check_same_thread=False for shared memory connection as it might be accessed by different threads/requests
                _shared_memory_conn = sqlite3.connect(DATABASE_PATH, timeout=10, check_same_thread=False, uri=True)
                _shared_memory_conn.row_factory = sqlite3.Row
                _shared_memory_conn.execute("PRAGMA foreign_keys = ON;")
                logger.info(f"内存数据库模式：在共享连接 {id(_shared_memory_conn)} 上创建表...")
                _create_tables_if_not_exist(_shared_memory_conn) # Create tables only once when the shared connection is made
                logger.info(f"内存数据库模式：共享连接 {id(_shared_memory_conn)} 已初始化。")
            # logger.debug(f"内存数据库模式：返回共享连接 {id(_shared_memory_conn)}")
            conn = _shared_memory_conn
            is_shared_conn = True
            yield conn
        else:
            # File-based database: create a new connection for each request
            # logger.debug(f"文件数据库模式：创建新连接 ({DATABASE_PATH})...")
            conn = sqlite3.connect(DATABASE_PATH, timeout=10, check_same_thread=True) # check_same_thread=True for file DB safety
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            # No need to create tables here for file DB, initialize_db_tables handles it once at startup
            # logger.debug(f"文件数据库连接 {id(conn)} 已准备好。")
            yield conn

    except sqlite3.Error as e:
        logger.error(f"数据库连接或设置错误 ({DATABASE_PATH}): {e}", exc_info=True)
        raise # Re-raise to notify the caller
    finally:
        if conn and not is_shared_conn: # Only close if it's not the shared memory connection
            # logger.debug(f"关闭文件数据库连接 {id(conn)}。")
            conn.close()
        # else:
            # logger.debug(f"保持共享内存连接 {id(conn)} 打开。")


# --- 公共数据库初始化函数 ---
def initialize_db_tables():
    """
    显式初始化数据库表（如果不存在）。应在应用启动时调用一次。
    对于内存数据库，这将创建并缓存共享连接。
    对于文件数据库，这将确保文件和表已创建。
    """
    logger.info(f"开始显式数据库表初始化 ({DATABASE_PATH})...")
    try:
        # Simply getting a connection via the context manager handles initialization
        with get_db_connection() as conn:
             # For memory DB, this creates/retrieves the shared connection and ensures tables exist.
             # For file DB, this creates the file/tables if they don't exist via the first connect.
             logger.info(f"数据库连接已获取 (类型: {'内存共享' if IS_MEMORY_DB else '文件'}, ID: {id(conn)})，初始化检查完成。")
             pass # Connection obtained, initialization logic inside get_db_connection handled it
        logger.info(f"显式数据库表初始化完成 ({DATABASE_PATH})。")
    except sqlite3.Error as e:
        logger.error(f"显式数据库表初始化失败 ({DATABASE_PATH}): {e}", exc_info=True)
        raise RuntimeError(f"无法初始化数据库表: {e}") # Re-raise critical error on startup
    except Exception as e: # Catch other potential exceptions during connection
        logger.error(f"显式数据库表初始化期间发生意外错误: {e}", exc_info=True)
        raise RuntimeError(f"无法初始化数据库表: {e}")

# --- Proxy Key Management Functions ---

def get_all_proxy_keys() -> list[sqlite3.Row]:
    """获取所有代理 Key 及其信息。"""
    logger.debug("获取所有 proxy keys...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, description, created_at, is_active FROM proxy_keys ORDER BY created_at DESC")
            keys = cursor.fetchall()
            logger.debug(f"成功获取 {len(keys)} 个 proxy keys。")
            return keys
    except sqlite3.Error as e:
        logger.error(f"获取所有 proxy keys 时出错: {e}", exc_info=True)
        return [] # Return empty list on error

def get_proxy_key(key: str) -> Optional[sqlite3.Row]:
    """获取单个代理 Key 的信息。"""
    logger.debug(f"获取 proxy key: {key}...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, description, created_at, is_active FROM proxy_keys WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                logger.debug(f"成功获取 proxy key: {key}。")
            else:
                logger.debug(f"Proxy key 未找到: {key}。")
            return row
    except sqlite3.Error as e:
        logger.error(f"获取 proxy key '{key}' 时出错: {e}", exc_info=True)
        return None

def add_proxy_key(key: str, description: str = "") -> bool:
    """
    添加一个新的代理 Key。
    如果 Key 已存在，则不执行任何操作并返回 False。
    """
    logger.info(f"尝试添加 proxy key: {key}...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # 使用 INSERT OR IGNORE 避免因 Key 已存在而出错
            cursor.execute("INSERT OR IGNORE INTO proxy_keys (key, description, is_active) VALUES (?, ?, ?)",
                           (key, description, True))
            conn.commit()
            # rowcount 会告诉我们是否实际插入了行
            if cursor.rowcount > 0:
                logger.info(f"成功添加 proxy key: {key}。")
                return True
            else:
                logger.warning(f"添加 proxy key 失败，Key '{key}' 可能已存在。")
                return False
    except sqlite3.Error as e:
        logger.error(f"添加 proxy key '{key}' 时出错: {e}", exc_info=True)
        return False

def update_proxy_key(key: str, description: Optional[str] = None, is_active: Optional[bool] = None) -> bool:
    """
    更新代理 Key 的描述或激活状态。
    至少需要提供 description 或 is_active 中的一个。
    """
    if description is None and is_active is None:
        logger.warning(f"更新 proxy key '{key}' 失败：未提供要更新的字段 (description 或 is_active)。")
        return False

    logger.info(f"尝试更新 proxy key: {key}...")
    updates = []
    params = []

    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(is_active)

    params.append(key) # For the WHERE clause

    sql = f"UPDATE proxy_keys SET {', '.join(updates)} WHERE key = ?"

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"成功更新 proxy key: {key}。")
                return True
            else:
                logger.warning(f"更新 proxy key '{key}' 失败：Key 未找到或值未改变。")
                return False
    except sqlite3.Error as e:
        logger.error(f"更新 proxy key '{key}' 时出错: {e}", exc_info=True)
        return False

def delete_proxy_key(key: str) -> bool:
    """
    删除一个代理 Key。
    由于设置了 FOREIGN KEY ... ON DELETE CASCADE，关联的上下文也会被删除。
    """
    logger.info(f"尝试删除 proxy key: {key}...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM proxy_keys WHERE key = ?", (key,))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"成功删除 proxy key: {key} (及其关联的上下文)。")
                return True
            else:
                logger.warning(f"删除 proxy key '{key}' 失败：Key 未找到。")
                return False
    except sqlite3.Error as e:
        logger.error(f"删除 proxy key '{key}' 时出错: {e}", exc_info=True)
        return False
