# -*- coding: utf-8 -*-
"""
处理 SQLite 数据库交互，用于存储和管理对话上下文。
支持文件存储（持久化）和内存存储（临时）。
包含加载、保存、删除上下文，以及检查 TTL 和清理内存数据库的功能。
"""
import aiosqlite # 导入 aiosqlite 模块，用于异步 SQLite 操作
import logging # 导入日志模块
import os # 导入 os 模块 (在此文件中未使用，但保留可能有用)
import json # 导入 json 模块，用于序列化和反序列化上下文内容
import uuid # 导入 uuid 模块 (在此文件中未使用，但保留可能有用)
import asyncio # 导入 asyncio 库，用于异步操作和线程池
from datetime import datetime, timedelta, timezone # 导入日期、时间、时间差和时区处理
from contextlib import asynccontextmanager # 导入异步上下文管理器
from typing import Optional, List, Dict, Any, Tuple, Union, AsyncGenerator # 导入类型提示
from sqlalchemy import select, delete # <--- 添加导入
from app.core.context.converter import convert_messages # 导入消息转换函数 (新路径)

# 导入 Message Pydantic 模型，用于类型检查和数据结构定义
from app.api.models import Message

# 导入数据库设置管理模块中的函数
from app.core.database.settings import get_ttl_days, set_ttl_days # (新路径)
# 导入应用配置中的内存数据库最大记录数限制
from app.config import MAX_CONTEXT_RECORDS_MEMORY, CONTEXT_STORAGE_MODE, CONTEXT_DB_PATH # 导入配置

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# 注意：原文件中 get_proxy_key 和 is_valid_proxy_key 函数似乎与上下文存储关系不大，
# 且可能与 app.core.keys 中的功能重复或冲突。在添加注释时暂时保留，但建议审查其必要性。

async def get_proxy_key(key: str) -> Optional[Dict[str, Any]]:
     """
     (可能需要审查/移除) 获取单个代理 Key 的信息 (似乎与 Key 管理功能重复)。
     """
     if not key: return None # 如果 key 为空，返回 None
     try:
         # 延迟导入 db_utils
         from app.core.database.utils import get_db_connection # (新路径)
         async with get_db_connection() as conn: # 获取异步数据库连接
             async with conn.cursor() as cursor: # 使用异步游标
                 # 从 proxy_keys 表查询信息 (注意：表名可能需要与 models.py 统一)
                 await cursor.execute("SELECT key, description, created_at, is_active FROM proxy_keys WHERE key = ?", (key,))
                 row = await cursor.fetchone() # 获取查询结果
             # 将查询结果行转换为字典返回，如果未找到则返回 None
             return dict(row) if row else None
     except aiosqlite.Error as e: # 捕获数据库错误
         logger.error(f"获取代理 Key {key[:8]}... 信息失败: {e}", exc_info=True) # 记录错误日志
         return None # 出错时返回 None

async def is_valid_proxy_key(key: str) -> bool:
    """
    (可能需要审查/移除) 检查代理 Key 是否有效且处于活动状态 (似乎与 Key 管理功能重复)。
    """
    key_info = await get_proxy_key(key) # 调用上面的函数获取 Key 信息
    # 返回 Key 是否存在且 is_active 字段为 True
    return bool(key_info and key_info.get('is_active'))


