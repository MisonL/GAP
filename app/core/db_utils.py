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
from typing import Optional # 为类型提示添加

# 导入配置以获取默认值
from .. import config as app_config

logger = logging.getLogger('my_logger')

# --- 数据库路径配置 ---
_db_path_env = os.environ.get('CONTEXT_DB_PATH')
DATABASE_PATH: str
IS_MEMORY_DB: bool

if _db_path_env:
    # 尝试使用基于文件的数据库
    temp_db_path = _db_path_env
    temp_is_memory = False
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
    # 默认使用共享内存数据库
    DATABASE_PATH = "file::memory:?cache=shared" # SQLite 共享内存数据库 URI
    IS_MEMORY_DB = True
    logger.info("上下文存储：使用共享内存数据库 (file::memory:?cache=shared)")

DEFAULT_CONTEXT_TTL_DAYS = getattr(app_config, 'DEFAULT_CONTEXT_TTL_DAYS', 7)

# --- 内存模式下的共享连接 ---
_shared_memory_conn: Optional[sqlite3.Connection] = None # 用于缓存共享内存连接

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
        # 让调用者处理错误传播

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
    is_shared_conn = False # 标记以防止关闭共享连接

    try:
        if IS_MEMORY_DB:
            if _shared_memory_conn is None: # 如果共享连接尚未创建
                logger.info("内存数据库模式：创建共享连接...")
                # 对于共享内存连接使用 check_same_thread=False，因为它可能被不同的线程/请求访问
                _shared_memory_conn = sqlite3.connect(DATABASE_PATH, timeout=10, check_same_thread=False, uri=True)
                _shared_memory_conn.row_factory = sqlite3.Row # 设置行工厂以字典形式访问列
                _shared_memory_conn.execute("PRAGMA foreign_keys = ON;") # 启用外键约束
                logger.info(f"内存数据库模式：在共享连接 {id(_shared_memory_conn)} 上创建表...")
                _create_tables_if_not_exist(_shared_memory_conn) # 仅在创建共享连接时创建一次表
                logger.info(f"内存数据库模式：共享连接 {id(_shared_memory_conn)} 已初始化。")
            # logger.debug(f"内存数据库模式：返回共享连接 {id(_shared_memory_conn)}")
            conn = _shared_memory_conn
            is_shared_conn = True
            yield conn
        else:
            # 基于文件的数据库：为每个请求创建一个新连接
            # logger.debug(f"文件数据库模式：创建新连接 ({DATABASE_PATH})...")
            conn = sqlite3.connect(DATABASE_PATH, timeout=10, check_same_thread=True) # 文件数据库使用 check_same_thread=True 以确保安全
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            # 文件数据库不需要在此处创建表，initialize_db_tables 会在启动时处理一次
            # logger.debug(f"文件数据库连接 {id(conn)} 已准备好。")
            yield conn

    except sqlite3.Error as e:
        logger.error(f"数据库连接或设置错误 ({DATABASE_PATH}): {e}", exc_info=True)
        raise # 重新抛出异常以通知调用者
    finally:
        if conn and not is_shared_conn: # 仅当不是共享内存连接时才关闭
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
        # 只需通过上下文管理器获取连接即可处理初始化
        with get_db_connection() as conn:
             # 对于内存数据库，这将创建/检索共享连接并确保表存在。
             # 对于文件数据库，这将在首次连接时创建文件/表（如果它们不存在）。
             logger.info(f"数据库连接已获取 (类型: {'内存共享' if IS_MEMORY_DB else '文件'}, ID: {id(conn)})，初始化检查完成。")
             pass # 连接已获取，get_db_connection 内部的初始化逻辑已处理
        logger.info(f"显式数据库表初始化完成 ({DATABASE_PATH})。")
    except sqlite3.Error as e:
        logger.error(f"显式数据库表初始化失败 ({DATABASE_PATH}): {e}", exc_info=True)
        raise RuntimeError(f"无法初始化数据库表: {e}") # 启动时重新抛出严重错误
    except Exception as e: # 捕获连接期间其他可能的异常
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
        return [] # 出错时返回空列表

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

    params.append(key) # 用于 WHERE 子句

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
