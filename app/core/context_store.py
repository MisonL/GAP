# -*- coding: utf-8 -*-
"""
处理 SQLite 数据库交互，用于存储代理密钥、对话上下文和设置。
支持文件存储（持久化）和内存存储（临时）。
Handles SQLite database interactions for storing proxy keys, conversation context, and settings.
Supports file storage (persistence) and in-memory storage (temporary).
"""
import sqlite3 # 导入 sqlite3 模块 (Import sqlite3 module)
import logging # 导入 logging 模块 (Import logging module)
import os # 导入 os 模块 (Import os module)
import json # 导入 json 模块 (Import json module)
import uuid # 导入 uuid 模块 (Import uuid module)
import asyncio # 导入 asyncio (Import asyncio)
from datetime import datetime, timedelta, timezone # 导入日期、时间、时区相关 (Import date, time, timezone related)
from typing import Optional, List, Dict, Any, Tuple # 导入类型提示 (Import type hints)
# from contextlib import contextmanager # 不再需要 (No longer needed)

# 导入配置以获取默认值 (现在由 db_settings 处理)
# Import configuration to get default values (now handled by db_settings)
# from .. import config as app_config
from ..core import key_management # 导入 key_management 模块 (Import key_management module)
# 导入新的设置管理模块
# Import new settings management module
from .db_settings import get_ttl_days, set_ttl_days # 注意：这些也需要变成 async (Note: These also need to become async)
# 导入共享的数据库工具 和 新配置项
# Import shared database tools and new configuration items
from .db_utils import get_db_connection, DATABASE_PATH, IS_MEMORY_DB, DEFAULT_CONTEXT_TTL_DAYS # 导入数据库连接、路径、内存模式标志、默认 TTL (Import database connection, path, memory mode flag, default TTL)
from ..config import MAX_CONTEXT_RECORDS_MEMORY # 导入最大记录数配置 (Import max records configuration)

logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

# --- 数据库路径配置 (已移至 db_utils.py) ---
# --- Database Path Configuration (Moved to db_utils.py) ---
# ...

# --- 数据库连接 (已移至 db_utils.py) ---
# --- Database Connection (Moved to db_utils.py) ---
# @contextmanager
# def get_db_connection(): ...

# --- 数据库初始化 (已移至 db_utils.py) ---
# --- Database Initialization (Moved to db_utils.py) ---
# def initialize_database(): ...

# --- 设置管理 (已移至 db_settings.py) ---
# --- Settings Management (Moved to db_settings.py) ---
# def get_setting(...): ...
# def set_setting(...): ...
# def get_ttl_days(...): ...
# def set_ttl_days(...): ...

# --- 代理 Key 管理 (部分保留，用于 API 认证) ---
# --- Proxy Key Management (Partially retained for API authentication) ---
# generate_proxy_key, add_proxy_key, list_proxy_keys, update_proxy_key, delete_proxy_key 已移除，因为 Web UI 已移除
# generate_proxy_key, add_proxy_key, list_proxy_keys, update_proxy_key, delete_proxy_key have been removed because the Web UI has been removed

# 注意：此函数现在需要是 async，因为它调用了 async 的 get_db_connection
# Note: This function now needs to be async because it calls the async get_db_connection
async def get_proxy_key(key: str) -> Optional[Dict[str, Any]]:
     """
     获取单个代理 Key 的信息。
     Gets information for a single proxy key.
     """
     if not key: return None # 如果 Key 为空则返回 None (Return None if key is empty)
     try:
         async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
             cursor = conn.cursor() # 获取游标 (Get cursor)
             # 在线程中执行同步的数据库操作
             # Execute synchronous database operations in a thread
             await asyncio.to_thread(cursor.execute, "SELECT key, description, created_at, is_active FROM proxy_keys WHERE key = ?", (key,))
             row = await asyncio.to_thread(cursor.fetchone) # 在线程中获取单行结果 (Fetch single row result in a thread)
             return dict(row) if row else None # 如果找到行则转换为字典并返回，否则返回 None (Convert row to dictionary and return if found, otherwise return None)
     except sqlite3.Error as e:
         logger.error(f"获取代理 Key {key[:8]}... 信息失败: {e}", exc_info=True) # 记录错误 (Log error)
         return None # 出错时返回 None (Return None on error)