async def save_context(proxy_key: str, contents: List[Dict[str, Any]]):
    """
    异步保存或更新指定代理 Key (通常是 user_id) 的对话上下文到数据库。
    如果记录已存在，则替换；如果不存在，则插入新记录。
    同时会更新 `last_used` 时间戳。
    在内存数据库模式下，会检查并清理超出数量限制的旧记录。

    Args:
        proxy_key (str): 用于标识上下文的键 (通常是 user_id)。
        contents (List[Dict[str, Any]]): 要保存的 Gemini 格式的对话内容列表。
    """
    # 检查输入是否有效
    if not proxy_key or not contents:
        logger.warning(f"尝试为 Key {proxy_key[:8]}... 保存空的上下文，已跳过。") # 记录警告
        return # 直接返回

    try:
        # --- 序列化上下文内容 ---
        try:
            # json.dumps 是 CPU 密集型操作，可以考虑使用 asyncio.to_thread 在线程池中执行以避免阻塞事件循环
            contents_json = await asyncio.to_thread(json.dumps, contents, ensure_ascii=False)
            # 或者，如果性能影响不大，可以直接同步执行：
            # contents_json = json.dumps(contents, ensure_ascii=False)
        except TypeError as json_err: # 捕获序列化错误
            logger.error(f"序列化上下文为 JSON 时失败 (TypeError) (Key: {proxy_key[:8]}...): {json_err}", exc_info=True)
            return # 无法序列化，直接返回

        # --- 数据库操作 ---
        # 延迟导入数据库工具函数
        from app.core.database.utils import get_db_connection, IS_MEMORY_DB, DATABASE_PATH # (新路径)
        async with get_db_connection() as conn: # 获取异步数据库连接
            async with conn.cursor() as cursor: # 创建异步游标
                # 获取当前的 UTC 时间并格式化为 ISO 格式字符串
                last_used_ts = datetime.now(timezone.utc).isoformat()

                # (可选，取决于数据库模式) 确保 proxy_key 在关联表中存在
                # 对于 SQLite，如果 contexts 表有外键约束指向 proxy_keys 表，需要先确保 proxy_keys 中有记录
                # 这里使用 INSERT OR IGNORE 尝试插入，如果已存在则忽略错误
                # 注意：表名 'proxy_keys' 可能需要与 models.py 中的定义核对
                # await cursor.execute("INSERT OR IGNORE INTO proxy_keys (key) VALUES (?)", (proxy_key,))

                # 执行插入或替换操作，将上下文存入 contexts 表
                logger.debug(f"准备在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 执行 INSERT OR REPLACE...") # 记录调试日志
                await cursor.execute(
                    """
                    INSERT OR REPLACE INTO contexts (proxy_key, contents, last_used)
                    VALUES (?, ?, ?)
                    """,
                    (proxy_key, contents_json, last_used_ts) # 传递参数
                )
                logger.debug(f"在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 执行 INSERT OR REPLACE 完成。") # 记录调试日志

                # --- 内存数据库记录数限制 ---
                # 如果是内存数据库且设置了最大记录数限制
                if IS_MEMORY_DB and MAX_CONTEXT_RECORDS_MEMORY > 0:
                    # 调用辅助函数进行清理
                    await _prune_memory_context(cursor)

            # 提交数据库事务（保存插入/替换和可能的删除操作）
            logger.debug(f"准备在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 提交事务...") # 记录调试日志
            await conn.commit() # 提交事务
            logger.info(f"上下文已为 Key {proxy_key[:8]}... 保存/更新。") # 记录成功日志
    except aiosqlite.Error as e: # 捕获数据库操作错误
        logger.error(f"为 Key {proxy_key[:8]}... 保存上下文失败: {e}", exc_info=True) # 记录错误
    except Exception as e: # 捕获其他意外错误
        logger.error(f"保存上下文时发生意外错误 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 记录错误

async def _prune_memory_context(cursor: aiosqlite.Cursor):
    """
    (内部辅助函数) 修剪内存数据库中的上下文记录，移除最旧的记录，
    使其总数不超过 `MAX_CONTEXT_RECORDS_MEMORY` 限制。
    此函数应在 `save_context` 内部、提交事务之前调用。

    Args:
        cursor (aiosqlite.Cursor): 当前数据库操作使用的异步游标。
    """
    # 延迟导入配置和常量
    from app.core.database.utils import IS_MEMORY_DB # (新路径)
    from app.config import MAX_CONTEXT_RECORDS_MEMORY # 导入限制配置

    # 仅在内存数据库模式且设置了有效限制时执行
    if not IS_MEMORY_DB or MAX_CONTEXT_RECORDS_MEMORY <= 0:
        return

    try:
        # 1. 获取当前 contexts 表中的记录总数
        await cursor.execute("SELECT COUNT(*) FROM contexts")
        count_row = await cursor.fetchone()
        current_count = count_row[0] if count_row else 0 # 获取当前计数

        # 2. 判断是否超过限制
        if current_count > MAX_CONTEXT_RECORDS_MEMORY:
            # 计算需要删除的记录数量
            num_to_delete = current_count - MAX_CONTEXT_RECORDS_MEMORY
            logger.info(f"内存数据库记录数 ({current_count}) 已超过限制 ({MAX_CONTEXT_RECORDS_MEMORY})，将删除 {num_to_delete} 条最旧的记录...") # 记录日志
            # 3. 执行删除操作
            # 通过查询 `last_used` 时间戳最早的记录的 `rowid` 来确定要删除的行
            # `rowid` 是 SQLite 的内部行标识符
            await cursor.execute(
                """
                DELETE FROM contexts
                WHERE rowid IN (
                    SELECT rowid FROM contexts ORDER BY last_used ASC LIMIT ?
                )
                """,
                (num_to_delete,) # 传递要删除的数量作为参数
            )
            rowcount = cursor.rowcount # 获取实际删除的行数
            logger.info(f"成功删除了 {rowcount} 条最旧的内存上下文记录。") # 记录成功日志
    except aiosqlite.Error as prune_err: # 捕获数据库错误
        # 记录修剪过程中发生的错误，但不影响外部 save_context 的主要流程
        logger.error(f"修剪内存上下文记录时出错: {prune_err}", exc_info=True)

async def _is_context_expired(last_used_str: str, ttl_delta: Optional[timedelta], proxy_key: str) -> bool:
    """
    (内部辅助函数) 检查给定的上次使用时间戳字符串表示的上下文是否已过期。

    Args:
        last_used_str (str): 从数据库读取的 ISO 格式的上次使用时间字符串。
        ttl_delta (Optional[timedelta]): 上下文的生存时间间隔。如果为 None 或 0，表示永不过期。
        proxy_key (str): 相关的代理 Key (用于日志记录)。

    Returns:
        bool: 如果上下文已过期或时间戳解析失败，返回 True；否则返回 False。
    """
    # 如果 TTL 未设置或为 0，则永不过期
    if not ttl_delta:
        return False

    now_utc = datetime.now(timezone.utc) # 获取当前的 UTC 时间
    try:
        # 解析存储在数据库中的 ISO 格式时间字符串，并确保其为 UTC 时区
        # replace(tzinfo=timezone.utc) 假设数据库存储的是 naive UTC 时间戳
        last_used_dt = datetime.fromisoformat(last_used_str).replace(tzinfo=timezone.utc)
        # 判断当前时间与上次使用时间的差是否大于 TTL 间隔
        if now_utc - last_used_dt > ttl_delta:
            logger.info(f"Key {proxy_key[:8]}... 的上下文已超过 TTL ({ttl_delta})，将被视为过期。") # 记录过期日志
            return True # 已过期
        return False # 未过期
    except (ValueError, TypeError) as dt_err: # 捕获时间戳解析错误
         # 如果无法解析存储的时间戳，将其视为已过期以进行清理
         logger.error(f"解析 Key {proxy_key[:8]}... 的 last_used 时间戳 '{last_used_str}' 失败: {dt_err}。视为已过期。") # 记录错误
         return True # 解析失败，视为已过期

async def delete_context_for_key(proxy_key: str) -> bool:
    """
    异步删除指定代理 Key (通常是 user_id) 的所有上下文记录。

    Args:
        proxy_key (str): 要删除上下文的键。

    Returns:
        bool: 如果成功删除（或记录本就不存在）返回 True，否则返回 False。
    """
    if not proxy_key: return False # 如果 key 为空，返回 False
    try:
        # 延迟导入数据库工具函数
        from app.core.database.utils import get_db_connection # (新路径)
        async with get_db_connection() as conn: # 获取异步数据库连接
            async with conn.cursor() as cursor: # 创建异步游标
                # 执行删除操作
                await cursor.execute("DELETE FROM contexts WHERE proxy_key = ?", (proxy_key,))
                rowcount = cursor.rowcount # 获取受影响的行数
                await conn.commit() # 提交事务
            if rowcount > 0: # 如果删除了至少一行
                logger.info(f"上下文已为 Key {proxy_key[:8]}... 删除。") # 记录成功日志
                return True # 返回 True
            else: # 如果没有删除任何行
                logger.warning(f"尝试删除 Key {proxy_key[:8]}... 的上下文，但未找到记录。") # 记录警告
                return True # 也可以认为删除成功（目标状态达成）
    except aiosqlite.Error as e: # 捕获数据库错误
        logger.error(f"删除 Key {proxy_key[:8]}... 的上下文失败: {e}", exc_info=True) # 记录错误日志
        return False # 返回 False 表示失败

async def _deserialize_context_contents(contents_json: str, proxy_key: str) -> Optional[List[Dict[str, Any]]]:
    """
    (内部辅助函数) 异步反序列化存储在数据库中的上下文 JSON 字符串。
    处理可能的 JSON 解析错误，并在出错时尝试删除损坏的数据。

    Args:
        contents_json (str): 从数据库读取的上下文内容的 JSON 字符串。
        proxy_key (str): 相关的代理 Key (用于日志和删除操作)。

    Returns:
        Optional[List[Dict[str, Any]]]: 如果成功反序列化，返回 Python 列表；
                                         如果反序列化失败，返回 None。
    """
    try:
        # 使用 asyncio.to_thread 在线程池中执行 JSON 解析，避免阻塞事件循环
        contents = await asyncio.to_thread(json.loads, contents_json)
        logger.debug(f"上下文 JSON 已为 Key {proxy_key[:8]}... 反序列化。") # 记录调试日志
        # 验证反序列化结果是否为列表 (期望的格式)
        if isinstance(contents, list):
            return contents # 返回列表
        else:
            logger.error(f"反序列化的上下文格式不正确 (期望列表，得到 {type(contents)}) (Key: {proxy_key[:8]}...)")
            # 格式不正确，删除损坏数据
            await delete_context_for_key(proxy_key)
            return None
    except json.JSONDecodeError as e: # 捕获 JSON 解析错误
        logger.error(f"反序列化存储的上下文时失败 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 记录错误
        # 删除损坏的数据，避免下次加载时再次出错
        await delete_context_for_key(proxy_key)
        return None # 返回 None
    except Exception as e: # 捕获其他可能的异常
        logger.error(f"反序列化上下文时发生意外错误 (Key: {proxy_key[:8]}...): {e}", exc_info=True)
        # 尝试删除可能损坏的数据
        await delete_context_for_key(proxy_key)
        return None

async def load_context(proxy_key: str) -> Optional[List[Dict[str, Any]]]:
    """
    异步加载指定代理 Key (通常是 user_id) 的对话上下文。
    会检查上下文的 TTL (生存时间)，如果过期则删除并返回 None。
    如果数据损坏无法解析，也会删除并返回 None。

    Args:
        proxy_key (str): 要加载上下文的键。

    Returns:
        Optional[List[Dict[str, Any]]]: 如果找到有效且未过期的上下文，返回 Gemini 格式的内容列表；
                                         否则返回 None。
    """
    if not proxy_key: return None # 如果 key 为空，返回 None

    # 获取当前的 TTL 设置 (天数)
    ttl_days = await get_ttl_days()
    # 计算 TTL 的 timedelta 对象 (如果 ttl_days > 0)
    ttl_delta = timedelta(days=ttl_days) if ttl_days > 0 else None

    try:
        # 延迟导入数据库工具函数
        from app.core.database.utils import get_db_connection # (新路径)
        async with get_db_connection() as conn: # 获取异步数据库连接
            async with conn.cursor() as cursor: # 创建异步游标
                # 查询指定 key 的上下文内容和最后使用时间
                await cursor.execute("SELECT contents, last_used FROM contexts WHERE proxy_key = ?", (proxy_key,))
                row = await cursor.fetchone() # 获取查询结果

            if not row or not row['contents']: # 如果未找到记录或内容为空
                logger.debug(f"未找到 Key {proxy_key[:8]}... 的上下文。") # 记录调试日志
                return None # 返回 None

            last_used_str = row['last_used'] # 获取最后使用时间字符串
            contents_json = row['contents'] # 获取上下文内容的 JSON 字符串

            # 检查 TTL 是否已过期
            if await _is_context_expired(last_used_str, ttl_delta, proxy_key):
                 # 如果已过期，删除上下文记录并返回 None
                 await delete_context_for_key(proxy_key)
                 return None

            # 如果未过期，反序列化上下文内容
            return await _deserialize_context_contents(contents_json, proxy_key)

    except aiosqlite.Error as e: # 捕获数据库错误
        logger.error(f"为 Key {proxy_key[:8]}... 加载上下文失败: {e}", exc_info=True) # 记录错误日志
        return None # 出错时返回 None
    except Exception as e: # 捕获其他意外错误
        logger.error(f"加载上下文时发生意外错误 (Key: {proxy_key[:8]}...): {e}", exc_info=True)
        return None


async def get_context_info(proxy_key: str) -> Optional[Dict[str, Any]]:
     """
     异步获取指定代理 Key 上下文的元信息（内容长度和最后使用时间）。

     Args:
         proxy_key (str): 要查询的代理 Key。

     Returns:
         Optional[Dict[str, Any]]: 包含 'content_length' 和 'last_used' 的字典，如果未找到记录则返回 None。
     """
     if not proxy_key: return None # 如果 key 为空，返回 None
     try:
         # 延迟导入数据库工具函数
         from app.core.database.utils import get_db_connection # (新路径)
         async with get_db_connection() as conn: # 获取异步数据库连接
             conn.row_factory = aiosqlite.Row # 设置 row_factory 以便按列名访问
             async with conn.cursor() as cursor: # 创建异步游标
                 # 查询内容的长度和最后使用时间
                 await cursor.execute("SELECT length(contents) as content_length, last_used FROM contexts WHERE proxy_key = ?", (proxy_key,))
                 row = await cursor.fetchone() # 获取查询结果
             # 如果找到行，将其转换为字典并返回；否则返回 None
             return dict(row) if row else None
     except aiosqlite.Error as e: # 捕获数据库错误
         logger.error(f"获取 Key {proxy_key[:8]}... 的上下文信息失败: {e}", exc_info=True) # 记录错误日志
         return None # 出错时返回 None

async def list_all_context_keys_info(user_key: Optional[str] = None, is_admin: bool = False) -> List[Dict[str, Any]]:
    """
    异步获取存储的上下文的 Key 和元信息列表。
    根据用户权限（是否为管理员）和提供的用户 Key 进行过滤。

    Args:
        user_key (Optional[str]): 当前请求用户的 Key (通常是 user_id)。默认为 None。
        is_admin (bool): 当前用户是否具有管理员权限。默认为 False。

    Returns:
        List[Dict[str, Any]]: 包含上下文信息的字典列表。每个字典包含 'proxy_key', 'contents' (JSON 字符串),
                              'content_length', 'last_used'。
                              如果无权访问或出错，返回空列表。
    """
    contexts_info = [] # 初始化结果列表
    try:
        # 延迟导入数据库工具函数
        from app.core.database.utils import get_db_connection, DATABASE_PATH # (新路径)
        async with get_db_connection() as conn: # 获取异步数据库连接
            conn.row_factory = aiosqlite.Row # 设置 row_factory 以便按列名访问
            async with conn.cursor() as cursor: # 创建异步游标
                # 构建基础 SQL 查询语句
                sql = "SELECT proxy_key, contents, length(contents) as content_length, last_used FROM contexts"
                params: Tuple = () # 初始化查询参数

                if is_admin: # 如果是管理员，查询所有记录
                    logger.info(f"管理员请求所有上下文信息 (连接 ID: {id(conn)})...") # 记录日志
                    sql += " ORDER BY last_used DESC" # 按最后使用时间降序排序
                elif user_key: # 如果是普通用户且提供了 user_key，只查询该用户的记录
                    logger.info(f"用户 {user_key[:8]}... 请求其上下文信息 (连接 ID: {id(conn)})...") # 记录日志
                    sql += " WHERE proxy_key = ? ORDER BY last_used DESC" # 添加 WHERE 条件
                    params = (user_key,) # 设置查询参数
                else: # 如果既不是管理员，也没提供 user_key
                    logger.warning(f"非管理员尝试列出上下文但未提供 user_key (连接 ID: {id(conn)})。") # 记录警告
                    return [] # 直接返回空列表

                # 执行 SQL 查询
                await cursor.execute(sql, params)
                rows = await cursor.fetchall() # 获取所有结果行

                # 记录获取到的行数 (限制日志输出长度)
                log_key_info = 'admin' if is_admin else (user_key[:8]+'...' if user_key else 'unknown_user')
                raw_rows_str = str(rows)
                max_log_len = 500 # 日志中原始行内容的最大长度
                if len(raw_rows_str) > max_log_len:
                    raw_rows_str = raw_rows_str[:max_log_len] + f"... (truncated, total {len(rows)} rows)"
                logger.debug(f"list_all_context_keys_info: Fetched {len(rows)} rows from DB for {log_key_info}. Raw rows: {raw_rows_str}")

                # 将查询结果行转换为字典列表
                contexts_info = [dict(row) for row in rows]
    except aiosqlite.Error as e: # 捕获数据库错误
        log_prefix = f"管理员" if is_admin else f"用户 {user_key[:8]}..." if user_key else "未知用户" # 构建日志前缀
        logger.error(f"{log_prefix} 列出上下文信息失败 ({DATABASE_PATH}): {e}", exc_info=True) # 记录错误日志
        contexts_info = [] # 出错时清空结果列表
    return contexts_info # 返回上下文信息列表

# --- 上下文格式转换函数 (可能可以移到 converter.py) ---

def convert_openai_to_gemini_contents(history: List[Dict]) -> List[Dict]:
    """
    (辅助函数) 将 OpenAI 格式的对话历史列表转换为 Gemini 的 contents 格式列表。
    主要处理角色映射和将 content 字符串包装在 parts 列表中。

    Args:
        history (List[Dict]): OpenAI 格式的对话历史列表，每个字典包含 'role' 和 'content'。

    Returns:
        List[Dict]: Gemini 格式的 contents 列表，每个字典包含 'role' 和 'parts'。
    """
    gemini_contents = [] # 初始化结果列表
    for message in history: # 遍历输入的 OpenAI 消息
        openai_role = message.get('role') # 获取角色
        openai_content = message.get('content') # 获取内容

        # 确保消息包含有效的角色和内容
        if openai_role and openai_content is not None:
            # --- 角色映射 ---
            if openai_role == 'user':
                gemini_role = 'user'
            elif openai_role == 'assistant':
                gemini_role = 'model'
            elif openai_role == 'system':
                # Gemini v1/v1.5 不直接支持 system 角色在 contents 中，通常映射为 user
                # 或者在 convert_messages 中单独处理为 system_instruction
                gemini_role = 'user' # 将 system 映射为 user
                logger.debug("将 OpenAI 'system' 角色映射为 Gemini 'user' 角色。")
            else:
                logger.warning(f"跳过无效的 OpenAI 历史消息角色: {openai_role}") # 记录无效角色警告
                continue # 跳过此消息

            # --- 内容包装 ---
            # 假设 content 总是字符串，将其包装在 'parts' 列表中
            # TODO: 如果 OpenAI content 可能包含多部分（如图像），需要更复杂的处理逻辑
            if isinstance(openai_content, str):
                gemini_parts = [{'text': openai_content}] # 创建 parts 列表
            else:
                 logger.warning(f"跳过非字符串类型的 OpenAI content: {type(openai_content)}")
                 continue # 跳过非字符串内容

            # 添加到结果列表
            gemini_contents.append({'role': gemini_role, 'parts': gemini_parts})
        else: # 如果消息缺少角色或内容
            logger.warning(f"跳过无效的 OpenAI 历史消息（缺少 role 或 content）: {message}") # 记录无效消息警告

    return gemini_contents # 返回转换后的列表

async def load_context_as_gemini(proxy_key: str) -> Optional[List[Dict[str, Any]]]:
    """
    异步加载指定代理 Key 的上下文，并将其直接转换为 Gemini 的 contents 格式返回。
    处理 TTL 检查和数据反序列化。

    Args:
        proxy_key (str): 要加载上下文的代理 Key (通常是 user_id)。

    Returns:
        Optional[List[Dict[str, Any]]]: Gemini 格式的 contents 列表，如果未找到、过期或加载/转换失败则返回 None。
    """
    # 1. 调用 load_context 加载原始上下文（可能是 OpenAI 格式或其他存储格式）
    # load_context 内部会处理 TTL 检查和反序列化
    loaded_context = await load_context(proxy_key)

    if loaded_context is None: # 如果加载失败或上下文为空/过期
        return None # 直接返回 None

    # 2. 假设 load_context 返回的是 Gemini 格式的列表 (根据 save_context 的逻辑)
    # 如果 load_context 返回的是 OpenAI 格式，则需要调用转换函数
    # if IS_OPENAI_FORMAT_STORAGE: # 假设有一个配置项判断存储格式
    #    conversion_result = convert_messages(loaded_context) # 调用转换函数
    #    if isinstance(conversion_result, list): # 检查转换是否出错
    #        logger.error(f"将加载的上下文从 OpenAI 转换为 Gemini 格式失败: {conversion_result}")
    #        return None
    #    gemini_context, _ = conversion_result # 获取转换后的 Gemini context
    #    return gemini_context
    # else: # 假设存储的就是 Gemini 格式
    #    return loaded_context

    # 当前 save_context 保存的是 Gemini 格式，所以直接返回加载的内容
    # 但需要验证加载的内容是否真的是 List[Dict]
    if isinstance(loaded_context, list):
        # 可以添加更严格的验证，检查列表内元素的结构是否符合 Gemini Content 格式
        return loaded_context
    else:
        logger.error(f"加载的上下文格式不正确 (期望列表，得到 {type(loaded_context)}) (Key: {proxy_key[:8]}...)")
        # 格式错误，删除损坏数据
        await delete_context_for_key(proxy_key)
        return None


def convert_gemini_to_storage_format(request_content: Dict, response_content: Dict) -> List[Dict]:
    """
    (辅助函数) 将 Gemini API 的请求内容 (用户回合) 和响应内容 (模型回合)
    转换为用于数据库存储的格式 (目前使用类似 OpenAI 的格式)。
    主要提取文本内容。

    Args:
        request_content (Dict): Gemini 格式的用户请求内容 (包含 role='user' 和 parts)。
        response_content (Dict): Gemini 格式的模型响应内容 (包含 role='model' 和 parts)。

    Returns:
        List[Dict]: 包含两个字典的列表，分别代表用户回合和模型回合，格式为 {'role': 'user'/'assistant', 'content': 'text'}。
                    如果输入格式无效，可能返回空列表或只包含部分回合。
    """
    storage_format = [] # 初始化存储格式列表

    # --- 处理用户请求内容 ---
    user_role = request_content.get('role') # 获取角色
    user_parts = request_content.get('parts', []) # 获取 parts 列表
    user_text = "" # 初始化文本内容
    # 确保是用户角色且 parts 不为空
    if user_role == 'user' and user_parts:
        # 尝试从第一个 part 提取文本内容
        first_part = user_parts[0]
        if isinstance(first_part, dict) and 'text' in first_part:
            user_text = first_part['text']
        # TODO: 如果用户请求可能包含多部分（如图像），需要决定如何在存储格式中表示
        # 目前只存储第一个文本 part 的内容
        storage_format.append({'role': 'user', 'content': user_text}) # 添加用户回合到列表
    else: # 如果格式无效
        logger.warning(f"转换 Gemini 用户请求内容时发现无效格式或缺少文本: {request_content}") # 记录警告

    # --- 处理模型响应内容 ---
    model_role = response_content.get('role') # 获取角色
    model_parts = response_content.get('parts', []) # 获取 parts 列表
    model_text = "" # 初始化文本内容
    # 确保是模型角色且 parts 不为空
    if model_role == 'model' and model_parts:
        # 尝试从第一个 part 提取文本内容
        first_part = model_parts[0]
        if isinstance(first_part, dict) and 'text' in first_part:
            model_text = first_part['text']
        # TODO: 如果模型响应包含多部分或工具调用，需要决定如何在存储格式中表示
        # 目前只存储第一个文本 part 的内容
        storage_format.append({'role': 'assistant', 'content': model_text}) # 添加模型回合到列表 (使用 'assistant' 角色)
    else: # 如果格式无效
        logger.warning(f"转换 Gemini 模型响应内容时发现无效格式或缺少文本: {response_content}") # 记录警告

    return storage_format # 返回转换后的列表


# --- 内存数据库清理 ---
# 延迟导入 IS_MEMORY_DB
# from app.core.database.utils import IS_MEMORY_DB

async def update_ttl(context_key: str, ttl_seconds: int) -> Optional[bool]:
    """
    (可能需要审查) 异步更新指定上下文记录的 TTL。
    实际上是通过将 `last_used` 时间戳更新为当前时间来实现“刷新”TTL。

    Args:
        context_key (str): 要更新 TTL 的上下文键 (通常是 user_id)。
        ttl_seconds (int): 新的 TTL 秒数 (此参数当前未使用，因为只是更新时间戳)。

    Returns:
        Optional[bool]: 如果成功更新时间戳返回 True，如果记录未找到返回 False，如果发生错误返回 None。
    """
    if not context_key: return False # 如果 key 为空，返回 False
    try:
        # 延迟导入数据库连接函数
        from app.core.database.utils import get_db_connection # (新路径)
        async with get_db_connection() as conn: # 获取异步连接
            async with conn.cursor() as cursor: # 创建异步游标
                # 获取当前 UTC 时间的 ISO 格式字符串
                now_utc_iso = datetime.now(timezone.utc).isoformat()
                # 执行 UPDATE 语句，将指定 key 的 last_used 更新为当前时间
                await cursor.execute("UPDATE contexts SET last_used = ? WHERE proxy_key = ?", (now_utc_iso, context_key))
                rowcount = cursor.rowcount # 获取受影响的行数
                await conn.commit() # 提交事务
            if rowcount > 0: # 如果更新了至少一行
                logger.info(f"成功更新了 Key {context_key[:8]}... 的 last_used 时间戳。") # 记录成功日志
                return True # 返回 True
            else: # 如果没有行被更新 (记录不存在)
                logger.warning(f"尝试更新 Key {context_key[:8]}... 的 last_used 时间戳，但未找到记录。") # 记录警告
                return False # 返回 False
    except aiosqlite.Error as e: # 捕获数据库错误
        logger.error(f"更新 Key {context_key[:8]}... 的 last_used 时间戳失败: {e}", exc_info=True) # 记录错误日志
        return None # 返回 None 表示出错

async def update_global_ttl(ttl_days: int) -> bool: # 参数名修改为 ttl_days
    """
    异步更新全局上下文 TTL 的天数设置。

    Args:
        ttl_days (int): 新的全局 TTL 天数 (非负整数)。

    Returns:
        bool: 如果成功更新设置返回 True，否则返回 False。
    """
    # 延迟导入数据库设置函数
    from app.core.database.settings import set_ttl_days # (新路径)
    try:
        # 调用 set_ttl_days 函数来验证并保存设置
        await set_ttl_days(ttl_days) # set_ttl_days 内部会处理验证和转换
        logger.info(f"全局上下文 TTL 已更新为 {ttl_days} 天。") # 记录成功日志
        return True # 返回 True
    except ValueError as ve: # 捕获 set_ttl_days 可能抛出的 ValueError (如果输入无效)
        logger.error(f"更新全局上下文 TTL 失败: {ve}") # 记录错误
        return False # 返回 False
    except Exception as e: # 捕获其他可能的异常
        logger.error(f"更新全局上下文 TTL 时发生意外错误: {e}", exc_info=True) # 记录错误
        return False # 返回 False

async def get_all_contexts_with_ttl() -> Dict[str, Dict[str, Any]]:
    """
    异步获取所有存储的上下文记录及其元信息，包括计算出的剩余 TTL 和内容摘要。

    Returns:
        Dict[str, Dict[str, Any]]: 一个字典，键是 proxy_key (user_id)，值是包含以下信息的字典：
            - 'ttl' (str): 剩余 TTL 的可读字符串 ("x天 y小时", "已过期", "永不", "N/A")。
            - 'last_accessed' (str): 最后访问时间的格式化字符串 ("YYYY-MM-DD HH:MM:SS") 或 "N/A"。
            - 'context_summary' (str): 上下文内容的摘要 (通常是第一条消息的前 100 个字符) 或 "N/A"。
    """
    all_contexts_data = {} # 初始化结果字典
    try:
        # 延迟导入数据库工具和设置函数
        from app.core.database.utils import get_db_connection # (新路径)
        from app.core.database.settings import get_ttl_days # (新路径)

        # 获取全局 TTL 设置 (天数)
        global_ttl_days = await get_ttl_days()
        # 计算全局 TTL 的秒数 (如果 TTL > 0)
        global_ttl_seconds = global_ttl_days * 24 * 60 * 60 if global_ttl_days > 0 else 0

        async with get_db_connection() as conn: # 获取异步数据库连接
            conn.row_factory = aiosqlite.Row # 设置 row_factory 以便按列名访问
            async with conn.cursor() as cursor: # 创建异步游标
                # 查询所有上下文记录，按最后使用时间降序排序
                await cursor.execute("SELECT proxy_key, contents, last_used FROM contexts ORDER BY last_used DESC")
                rows = await cursor.fetchall() # 获取所有行

            # 遍历查询结果
            for row in rows:
                proxy_key = row['proxy_key'] # 获取 proxy_key
                contents_json = row['contents'] # 获取上下文内容的 JSON 字符串
                last_used_str = row['last_used'] # 获取最后使用时间的 ISO 格式字符串

                # --- 生成内容摘要 ---
                context_summary = "N/A" # 初始化摘要为 "N/A"
                if contents_json: # 如果内容不为空
                    try:
                        # 在线程中反序列化 JSON
                        contents_list = await asyncio.to_thread(json.loads, contents_json)
                        # 检查反序列化结果是否为非空列表
                        if contents_list and isinstance(contents_list, list) and len(contents_list) > 0:
                            # 尝试从第一条消息提取文本内容作为摘要
                            first_message = contents_list[0]
                            if isinstance(first_message, dict) and 'content' in first_message: # 处理 OpenAI 格式
                                content_text = str(first_message['content'])
                                context_summary = content_text[:100] + "..." if len(content_text) > 100 else content_text
                            elif isinstance(first_message, dict) and 'parts' in first_message and isinstance(first_message['parts'], list) and len(first_message['parts']) > 0: # 处理 Gemini 格式
                                first_part = first_message['parts'][0]
                                if isinstance(first_part, dict) and 'text' in first_part:
                                    content_text = str(first_part['text'])
                                    context_summary = content_text[:100] + "..." if len(content_text) > 100 else content_text
                    except json.JSONDecodeError: # 捕获 JSON 解析错误
                        logger.warning(f"无法解析 Key {proxy_key[:8]}... 的上下文内容 JSON。") # 记录警告
                    except Exception as e: # 捕获其他提取摘要时的错误
                        logger.warning(f"提取 Key {proxy_key[:8]}... 的上下文摘要时出错: {e}") # 记录警告

                # --- 计算剩余 TTL ---
                ttl_remaining_str = "N/A" # 初始化剩余 TTL 字符串为 "N/A"
                if last_used_str and global_ttl_seconds > 0: # 仅在有上次使用时间且 TTL > 0 时计算
                    try:
                        # 解析 ISO 格式时间字符串，并确保为 UTC 时区
                        last_used_dt = datetime.fromisoformat(last_used_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
                        # 计算过期时间点
                        expiry_time = last_used_dt + timedelta(seconds=global_ttl_seconds)
                        now_utc = datetime.now(timezone.utc) # 获取当前 UTC 时间
                        # 计算剩余时间差
                        remaining_delta = expiry_time - now_utc
                        if remaining_delta.total_seconds() > 0: # 如果尚未过期
                            # 将剩余时间格式化为可读字符串
                            days = remaining_delta.days
                            hours, remainder = divmod(remaining_delta.seconds, 3600)
                            minutes, seconds = divmod(remainder, 60)
                            if days > 0:
                                ttl_remaining_str = f"{days}天 {hours}小时"
                            elif hours > 0:
                                ttl_remaining_str = f"{hours}小时 {minutes}分钟"
                            elif minutes > 0:
                                ttl_remaining_str = f"{minutes}分钟 {seconds}秒"
                            else:
                                ttl_remaining_str = f"{seconds}秒"
                        else: # 如果已过期
                            ttl_remaining_str = "已过期"
                    except ValueError: # 捕获时间戳解析错误
                        logger.warning(f"无法解析 Key {proxy_key[:8]}... 的 last_used 时间戳: {last_used_str}") # 记录警告
                elif global_ttl_seconds <= 0: # 如果 TTL 设置为 0 或负数
                    ttl_remaining_str = "永不" # 表示永不过期

                # --- 存储结果 ---
                all_contexts_data[proxy_key] = {
                    "ttl": ttl_remaining_str, # 剩余 TTL 字符串
                    # 格式化最后访问时间为 "YYYY-MM-DD HH:MM:SS"
                    "last_accessed": last_used_str.split('.')[0].replace('T', ' ') if last_used_str else "N/A",
                    "context_summary": context_summary # 内容摘要
                }
        logger.info(f"成功获取了 {len(all_contexts_data)} 条上下文记录及其 TTL 信息。") # 记录成功日志

    except aiosqlite.Error as e: # 捕获数据库错误
        logger.error(f"获取所有上下文及其 TTL 信息失败: {e}", exc_info=True) # 记录错误
    except Exception as e: # 捕获其他意外错误
        logger.error(f"处理所有上下文数据时发生意外错误: {e}", exc_info=True) # 记录错误

    return all_contexts_data # 返回结果字典

# 导入配置模块以访问 CONTEXT_STORAGE_MODE
from app import config as app_config

class ContextStore:
    """
    管理对话上下文的存储和检索。
    支持内存和数据库两种存储模式。
    """
    def __init__(self, storage_mode: str = app_config.CONTEXT_STORAGE_MODE, db_path: str = app_config.CONTEXT_DB_PATH):
        """
        初始化 ContextStore。

        Args:
            storage_mode (str): 'memory' 或 'database'。
            db_path (str): 数据库文件路径 (仅在 database 模式下使用)。
        """
        self.storage_mode = storage_mode
        self.db_path = db_path # 虽然旧函数可能使用，但新方法应通过 db session
        if self.storage_mode == "memory":
            self.memory_store: Dict[str, Dict[str, Any]] = {} # 存储结构: {context_key: {"content": ..., "expires_at": ..., "last_used": ...}}
            self.memory_lock = asyncio.Lock() # 用于保护内存存储的异步锁
            logger.info("上下文存储已初始化为内存模式。")
        elif self.storage_mode == "database":
            # 数据库模式的初始化在 get_db_session 和 init_db 中处理
            logger.info(f"上下文存储已初始化为数据库模式 (路径: {self.db_path})。")
        else:
            raise ValueError(f"未知的上下文存储模式: {storage_mode}")

    async def perform_memory_cleanup(self):
        """
        (仅内存模式) 清理内存中存储的过期上下文条目。
        """
        if self.storage_mode != "memory":
            return

        async with self.memory_lock:
            now_iso = datetime.now(timezone.utc).isoformat()
            keys_to_delete = []
            for key, data in self.memory_store.items():
                expires_at = data.get("expires_at")
                if expires_at and expires_at < now_iso:
                    keys_to_delete.append(key)
            
            for key in keys_to_delete:
                del self.memory_store[key]
                logger.info(f"内存中的上下文 Key '{key}' 已过期并被清理。")
            
            if keys_to_delete:
                logger.info(f"内存上下文清理完成，移除了 {len(keys_to_delete)} 个过期条目。")
            else:
                logger.debug("内存上下文清理完成，没有找到需要删除的过期条目。")

            # 检查是否超出最大记录数限制 (如果定义了 MAX_CONTEXT_RECORDS_MEMORY)
            if MAX_CONTEXT_RECORDS_MEMORY > 0 and len(self.memory_store) > MAX_CONTEXT_RECORDS_MEMORY:
                num_to_prune = len(self.memory_store) - MAX_CONTEXT_RECORDS_MEMORY
                # 按 last_used 排序，旧的在前
                sorted_keys = sorted(self.memory_store.items(), key=lambda item: item[1].get('last_used', ''))
                keys_to_prune = [item[0] for item in sorted_keys[:num_to_prune]]
                for key in keys_to_prune:
                    del self.memory_store[key]
                logger.info(f"内存上下文存储超出最大记录数限制，已清理 {len(keys_to_prune)} 条最旧的记录。")


    async def store_context(self, user_id: str, context_key: str, context_value: Any, ttl_seconds: Optional[int] = None):
        """
        存储上下文信息。

        Args:
            user_id (str): 用户标识。
            context_key (str): 上下文的唯一键。
            context_value (Any): 要存储的上下文内容 (通常是 Gemini contents 列表)。
            ttl_seconds (Optional[int]): 此上下文的 TTL (秒)。如果为 None，则使用全局 TTL。
        """
        if not context_key or context_value is None: # 允许空列表作为有效上下文
            logger.warning(f"尝试为 Key {context_key[:8]}... 保存空的上下文或内容，已跳过。")
            return

        now = datetime.now(timezone.utc)
        last_used_iso = now.isoformat()

        # 确定此上下文的 TTL
        final_ttl_seconds: Optional[int]
        if ttl_seconds is not None: # 如果请求中指定了 TTL
            final_ttl_seconds = ttl_seconds
        else: # 否则，使用全局 TTL
            global_ttl_days = await get_ttl_days() # 从数据库获取全局 TTL (天)
            final_ttl_seconds = global_ttl_days * 24 * 60 * 60 if global_ttl_days > 0 else None

        expires_at_iso: Optional[str] = None
        if final_ttl_seconds is not None and final_ttl_seconds > 0:
            expires_at_iso = (now + timedelta(seconds=final_ttl_seconds)).isoformat()

        if self.storage_mode == "memory":
            async with self.memory_lock:
                self.memory_store[context_key] = {
                    "user_id": user_id, # 存储 user_id
                    "content": context_value, # 直接存储 Python 对象
                    "last_used": last_used_iso,
                    "expires_at": expires_at_iso,
                    "created_at": now.isoformat() # 添加创建时间
                }
                logger.info(f"上下文已为 Key {context_key[:8]}... 存储到内存。")
                # 可以在这里触发一次清理，如果记录数可能超限
                if MAX_CONTEXT_RECORDS_MEMORY > 0 and len(self.memory_store) > MAX_CONTEXT_RECORDS_MEMORY:
                    # 按 last_used 排序，旧的在前
                    sorted_keys = sorted(self.memory_store.items(), key=lambda item: item[1].get('last_used', ''))
                    keys_to_prune = [item[0] for item in sorted_keys[:len(self.memory_store) - MAX_CONTEXT_RECORDS_MEMORY]]
                    for key_to_prune in keys_to_prune:
                        del self.memory_store[key_to_prune]
                    logger.info(f"内存上下文存储超出最大记录数限制，已清理 {len(keys_to_prune)} 条最旧的记录。")

        elif self.storage_mode == "database":
            try:
                contents_json = await asyncio.to_thread(json.dumps, context_value, ensure_ascii=False)
                from app.core.database.utils import get_db_session # 导入异步会话依赖
                async for session in get_db_session(): # 获取异步会话
                    async with session.begin(): # 开始事务
                        # 使用 SQLAlchemy ORM (假设模型已定义)
                        from app.core.database.models import CachedContent # 导入模型
                        # 尝试获取现有记录
                        stmt = select(CachedContent).filter_by(user_id=user_id, content_id=context_key)
                        result = await session.execute(stmt)
                        existing_record = result.scalar_one_or_none()

                        if existing_record:
                            existing_record.content = contents_json
                            existing_record.last_used_timestamp = now # 使用 datetime 对象
                            existing_record.expiration_timestamp = datetime.fromisoformat(expires_at_iso) if expires_at_iso else None
                        else:
                            new_record = CachedContent(
                                user_id=user_id,
                                content_id=context_key,
                                content=contents_json,
                                creation_timestamp=now, # 使用 datetime 对象
                                last_used_timestamp=now, # 使用 datetime 对象
                                expiration_timestamp=datetime.fromisoformat(expires_at_iso) if expires_at_iso else None
                            )
                            session.add(new_record)
                        await session.commit() # 提交事务
                        logger.info(f"上下文已为 Key {context_key[:8]}... (用户 {user_id[:8]}...) 保存/更新到数据库。")
                        break # 成功后退出循环
            except Exception as e:
                logger.error(f"为 Key {context_key[:8]}... 保存上下文到数据库失败: {e}", exc_info=True)
        else:
            logger.error(f"未知的存储模式 '{self.storage_mode}'，无法存储上下文。")


    async def retrieve_context(self, user_id: str, context_key: str) -> Optional[Any]:
        """
        检索上下文信息。

        Args:
            user_id (str): 用户标识。
            context_key (str): 上下文的唯一键。

        Returns:
            Optional[Any]: 存储的上下文内容，如果未找到或已过期则返回 None。
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        if self.storage_mode == "memory":
            async with self.memory_lock:
                data = self.memory_store.get(context_key)
                if data:
                    # 检查 user_id 是否匹配 (如果需要更严格的隔离)
                    # if data.get("user_id") != user_id:
                    #     logger.warning(f"用户 {user_id[:8]}... 尝试访问不属于自己的内存上下文 Key '{context_key}'。")
                    #     return None

                    if data.get("expires_at") and data["expires_at"] < now_iso:
                        logger.info(f"内存中的上下文 Key '{context_key}' 已过期，将被删除。")
                        del self.memory_store[context_key]
                        return None
                    data["last_used"] = now_iso # 更新最后使用时间
                    return data.get("content")
                return None
        elif self.storage_mode == "database":
            try:
                from app.core.database.utils import get_db_session
                from app.core.database.models import CachedContent
                async for session in get_db_session():
                    async with session.begin():
                        stmt = select(CachedContent).filter_by(user_id=user_id, content_id=context_key)
                        result = await session.execute(stmt)
                        record = result.scalar_one_or_none()

                        if record:
                            if record.expiration_timestamp and record.expiration_timestamp < datetime.now(timezone.utc):
                                logger.info(f"数据库中的上下文 Key '{context_key}' (用户 {user_id[:8]}...) 已过期，将被删除。")
                                await session.delete(record)
                                await session.commit()
                                return None
                            
                            record.last_used_timestamp = datetime.now(timezone.utc) # 更新最后使用时间
                            await session.commit()
                            try:
                                return await asyncio.to_thread(json.loads, record.content)
                            except json.JSONDecodeError:
                                logger.error(f"反序列化数据库中 Key '{context_key}' 的上下文失败。数据已损坏。")
                                await session.delete(record) # 删除损坏数据
                                await session.commit()
                                return None
                        return None
            except Exception as e:
                logger.error(f"从数据库检索 Key '{context_key}' 的上下文失败: {e}", exc_info=True)
                return None
        else:
            logger.error(f"未知的存储模式 '{self.storage_mode}'，无法检索上下文。")
            return None

    async def delete_context(self, user_id: str, context_key: str) -> bool:
        """
        删除指定的上下文。

        Args:
            user_id (str): 用户标识。
            context_key (str): 要删除的上下文的键。

        Returns:
            bool: 如果成功删除或记录本就不存在则返回 True，否则返回 False。
        """
        if self.storage_mode == "memory":
            async with self.memory_lock:
                if context_key in self.memory_store:
                    # 检查 user_id 是否匹配 (如果需要)
                    # if self.memory_store[context_key].get("user_id") != user_id:
                    #     logger.warning(f"用户 {user_id[:8]}... 尝试删除不属于自己的内存上下文 Key '{context_key}'。")
                    #     return False
                    del self.memory_store[context_key]
                    logger.info(f"内存中的上下文 Key '{context_key}' 已被用户 {user_id[:8]}... 删除。")
                    return True
                return False # Key 不存在
        elif self.storage_mode == "database":
            try:
                from app.core.database.utils import get_db_session
                from app.core.database.models import CachedContent
                async for session in get_db_session():
                    async with session.begin():
                        stmt = delete(CachedContent).where(CachedContent.user_id == user_id, CachedContent.content_id == context_key)
                        result = await session.execute(stmt)
                        await session.commit()
                        if result.rowcount > 0:
                            logger.info(f"数据库中的上下文 Key '{context_key}' (用户 {user_id[:8]}...) 已被删除。")
                            return True
                        logger.info(f"尝试删除数据库上下文 Key '{context_key}' (用户 {user_id[:8]}...)，但未找到记录。")
                        return False # Key 不存在或不属于该用户
            except Exception as e:
                logger.error(f"从数据库删除 Key '{context_key}' 的上下文失败: {e}", exc_info=True)
                return False
        else:
            logger.error(f"未知的存储模式 '{self.storage_mode}'，无法删除上下文。")
            return False

    async def get_context_info_for_management(self, user_id: Optional[str] = None, is_admin: bool = False) -> List[Dict[str, Any]]:
        """
        获取用于管理界面的上下文信息列表。
        """
        contexts_info = []
        now_utc = datetime.now(timezone.utc)
        global_ttl_days = await get_ttl_days()
        global_ttl_delta = timedelta(days=global_ttl_days) if global_ttl_days > 0 else None

        if self.storage_mode == "memory":
            async with self.memory_lock:
                for key, data in self.memory_store.items():
                    if not is_admin and data.get("user_id") != user_id:
                        continue # 非管理员只能看到自己的

                    summary = "N/A"
                    if data.get("content"):
                        try:
                            first_message_content = ""
                            if isinstance(data["content"], list) and data["content"]:
                                first_message = data["content"][0]
                                if isinstance(first_message, dict) and 'parts' in first_message and first_message['parts']:
                                    first_part = first_message['parts'][0]
                                    if isinstance(first_part, dict) and 'text' in first_part:
                                        first_message_content = str(first_part['text'])
                                elif isinstance(first_message, dict) and 'content' in first_message: # 兼容旧格式
                                     first_message_content = str(first_message['content'])
                            summary = first_message_content[:100] + "..." if len(first_message_content) > 100 else first_message_content
                        except Exception:
                            pass
                    
                    last_used_dt = datetime.fromisoformat(data["last_used"].replace('Z', '+00:00')) if data.get("last_used") else now_utc
                    expires_at_dt = datetime.fromisoformat(data["expires_at"].replace('Z', '+00:00')) if data.get("expires_at") else None
                    
                    ttl_str = "永不"
                    if expires_at_dt:
                        if expires_at_dt < now_utc:
                            ttl_str = "已过期"
                        else:
                            remaining_delta = expires_at_dt - now_utc
                            days = remaining_delta.days
                            hours, remainder = divmod(remaining_delta.seconds, 3600)
                            minutes, _ = divmod(remainder, 60)
                            if days > 0: ttl_str = f"{days}天{hours}小时"
                            elif hours > 0: ttl_str = f"{hours}小时{minutes}分钟"
                            else: ttl_str = f"{minutes}分钟"
                    elif global_ttl_delta : # 如果单条记录没有expires_at，但有全局TTL
                        effective_expiry = last_used_dt + global_ttl_delta
                        if effective_expiry < now_utc:
                            ttl_str = "已过期 (全局TTL)"
                        else:
                            remaining_delta = effective_expiry - now_utc
                            days = remaining_delta.days
                            hours, remainder = divmod(remaining_delta.seconds, 3600)
                            minutes, _ = divmod(remainder, 60)
                            if days > 0: ttl_str = f"{days}天{hours}小时 (全局TTL)"
                            elif hours > 0: ttl_str = f"{hours}小时{minutes}分钟 (全局TTL)"
                            else: ttl_str = f"{minutes}分钟 (全局TTL)"


                    contexts_info.append({
                        "context_key": key, # 使用内存中的 key 作为 context_key
                        "user_id": data.get("user_id", "N/A"),
                        "created_at": data.get("created_at", "N/A"), # 已是 ISO 格式
                        "last_accessed_at": data.get("last_used", "N/A"), # 已是 ISO 格式
                        "ttl_seconds": (expires_at_dt - datetime.fromisoformat(data["created_at"])).total_seconds() if expires_at_dt and data.get("created_at") else "N/A",
                        "context_value_summary": summary,
                        "ttl_display": ttl_str,
                        "id": key # 对于内存模式，用 key 作为 id
                    })
            # 按创建时间排序 (新的在前)
            contexts_info.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        elif self.storage_mode == "database":
            try:
                from app.core.database.utils import get_db_session
                from app.core.database.models import CachedContent
                async for session in get_db_session():
                    async with session.begin():
                        stmt = select(CachedContent)
                        if not is_admin and user_id:
                            stmt = stmt.filter_by(user_id=user_id)
                        stmt = stmt.order_by(CachedContent.last_used_timestamp.desc())
                        
                        result = await session.execute(stmt)
                        records = result.scalars().all()

                        for record in records:
                            summary = "N/A"
                            if record.content:
                                try:
                                    content_list = await asyncio.to_thread(json.loads, record.content)
                                    if content_list and isinstance(content_list, list) and content_list:
                                        first_message = content_list[0]
                                        if isinstance(first_message, dict) and 'parts' in first_message and first_message['parts']:
                                            first_part = first_message['parts'][0]
                                            if isinstance(first_part, dict) and 'text' in first_part:
                                                summary = str(first_part['text'])[:100] + "..." if len(str(first_part['text'])) > 100 else str(first_part['text'])
                                        elif isinstance(first_message, dict) and 'content' in first_message: # 兼容旧格式
                                            summary = str(first_message['content'])[:100] + "..." if len(str(first_message['content'])) > 100 else str(first_message['content'])
                                except Exception:
                                    pass
                            
                            ttl_str = "永不"
                            if record.expiration_timestamp:
                                if record.expiration_timestamp < now_utc:
                                    ttl_str = "已过期"
                                else:
                                    remaining_delta = record.expiration_timestamp - now_utc
                                    days, rem_secs = divmod(remaining_delta.total_seconds(), 86400)
                                    hours, rem_secs = divmod(rem_secs, 3600)
                                    minutes, _ = divmod(rem_secs, 60)
                                    if days > 0: ttl_str = f"{int(days)}天{int(hours)}小时"
                                    elif hours > 0: ttl_str = f"{int(hours)}小时{int(minutes)}分钟"
                                    else: ttl_str = f"{int(minutes)}分钟"
                            elif global_ttl_delta and record.last_used_timestamp : # 如果单条记录没有expires_at，但有全局TTL
                                effective_expiry = record.last_used_timestamp + global_ttl_delta
                                if effective_expiry < now_utc:
                                    ttl_str = "已过期 (全局TTL)"
                                else:
                                    remaining_delta = effective_expiry - now_utc
                                    days, rem_secs = divmod(remaining_delta.total_seconds(), 86400)
                                    hours, rem_secs = divmod(rem_secs, 3600)
                                    minutes, _ = divmod(rem_secs, 60)
                                    if days > 0: ttl_str = f"{int(days)}天{int(hours)}小时 (全局TTL)"
                                    elif hours > 0: ttl_str = f"{int(hours)}小时{int(minutes)}分钟 (全局TTL)"
                                    else: ttl_str = f"{int(minutes)}分钟 (全局TTL)"


                            contexts_info.append({
                                "id": record.id,
                                "user_id": record.user_id,
                                "context_key": record.content_id,
                                "created_at": record.creation_timestamp.isoformat() if record.creation_timestamp else "N/A",
                                "last_accessed_at": record.last_used_timestamp.isoformat() if record.last_used_timestamp else "N/A",
                                "ttl_seconds": (record.expiration_timestamp - record.creation_timestamp).total_seconds() if record.expiration_timestamp and record.creation_timestamp else "N/A",
                                "context_value_summary": summary,
                                "ttl_display": ttl_str
                            })
                        break # 成功后退出循环
            except Exception as e:
                logger.error(f"获取数据库上下文信息失败: {e}", exc_info=True)
        
        return contexts_info

    async def delete_context_by_id(self, context_id: int, user_id: Optional[str] = None, is_admin: bool = False) -> bool:
        """
        通过数据库 ID 删除上下文条目。
        如果不是管理员，则会校验 user_id。
        """
        if self.storage_mode == "memory":
            # 内存模式下，我们通常通过 context_key (即 id) 删除
            async with self.memory_lock:
                key_to_delete = str(context_id) # 假设 id 就是 context_key
                if key_to_delete in self.memory_store:
                    if not is_admin and self.memory_store[key_to_delete].get("user_id") != user_id:
                        logger.warning(f"用户 {user_id} 尝试删除不属于自己的内存上下文 ID {key_to_delete}")
                        return False
                    del self.memory_store[key_to_delete]
                    logger.info(f"内存上下文 ID '{key_to_delete}' 已被删除。")
                    return True
                return False
        elif self.storage_mode == "database":
            try:
                from app.core.database.utils import get_db_session
                from app.core.database.models import CachedContent
                async for session in get_db_session():
                    async with session.begin():
                        stmt = select(CachedContent).filter_by(id=context_id)
                        if not is_admin and user_id:
                            stmt = stmt.filter_by(user_id=user_id)
                        
                        result = await session.execute(stmt)
                        record_to_delete = result.scalar_one_or_none()

                        if record_to_delete:
                            await session.delete(record_to_delete)
                            await session.commit()
                            logger.info(f"数据库上下文 ID '{context_id}' 已被删除。")
                            return True
                        logger.warning(f"尝试删除数据库上下文 ID '{context_id}'，但未找到或权限不足。")
                        return False
            except Exception as e:
                logger.error(f"通过 ID 删除数据库上下文失败: {e}", exc_info=True)
                return False
        return False

# 旧的 cleanup_memory_context 函数，将被 ContextStore.perform_memory_cleanup 替代
# async def cleanup_memory_context(max_age_seconds: int):
#     """
#     异步清理内存数据库中超过指定时间的旧上下文记录。
#     仅在 IS_MEMORY_DB 为 True 时执行。
# 
#     Args:
#         max_age_seconds (int): 上下文记录的最大保留时间（秒）。小于等于 0 表示不清理。
#     """
#     # 延迟导入 IS_MEMORY_DB
#     from app.core.database.utils import IS_MEMORY_DB # (新路径)
#     if not IS_MEMORY_DB: # 如果不是内存数据库模式，则不执行
#         return
# 
#     if max_age_seconds <= 0: # 如果清理间隔无效
#         logger.warning("内存上下文清理间隔无效 (<= 0)，跳过清理。") # 记录警告
#         return
# 
#     # 计算截止时间点 (当前 UTC 时间减去最大保留时间)
#     cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
#     # 将截止时间格式化为 ISO 格式字符串，用于 SQL 查询比较
#     cutoff_time_iso = cutoff_time.isoformat()
# 
#     try:
#         # 延迟导入数据库连接函数
#         from app.core.database.utils import get_db_connection # (新路径)
#         async with get_db_connection() as conn: # 获取异步数据库连接
#             async with conn.cursor() as cursor: # 创建异步游标
#                 # 执行 SQL 删除语句，删除 last_used 早于截止时间的记录
#                 # !!! 注意：这里的表名是 'contexts'，与 SQLAlchemy 模型 'cached_contents' 不一致 !!!
#                 # !!! 这可能是导致 "no such table: contexts" 错误的原因 !!!
#                 await cursor.execute("DELETE FROM contexts WHERE last_used < ?", (cutoff_time_iso,))
#                 rowcount = cursor.rowcount # 获取删除的行数
#                 await conn.commit() # 提交事务
#             if rowcount > 0: # 如果删除了记录
#                 logger.info(f"成功清理了 {rowcount} 条超过 {max_age_seconds} 秒的内存上下文记录。") # 记录成功日志
#             else: # 如果没有删除记录
#                 logger.debug("内存上下文清理完成，没有找到需要删除的记录。") # 记录调试日志
#     except aiosqlite.Error as e: # 捕获数据库错误
#         logger.error(f"清理内存上下文记录失败: {e}", exc_info=True) # 记录错误日志

async def update_ttl(context_key: str, ttl_seconds: int) -> Optional[bool]:
    """
    (可能需要审查) 异步更新指定上下文记录的 TTL。
    实际上是通过将 `last_used` 时间戳更新为当前时间来实现“刷新”TTL。

    Args:
        context_key (str): 要更新 TTL 的上下文键 (通常是 user_id)。
        ttl_seconds (int): 新的 TTL 秒数 (此参数当前未使用，因为只是更新时间戳)。

    Returns:
        Optional[bool]: 如果成功更新时间戳返回 True，如果记录未找到返回 False，如果发生错误返回 None。
    """
    if not context_key: return False # 如果 key 为空，返回 False
    try:
        # 延迟导入数据库连接函数
        from app.core.database.utils import get_db_connection # (新路径)
        async with get_db_connection() as conn: # 获取异步连接
            async with conn.cursor() as cursor: # 创建异步游标
                # 获取当前 UTC 时间的 ISO 格式字符串
                now_utc_iso = datetime.now(timezone.utc).isoformat()
                # 执行 UPDATE 语句，将指定 key 的 last_used 更新为当前时间
                # !!! 注意：这里的表名是 'contexts'，与 SQLAlchemy 模型 'cached_contents' 不一致 !!!
                await cursor.execute("UPDATE contexts SET last_used = ? WHERE proxy_key = ?", (now_utc_iso, context_key))
                rowcount = cursor.rowcount # 获取受影响的行数
                await conn.commit() # 提交事务
            if rowcount > 0: # 如果更新了至少一行
                logger.info(f"成功更新了 Key {context_key[:8]}... 的 last_used 时间戳。") # 记录成功日志
                return True # 返回 True
            else: # 如果没有行被更新 (记录不存在)
                logger.warning(f"尝试更新 Key {context_key[:8]}... 的 last_used 时间戳，但未找到记录。") # 记录警告
                return False # 返回 False
    except aiosqlite.Error as e: # 捕获数据库错误
        logger.error(f"更新 Key {context_key[:8]}... 的 last_used 时间戳失败: {e}", exc_info=True) # 记录错误日志
        return None # 返回 None 表示出错

async def update_global_ttl(ttl_days: int) -> bool: # 参数名修改为 ttl_days
    """
    异步更新全局上下文 TTL 的天数设置。

    Args:
        ttl_days (int): 新的全局 TTL 天数 (非负整数)。

    Returns:
        bool: 如果成功更新设置返回 True，否则返回 False。
    """
    # 延迟导入数据库设置函数
    from app.core.database.settings import set_ttl_days # (新路径)
    try:
        # 调用 set_ttl_days 函数来验证并保存设置
        await set_ttl_days(ttl_days) # set_ttl_days 内部会处理验证和转换
        logger.info(f"全局上下文 TTL 已更新为 {ttl_days} 天。") # 记录成功日志
        return True # 返回 True
    except ValueError as ve: # 捕获 set_ttl_days 可能抛出的 ValueError (如果输入无效)
        logger.error(f"更新全局上下文 TTL 失败: {ve}") # 记录错误
        return False # 返回 False
    except Exception as e: # 捕获其他可能的异常
        logger.error(f"更新全局上下文 TTL 时发生意外错误: {e}", exc_info=True) # 记录错误
        return False # 返回 False

async def get_all_contexts_with_ttl() -> Dict[str, Dict[str, Any]]:
    """
    异步获取所有存储的上下文记录及其元信息，包括计算出的剩余 TTL 和内容摘要。

    Returns:
        Dict[str, Dict[str, Any]]: 一个字典，键是 proxy_key (user_id)，值是包含以下信息的字典：
            - 'ttl' (str): 剩余 TTL 的可读字符串 ("x天 y小时", "已过期", "永不", "N/A")。
            - 'last_accessed' (str): 最后访问时间的格式化字符串 ("YYYY-MM-DD HH:MM:SS") 或 "N/A"。
            - 'context_summary' (str): 上下文内容的摘要 (通常是第一条消息的前 100 个字符) 或 "N/A"。
    """
    all_contexts_data = {} # 初始化结果字典
    try:
        # 延迟导入数据库工具和设置函数
        from app.core.database.utils import get_db_connection # (新路径)
        from app.core.database.settings import get_ttl_days # (新路径)

        # 获取全局 TTL 设置 (天数)
        global_ttl_days = await get_ttl_days()
        # 计算全局 TTL 的秒数 (如果 TTL > 0)
        global_ttl_seconds = global_ttl_days * 24 * 60 * 60 if global_ttl_days > 0 else 0

        async with get_db_connection() as conn: # 获取异步数据库连接
            conn.row_factory = aiosqlite.Row # 设置 row_factory 以便按列名访问
            async with conn.cursor() as cursor: # 创建异步游标
                # 查询所有上下文记录，按最后使用时间降序排序
                # !!! 注意：这里的表名是 'contexts'，与 SQLAlchemy 模型 'cached_contents' 不一致 !!!
                await cursor.execute("SELECT proxy_key, contents, last_used FROM contexts ORDER BY last_used DESC")
                rows = await cursor.fetchall() # 获取所有行

            # 遍历查询结果
            for row in rows:
                proxy_key = row['proxy_key'] # 获取 proxy_key
                contents_json = row['contents'] # 获取上下文内容的 JSON 字符串
                last_used_str = row['last_used'] # 获取最后使用时间的 ISO 格式字符串

                # --- 生成内容摘要 ---
                context_summary = "N/A" # 初始化摘要为 "N/A"
                if contents_json: # 如果内容不为空
                    try:
                        # 在线程中反序列化 JSON
                        contents_list = await asyncio.to_thread(json.loads, contents_json)
                        # 检查反序列化结果是否为非空列表
                        if contents_list and isinstance(contents_list, list) and len(contents_list) > 0:
                            # 尝试从第一条消息提取文本内容作为摘要
                            first_message = contents_list[0]
                            if isinstance(first_message, dict) and 'content' in first_message: # 处理 OpenAI 格式
                                content_text = str(first_message['content'])
                                context_summary = content_text[:100] + "..." if len(content_text) > 100 else content_text
                            elif isinstance(first_message, dict) and 'parts' in first_message and isinstance(first_message['parts'], list) and len(first_message['parts']) > 0: # 处理 Gemini 格式
                                first_part = first_message['parts'][0]
                                if isinstance(first_part, dict) and 'text' in first_part:
                                    content_text = str(first_part['text'])
                                    context_summary = content_text[:100] + "..." if len(content_text) > 100 else content_text
                    except json.JSONDecodeError: # 捕获 JSON 解析错误
                        logger.warning(f"无法解析 Key {proxy_key[:8]}... 的上下文内容 JSON。") # 记录警告
                    except Exception as e: # 捕获其他提取摘要时的错误
                        logger.warning(f"提取 Key {proxy_key[:8]}... 的上下文摘要时出错: {e}") # 记录警告

                # --- 计算剩余 TTL ---
                ttl_remaining_str = "N/A" # 初始化剩余 TTL 字符串为 "N/A"
                if last_used_str and global_ttl_seconds > 0: # 仅在有上次使用时间且 TTL > 0 时计算
                    try:
                        # 解析 ISO 格式时间字符串，并确保为 UTC 时区
                        last_used_dt = datetime.fromisoformat(last_used_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
                        # 计算过期时间点
                        expiry_time = last_used_dt + timedelta(seconds=global_ttl_seconds)
                        now_utc = datetime.now(timezone.utc) # 获取当前 UTC 时间
                        # 计算剩余时间差
                        remaining_delta = expiry_time - now_utc
                        if remaining_delta.total_seconds() > 0: # 如果尚未过期
                            # 将剩余时间格式化为可读字符串
                            days = remaining_delta.days
                            hours, remainder = divmod(remaining_delta.seconds, 3600)
                            minutes, seconds = divmod(remainder, 60)
                            if days > 0:
                                ttl_remaining_str = f"{days}天 {hours}小时"
                            elif hours > 0:
                                ttl_remaining_str = f"{hours}小时 {minutes}分钟"
                            elif minutes > 0:
                                ttl_remaining_str = f"{minutes}分钟 {seconds}秒"
                            else:
                                ttl_remaining_str = f"{seconds}秒"
                        else: # 如果已过期
                            ttl_remaining_str = "已过期"
                    except ValueError: # 捕获时间戳解析错误
                        logger.warning(f"无法解析 Key {proxy_key[:8]}... 的 last_used 时间戳: {last_used_str}") # 记录警告
                elif global_ttl_seconds <= 0: # 如果 TTL 设置为 0 或负数
                    ttl_remaining_str = "永不" # 表示永不过期

                # --- 存储结果 ---
                all_contexts_data[proxy_key] = {
                    "ttl": ttl_remaining_str, # 剩余 TTL 字符串
                    # 格式化最后访问时间为 "YYYY-MM-DD HH:MM:SS"
                    "last_accessed": last_used_str.split('.')[0].replace('T', ' ') if last_used_str else "N/A",
                    "context_summary": context_summary # 内容摘要
                }
        logger.info(f"成功获取了 {len(all_contexts_data)} 条上下文记录及其 TTL 信息。") # 记录成功日志

    except aiosqlite.Error as e: # 捕获数据库错误
        logger.error(f"获取所有上下文及其 TTL 信息失败: {e}", exc_info=True) # 记录错误
    except Exception as e: # 捕获其他意外错误
        logger.error(f"处理所有上下文数据时发生意外错误: {e}", exc_info=True) # 记录错误

    return all_contexts_data # 返回结果字典