# 注意：此函数现在需要是 async，因为它调用了 async 的 get_proxy_key
# Note: This function now needs to be async because it calls the async get_proxy_key
async def is_valid_proxy_key(key: str) -> bool:
    """
    检查代理 Key 是否有效且处于活动状态 (从数据库)。
    Checks if a proxy key is valid and active (from the database).
    """
    key_info = await get_proxy_key(key) # 使用 await 调用 (Call with await)
    return bool(key_info and key_info.get('is_active')) # 返回 Key 是否有效且活跃 (Return whether the key is valid and active)

# list_proxy_keys 已移除
# list_proxy_keys removed
# update_proxy_key 已移除
# update_proxy_key removed
# delete_proxy_key 已移除
# delete_proxy_key removed

# --- 上下文管理 ---
# --- Context Management ---
# 注意：此函数现在需要是 async
# Note: This function now needs to be async
async def save_context(proxy_key: str, contents: List[Dict[str, Any]]):
    """
    保存或更新指定代理 Key 的上下文。
    Saves or updates the context for the specified proxy key.
    """
    if not proxy_key or not contents:
        logger.warning(f"尝试为 Key {proxy_key[:8]}... 保存空的上下文，已跳过。") # Log warning for attempting to save empty context
        return
    try:
        try:
            # json.dumps 是 CPU 密集型操作，也可以考虑放入 to_thread
            # json.dumps is a CPU-intensive operation, can also consider putting it in to_thread
            contents_json = await asyncio.to_thread(json.dumps, contents, ensure_ascii=False) # 在线程中序列化 JSON (Serialize JSON in a thread)
            # contents_json = json.dumps(contents, ensure_ascii=False) # 或者保持同步如果性能影响不大 (Or keep it synchronous if performance impact is not significant)
        except TypeError as json_err:
            logger.error(f"序列化上下文为 JSON 时失败 (TypeError) (Key: {proxy_key[:8]}...): {json_err}", exc_info=True) # 记录 JSON 序列化错误 (Log JSON serialization error)
            return # 无法序列化，直接返回 (Cannot serialize, return directly)

        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            cursor = conn.cursor() # 获取游标 (Get cursor)
            # 使用 ISO 格式存储 UTC 时间戳
            # Store UTC timestamp in ISO format
            last_used_ts = datetime.now(timezone.utc).isoformat() # 获取当前 UTC 时间并格式化 (Get current UTC time and format)
            # 在引用之前确保 proxy_key 存在于 proxy_keys 表中
            # Ensure proxy_key exists in the proxy_keys table before referencing it
            # 这对于内存模式至关重要，因为 Key 可能不会预先填充
            # This is crucial for memory mode as keys might not be pre-populated
            await asyncio.to_thread(cursor.execute, "INSERT OR IGNORE INTO proxy_keys (key) VALUES (?)", (proxy_key,)) # 插入或忽略 Key (Insert or ignore the key)
            logger.info(f"准备在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 执行 INSERT OR REPLACE...") # 日志级别改为 info (Changed log level to info)
            await asyncio.to_thread(
                cursor.execute,
                """
                INSERT OR REPLACE INTO contexts (proxy_key, contents, last_used)
                VALUES (?, ?, ?)
                """,
                (proxy_key, contents_json, last_used_ts)
            ) # 在线程中执行插入或替换操作 (Execute INSERT or REPLACE operation in a thread)
            logger.info(f"在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 执行 INSERT OR REPLACE 完成。") # 移除了 "准备提交" 日志 (Removed "preparing to commit" log)

            # --- 新增：内存数据库记录数限制 ---
            # --- New: Memory Database Record Count Limit ---
            if IS_MEMORY_DB and MAX_CONTEXT_RECORDS_MEMORY > 0: # 如果是内存数据库且设置了最大记录数 (If it's an in-memory database and max records is set)
                try:
                    # 获取当前记录数
                    # Get current record count
                    await asyncio.to_thread(cursor.execute, "SELECT COUNT(*) FROM contexts") # 在线程中执行计数查询 (Execute count query in a thread)
                    count_row = await asyncio.to_thread(cursor.fetchone) # 在线程中获取计数结果 (Fetch count result in a thread)
                    current_count = count_row[0] if count_row else 0 # 获取当前记录数 (Get current record count)
                    # logger.debug(f"内存数据库当前记录数: {current_count}, 限制: {MAX_CONTEXT_RECORDS_MEMORY}") # 调试日志 (Debug log)

                    if current_count > MAX_CONTEXT_RECORDS_MEMORY: # 如果当前记录数超过限制 (If current record count exceeds limit)
                        num_to_delete = current_count - MAX_CONTEXT_RECORDS_MEMORY # 计算需要删除的数量 (Calculate number to delete)
                        logger.info(f"内存数据库记录数 ({current_count}) 已超过限制 ({MAX_CONTEXT_RECORDS_MEMORY})，将删除 {num_to_delete} 条最旧的记录...") # Log that records will be deleted
                        # 删除 last_used 最早的记录
                        # Delete records with the earliest last_used
                        # 使用 rowid 可以确保删除的是物理上最早插入（或最近未更新）的行
                        # Using rowid ensures that the physically earliest inserted (or least recently updated) rows are deleted
                        await asyncio.to_thread(
                            cursor.execute,
                            """
                            DELETE FROM contexts
                            WHERE rowid IN (
                                SELECT rowid FROM contexts ORDER BY last_used ASC LIMIT ?
                            )
                            """,
                            (num_to_delete,)
                        ) # 在线程中执行删除操作 (Execute delete operation in a thread)
                        rowcount = cursor.rowcount # 获取同步操作的 rowcount (Get rowcount of the synchronous operation)
                        logger.info(f"成功删除了 {rowcount} 条最旧的内存上下文记录。") # Log successful deletion
                except sqlite3.Error as prune_err:
                    # 记录修剪错误，但不影响主保存操作的提交
                    # Log pruning error, but it does not affect the commit of the main save operation
                    logger.error(f"修剪内存上下文记录时出错 (Key: {proxy_key[:8]}...): {prune_err}", exc_info=True) # Log pruning error

            # 提交事务（包括插入/替换和可能的删除）
            # Commit the transaction (including insert/replace and potential deletion)
            logger.info(f"准备在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 提交事务...") # Log preparing to commit
            await asyncio.to_thread(conn.commit) # 在线程中提交事务 (Commit transaction in a thread)
            logger.info(f"在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 提交事务完成。") # Log commit complete
    except sqlite3.Error as e:
        logger.error(f"为 Key {proxy_key[:8]}... 保存上下文失败: {e}", exc_info=True) # 记录保存失败错误 (Log save failure error)
    except json.JSONDecodeError as e:
        logger.error(f"反序列化上下文为 JSON 时失败 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 修正了日志消息：反序列化错误 (Corrected log message: deserialization error)
    except Exception as e: # 捕获保存期间任何其他意外错误 (Catch any other unexpected errors during saving)
        logger.error(f"保存上下文时发生意外错误 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 记录意外错误 (Log unexpected error)

# 注意：此函数现在需要是 async
# Note: This function now needs to be async
async def load_context(proxy_key: str) -> Optional[List[Dict[str, Any]]]:
    """
    加载指定代理 Key 的上下文，并检查 TTL。
    Loads the context for the specified proxy key and checks TTL.
    """
    if not proxy_key: return None # 如果 Key 为空则返回 None (Return None if key is empty)

    # 注意：get_ttl_days 也需要变成 async
    # Note: get_ttl_days also needs to become async
    ttl_days = await get_ttl_days() # 获取 TTL 天数 (Get TTL days)
    # 如果 TTL <= 0，则禁用 TTL 检查
    # If TTL <= 0, disable TTL check
    if ttl_days <= 0:
        ttl_delta = None # TTL 时间差为 None (TTL timedelta is None)
    else:
        ttl_delta = timedelta(days=ttl_days) # 计算 TTL 时间差 (Calculate TTL timedelta)

    now_utc = datetime.now(timezone.utc) # 获取当前 UTC 时间 (Get current UTC time)

    try:
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            cursor = conn.cursor() # 获取游标 (Get cursor)
            await asyncio.to_thread(cursor.execute, "SELECT contents, last_used FROM contexts WHERE proxy_key = ?", (proxy_key,)) # 在线程中查询上下文 (Query context in a thread)
            row = await asyncio.to_thread(cursor.fetchone) # 在线程中获取单行结果 (Fetch single row result in a thread)

            if row and row['contents']: # 如果找到记录且内容不为空 (If record is found and content is not empty)
                last_used_str = row['last_used'] # 获取最后使用时间字符串 (Get last used time string)
                # 检查 TTL (仅当 ttl_delta 有效时)
                # Check TTL (only if ttl_delta is valid)
                if ttl_delta:
                    try:
                        # 解析存储的 ISO 格式 UTC 时间戳
                        # Parse the stored ISO format UTC timestamp
                        last_used_dt = datetime.fromisoformat(last_used_str).replace(tzinfo=timezone.utc) # 解析时间戳并设置为 UTC (Parse timestamp and set to UTC)
                        if now_utc - last_used_dt > ttl_delta: # 如果超过 TTL (If older than TTL)
                            logger.info(f"Key {proxy_key[:8]}... 的上下文已超过 TTL ({ttl_days} 天)，将被删除。") # Log that context has exceeded TTL and will be deleted
                            await delete_context_for_key(proxy_key) # 调用异步删除函数 (Call asynchronous delete function)
                            return None # 返回 None (Return None)
                    except (ValueError, TypeError) as dt_err:
                         logger.error(f"解析 Key {proxy_key[:8]}... 的 last_used 时间戳 '{last_used_str}' 失败: {dt_err}") # Log timestamp parsing error
                         # 时间戳无效，可能也需要删除？或者忽略 TTL 检查？暂时忽略 TTL 检查。
                         # Invalid timestamp, maybe also needs to be deleted? Or ignore TTL check? Temporarily ignore TTL check.
                         pass # 继续尝试加载内容 (Continue attempting to load content)

                # TTL 检查通过、被禁用或解析失败，尝试加载内容
                # TTL check passed, disabled, or parsing failed, attempt to load content
                try:
                    # json.loads 也可以考虑放入 to_thread
                    # json.loads can also be considered for putting into to_thread
                    contents = await asyncio.to_thread(json.loads, row['contents']) # 在线程中反序列化 JSON (Deserialize JSON in a thread)
                    # contents = json.loads(row['contents'])
                    logger.debug(f"上下文已为 Key {proxy_key[:8]}... 加载。") # Log that context has been loaded (DEBUG level)
                    return contents # 返回加载的上下文 (Return the loaded context)
                except json.JSONDecodeError as e:
                    logger.error(f"反序列化存储的上下文时失败 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 记录反序列化错误 (Log deserialization error)
                    # 删除损坏的数据，避免下次加载时再次出错
                    # Delete corrupted data to avoid errors on next load
                    await delete_context_for_key(proxy_key) # 调用异步删除函数 (Call asynchronous delete function)
                    return None # 返回 None (Return None)
            else:
                logger.debug(f"未找到 Key {proxy_key[:8]}... 的上下文。") # Log that context was not found (DEBUG level)
                return None # 返回 None (Return None)
    except sqlite3.Error as e:
        logger.error(f"为 Key {proxy_key[:8]}... 加载上下文失败: {e}", exc_info=True) # 记录加载失败错误 (Log load failure error)
        return None # 出错时返回 None (Return None on error)

# 注意：此函数现在需要是 async
# Note: This function now needs to be async
async def delete_context_for_key(proxy_key: str) -> bool:
    """
    删除指定代理 Key 的上下文记录。
    Deletes the context record for the specified proxy key.
    """
    if not proxy_key: return False # 如果 Key 为空则返回 False (Return False if key is empty)
    try:
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            cursor = conn.cursor() # 获取游标 (Get cursor)
            await asyncio.to_thread(cursor.execute, "DELETE FROM contexts WHERE proxy_key = ?", (proxy_key,)) # 在线程中执行删除操作 (Execute delete operation in a thread)
            rowcount = cursor.rowcount # 获取同步操作的 rowcount (Get rowcount of the synchronous operation)
            await asyncio.to_thread(conn.commit) # 在线程中提交事务 (Commit transaction in a thread)
            if rowcount > 0: # 如果删除了记录 (If records were deleted)
                logger.info(f"上下文已为 Key {proxy_key[:8]}... 删除。") # Log that context has been deleted
                return True # 返回 True (Return True)
            else:
                # 这不一定是警告，可能只是记录不存在或已被 TTL 清理
                # This is not necessarily a warning, it might just mean the record didn't exist or was already cleaned by TTL
                logger.debug(f"尝试删除 Key {proxy_key[:8]}... 的上下文，但未找到记录。") # Log that no record was found for deletion (DEBUG level)
                return False # 返回 False (Return False)
    except sqlite3.Error as e:
        logger.error(f"删除 Key {proxy_key[:8]}... 的上下文失败: {e}", exc_info=True) # 记录删除失败错误 (Log delete failure error)
        return False # 出错时返回 False (Return False on error)

# 注意：此函数现在需要是 async
# Note: This function now needs to be async
async def get_context_info(proxy_key: str) -> Optional[Dict[str, Any]]:
     """
     获取指定代理 Key 上下文的元信息。
     Gets metadata for the specified proxy key's context.
     """
     if not proxy_key: return None # 如果 Key 为空则返回 None (Return None if key is empty)
     try:
         async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
             cursor = conn.cursor() # 获取游标 (Get cursor)
             await asyncio.to_thread(cursor.execute, "SELECT length(contents) as content_length, last_used FROM contexts WHERE proxy_key = ?", (proxy_key,)) # 在线程中查询上下文信息 (Query context info in a thread)
             row = await asyncio.to_thread(cursor.fetchone) # 在线程中获取单行结果 (Fetch single row result in a thread)
             return dict(row) if row else None # 如果找到行则转换为字典并返回，否则返回 None (Convert row to dictionary and return if found, otherwise return None)
     except sqlite3.Error as e:
         logger.error(f"获取 Key {proxy_key[:8]}... 的上下文信息失败: {e}", exc_info=True) # 记录获取信息失败错误 (Log failure to get info error)
         return None # 出错时返回 None (Return None on error)

# 注意：此函数现在需要是 async
# Note: This function now needs to be async
async def list_all_context_keys_info(user_key: Optional[str] = None, is_admin: bool = False) -> List[Dict[str, Any]]:
    """
    获取存储的上下文的 Key 和元信息。
    - 如果 is_admin 为 True，返回所有上下文信息。
    - 如果 is_admin 为 False 且提供了 user_key，仅返回该用户的上下文信息。
    - 否则返回空列表。
    Gets the keys and metadata of stored contexts.
    - If is_admin is True, returns information for all contexts.
    - If is_admin is False and user_key is provided, returns information only for that user's context.
    - Otherwise, returns an empty list.

    Args:
        user_key: 当前用户的 Key。The current user's key.
        is_admin: 当前用户是否为管理员。Whether the current user is an administrator.

    Returns:
        包含上下文信息的字典列表。A list of dictionaries containing context information.
    """
    contexts_info = [] # 初始化上下文信息列表 (Initialize list of context info)
    try:
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            cursor = conn.cursor() # 获取游标 (Get cursor)
            sql = "SELECT proxy_key, length(contents) as content_length, last_used FROM contexts" # 构建 SQL 查询语句 (Build SQL query statement)
            params: Tuple = () # 初始化参数元组 (Initialize parameters tuple)

            if is_admin: # 如果是管理员 (If it's an admin)
                logger.info(f"管理员请求所有上下文信息 (连接 ID: {id(conn)})...") # Log admin request for all context info
                sql += " ORDER BY last_used DESC" # 按最后使用时间降序排序 (Order by last_used descending)
            elif user_key: # 如果提供了用户 Key (If user key is provided)
                logger.info(f"用户 {user_key[:8]}... 请求其上下文信息 (连接 ID: {id(conn)})...") # Log user request for their context info
                sql += " WHERE proxy_key = ? ORDER BY last_used DESC" # 按 Key 过滤并按最后使用时间降序排序 (Filter by key and order by last_used descending)
                params = (user_key,) # 设置查询参数 (Set query parameters)
            else:
                # 非管理员且未提供 user_key，不应查询任何内容
                # Not admin and no user_key provided, should not query anything
                logger.warning(f"非管理员尝试列出上下文但未提供 user_key (连接 ID: {id(conn)})。") # Log warning for non-admin without user_key
                return [] # 直接返回空列表 (Return empty list directly)

            await asyncio.to_thread(cursor.execute, sql, params) # 在线程中执行查询 (Execute query in a thread)
            rows = await asyncio.to_thread(cursor.fetchall) # 在线程中获取所有结果 (Fetch all results in a thread)
            logger.info(f"list_all_context_keys_info: Fetched {len(rows)} rows from DB for {'admin' if is_admin else user_key[:8]+'...'}. Raw rows: {rows}") # Log number of rows fetched
            contexts_info = [dict(row) for row in rows] # 将结果转换为字典列表 (Convert results to list of dictionaries)
    except sqlite3.Error as e:
        log_prefix = f"管理员" if is_admin else f"用户 {user_key[:8]}..." if user_key else "未知用户" # 构建日志前缀 (Build log prefix)
        logger.error(f"{log_prefix} 列出上下文信息失败 ({DATABASE_PATH}): {e}", exc_info=True) # 记录列出信息失败错误 (Log failure to list info error)
        contexts_info = [] # 出错时返回空列表 (Return empty list on error)
    return contexts_info # 返回上下文信息列表 (Return list of context info)

# --- 内存数据库清理 ---
# --- Memory Database Cleanup ---
# 注意：此函数现在需要是 async
# Note: This function now needs to be async
async def cleanup_memory_context(max_age_seconds: int):
    """
    清理内存数据库中超过指定时间的旧上下文记录。
    Cleans up old context records in the in-memory database that are older than the specified time.
    """
    if not IS_MEMORY_DB: # 如果不是内存数据库 (If it's not an in-memory database)
        # logger.debug("非内存数据库模式，跳过内存清理任务。") # 减少不必要的日志噪音 (Reduce unnecessary log noise)
        return

    if max_age_seconds <= 0: # 如果最大年龄无效 (If max age is invalid)
        logger.warning("内存上下文清理间隔无效 (<= 0)，跳过清理。") # Log warning for invalid cleanup interval
        return

    cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds) # 计算截止时间 (Calculate cutoff time)
    # 使用 ISO 格式进行比较
    # Use ISO format for comparison
    cutoff_timestamp_str = cutoff_time.isoformat() # 格式化截止时间戳 (Format cutoff timestamp)
    deleted_count = 0 # 初始化删除计数 (Initialize deleted count)

    logger.info(f"开始清理内存数据库中早于 {cutoff_timestamp_str} UTC 的上下文...") # Log cleanup start
    try:
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            cursor = conn.cursor() # 获取游标 (Get cursor)
            # 删除 last_used 早于截止时间的记录
            # Delete records where last_used is earlier than the cutoff time
            # 注意：SQLite 的时间字符串比较依赖于一致的格式 (ISO 8601)
            # Note: SQLite's time string comparison relies on a consistent format (ISO 8601)
            await asyncio.to_thread(cursor.execute, "DELETE FROM contexts WHERE last_used < ?", (cutoff_timestamp_str,)) # 在线程中执行删除操作 (Execute delete operation in a thread)
            deleted_count = cursor.rowcount # 获取同步操作的 rowcount (Get rowcount of the synchronous operation)
            await asyncio.to_thread(conn.commit) # 在线程中提交事务 (Commit transaction in a thread)
        if deleted_count > 0: # 如果删除了记录 (If records were deleted)
            logger.info(f"成功清理了 {deleted_count} 条过期的内存上下文记录。") # Log successful cleanup
        else:
            logger.info("没有需要清理的过期内存上下文记录。") # Log that no expired records were found
    except sqlite3.Error as e:
        logger.error(f"清理内存上下文时出错: {e}", exc_info=True) # 记录清理错误 (Log cleanup error)
