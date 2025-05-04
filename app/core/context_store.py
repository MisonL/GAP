# -*- coding: utf-8 -*-
"""
处理 SQLite 数据库交互，用于存储代理密钥、对话上下文和设置。
支持文件存储（持久化）和内存存储（临时）。
"""
import aiosqlite # 导入 aiosqlite 模块
import logging # 导入 logging 模块
import os # 导入 os 模块
import json # 导入 json 模块
import uuid # 导入 uuid 模块
import asyncio # 导入 asyncio
from datetime import datetime, timedelta, timezone # 导入日期、时间、时区相关
from contextlib import asynccontextmanager # 改为异步上下文管理器
from typing import Optional, List, Dict, Any, Tuple, Union, AsyncGenerator # 导入类型提示, 增加 Union, AsyncGenerator
from app.core.message_converter import convert_messages # 导入消息转换函数

# 导入 Message 类
from app.api.models import Message

# 导入新的设置管理模块
from app.core.db_settings import get_ttl_days, set_ttl_days # 注意：这些也需要变成 async
from app.config import MAX_CONTEXT_RECORDS_MEMORY # 导入最大记录数配置

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# 延迟导入 db_utils 以避免循环依赖
# from app.core.db_utils import get_db_connection, DATABASE_PATH, IS_MEMORY_DB, DEFAULT_CONTEXT_TTL_DAYS


async def get_proxy_key(key: str) -> Optional[Dict[str, Any]]:
     """
     获取单个代理 Key 的信息。
     """
     if not key: return None
     try:
         # 延迟导入 db_utils
         from app.core.db_utils import get_db_connection
         async with get_db_connection() as conn: # 获取异步数据库连接
             async with conn.cursor() as cursor: # 使用异步游标
                 await cursor.execute("SELECT key, description, created_at, is_active FROM proxy_keys WHERE key = ?", (key,)) # 使用 await
                 row = await cursor.fetchone() # 使用 await
             return dict(row) if row else None # 如果找到行则转换为字典并返回，否则返回 None
     except aiosqlite.Error as e: # 捕获 aiosqlite 错误
         logger.error(f"获取代理 Key {key[:8]}... 信息失败: {e}", exc_info=True) # 获取代理 Key 信息失败
         return None # 出错时返回 None

async def is_valid_proxy_key(key: str) -> bool:
    """
    检查代理 Key 是否有效且处于活动状态 (从数据库)。
    """
    key_info = await get_proxy_key(key)
    return bool(key_info and key_info.get('is_active')) # 返回 Key 是否有效且活跃


async def save_context(proxy_key: str, contents: List[Dict[str, Any]]):
    """
    保存或更新指定代理 Key 的上下文。
    """
    if not proxy_key or not contents:
        logger.warning(f"尝试为 Key {proxy_key[:8]}... 保存空的上下文，已跳过。")
        return
    try:
        try:
            # json.dumps is a CPU-intensive operation, can also consider putting it in to_thread
            contents_json = await asyncio.to_thread(json.dumps, contents, ensure_ascii=False) # 在线程中序列化 JSON
            # contents_json = json.dumps(contents, ensure_ascii=False) # 或者保持同步如果性能影响不大
        except TypeError as json_err:
            logger.error(f"序列化上下文为 JSON 时失败 (TypeError) (Key: {proxy_key[:8]}...): {json_err}", exc_info=True) # 序列化上下文为 JSON 时失败
            return # 无法序列化，直接返回

        # 延迟导入 db_utils
        from app.core.db_utils import get_db_connection, IS_MEMORY_DB, DATABASE_PATH
        async with get_db_connection() as conn: # 获取异步数据库连接
            async with conn.cursor() as cursor: # 使用异步游标
            # 使用 ISO 格式存储 UTC 时间戳
                last_used_ts = datetime.now(timezone.utc).isoformat() # 获取当前 UTC 时间并格式化
                # 在引用之前确保 proxy_key 存在于 proxy_keys 表中
                # 这对于内存模式至关重要，因为 Key 可能不会预先填充
                await cursor.execute("INSERT OR IGNORE INTO proxy_keys (key) VALUES (?)", (proxy_key,)) # 使用 await
                logger.info(f"准备在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 执行 INSERT OR REPLACE...") # 准备执行 INSERT OR REPLACE
                await cursor.execute( # 使用 await
                    """
                    INSERT OR REPLACE INTO contexts (proxy_key, contents, last_used)
                    VALUES (?, ?, ?)
                    """,
                    (proxy_key, contents_json, last_used_ts)
                )
                logger.info(f"在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 执行 INSERT OR REPLACE 完成。") # 移除了 "准备提交" 日志 (Removed "preparing to commit" log)

                # --- 新增：内存数据库记录数限制 ---
                # 将修剪逻辑委托给辅助函数
                if IS_MEMORY_DB and MAX_CONTEXT_RECORDS_MEMORY > 0:
                    await _prune_memory_context(cursor)

            # 提交事务（包括插入/替换和可能的删除）
            logger.info(f"准备在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 提交事务...") # 准备提交事务
            await conn.commit() # 使用 await
            logger.info(f"在连接 {id(conn)} 上为 Key {proxy_key[:8]}... 提交事务完成。") # 提交事务完成
    except aiosqlite.Error as e: # 捕获 aiosqlite 错误
        logger.error(f"为 Key {proxy_key[:8]}... 保存上下文失败: {e}", exc_info=True) # 保存上下文失败
    except json.JSONDecodeError as e:
        logger.error(f"反序列化上下文为 JSON 时失败 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 修正了日志消息：反序列化错误 (Corrected log message: deserialization error)
    except Exception as e: # 捕获保存期间任何其他意外错误
        logger.error(f"保存上下文时发生意外错误 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 保存上下文时发生意外错误

async def _prune_memory_context(cursor: aiosqlite.Cursor):
    """
    修剪内存数据库中的上下文记录，使其不超过最大限制。
    这是一个辅助函数，应在 save_context 内部调用。
    """
    # 延迟导入 db_utils
    from app.core.db_utils import IS_MEMORY_DB # 在函数开头导入

    if not IS_MEMORY_DB or MAX_CONTEXT_RECORDS_MEMORY <= 0:
        return

    try:
        # 获取当前记录数
        await cursor.execute("SELECT COUNT(*) FROM contexts") # 使用 await
        count_row = await cursor.fetchone() # 使用 await (Use await)
        current_count = count_row[0] if count_row else 0 # 获取当前记录数

        if current_count > MAX_CONTEXT_RECORDS_MEMORY: # 如果当前记录数超过限制
            num_to_delete = current_count - MAX_CONTEXT_RECORDS_MEMORY # 计算需要删除的数量
            logger.info(f"内存数据库记录数 ({current_count}) 已超过限制 ({MAX_CONTEXT_RECORDS_MEMORY})，将删除 {num_to_delete} 条最旧的记录...") # 内存数据库记录数超过限制，将删除最旧的记录
            # 删除 last_used 最早的记录
            # 使用 rowid 可以确保删除的是物理上最早插入（或最近未更新）的行
            # Using rowid ensures that the physically earliest inserted (or least recently updated) rows are deleted
            await cursor.execute( # 使用 await
                """
                DELETE FROM contexts
                WHERE rowid IN (
                    SELECT rowid FROM contexts ORDER BY last_used ASC LIMIT ?
                )
                """,
                (num_to_delete,)
            )
            rowcount = cursor.rowcount # 获取 rowcount
            logger.info(f"成功删除了 {rowcount} 条最旧的内存上下文记录。") # Log successful deletion
    except aiosqlite.Error as prune_err: # 捕获 aiosqlite 错误
        # 记录修剪错误，但不影响主保存操作的提交
        logger.error(f"修剪内存上下文记录时出错: {prune_err}", exc_info=True) # 修剪内存上下文记录时出错

async def _is_context_expired(last_used_str: str, ttl_delta: Optional[timedelta], proxy_key: str) -> bool:
    """
    检查上下文是否已过期。
    """
    if not ttl_delta:
        return False # TTL 禁用，永不过期

    now_utc = datetime.now(timezone.utc) # 获取当前 UTC 时间
    try:
        # 解析存储的 ISO 格式 UTC 时间戳
        last_used_dt = datetime.fromisoformat(last_used_str).replace(tzinfo=timezone.utc) # 解析时间戳并设置为 UTC
        if now_utc - last_used_dt > ttl_delta: # 如果超过 TTL
            logger.info(f"Key {proxy_key[:8]}... 的上下文已超过 TTL，将被删除。") # 上下文已超过 TTL，将被删除
            return True # 已过期
        return False # 未过期
    except (ValueError, TypeError) as dt_err:
         logger.error(f"解析 Key {proxy_key[:8]}... 的 last_used 时间戳 '{last_used_str}' 失败: {dt_err}。视为已过期。") # 解析 last_used 时间戳失败
         return True # 解析失败，视为已过期

# 将 delete_context_for_key 函数移到这里，在其首次使用之前定义
async def delete_context_for_key(proxy_key: str) -> bool:
    """
    删除指定代理 Key 的上下文记录。
    """
    if not proxy_key: return False
    try:
        # 延迟导入 db_utils
        from app.core.db_utils import get_db_connection
        async with get_db_connection() as conn: # 获取异步数据库连接
            async with conn.cursor() as cursor: # 使用异步游标
                await cursor.execute("DELETE FROM contexts WHERE proxy_key = ?", (proxy_key,)) # 使用 await
                rowcount = cursor.rowcount # 获取 rowcount
                await conn.commit() # 使用 await
            if rowcount > 0: # 如果删除了记录
                logger.info(f"上下文已为 Key {proxy_key[:8]}... 删除。") # 上下文已删除
                return True # 返回 True
            else:
                logger.warning(f"尝试删除 Key {proxy_key[:8]}... 的上下文，但未找到记录。") # 尝试删除上下文，但未找到记录
                return False # 返回 False
    except aiosqlite.Error as e: # 捕获 aiosqlite 错误
        logger.error(f"删除 Key {proxy_key[:8]}... 的上下文失败: {e}", exc_info=True) # 删除上下文失败
        return False # 出错时返回 False


async def _deserialize_context_contents(contents_json: str, proxy_key: str) -> Optional[List[Dict[str, Any]]]:
    """
    反序列化存储的上下文 JSON 字符串，处理错误并删除损坏的数据。
    """
    try:
        contents = await asyncio.to_thread(json.loads, contents_json) # 在线程中反序列化 JSON
        logger.debug(f"上下文已为 Key {proxy_key[:8]}... 加载。") # 上下文已加载
        return contents # 返回加载的上下文
    except json.JSONDecodeError as e:
        logger.error(f"反序列化存储的上下文时失败 (Key: {proxy_key[:8]}...): {e}", exc_info=True) # 记录反序列化错误 (Log deserialization error)
        # 删除损坏的数据，避免下次加载时再次出错
        await delete_context_for_key(proxy_key) # 调用异步删除函数
        return None # 返回 None

async def load_context(proxy_key: str) -> Optional[List[Dict[str, Any]]]:
    """
    加载指定代理 Key 的上下文，并检查 TTL。
    """
    if not proxy_key: return None

    ttl_days = await get_ttl_days() # 获取 TTL 天数
    ttl_delta = timedelta(days=ttl_days) if ttl_days > 0 else None # 计算 TTL 时间差 (如果 TTL > 0)

    try:
        # 延迟导入 db_utils
        from app.core.db_utils import get_db_connection
        async with get_db_connection() as conn: # 获取异步数据库连接
            async with conn.cursor() as cursor: # 使用异步游标
                await cursor.execute("SELECT contents, last_used FROM contexts WHERE proxy_key = ?", (proxy_key,)) # 使用 await
                row = await cursor.fetchone() # 使用 await

            if not row or not row['contents']: # 如果未找到记录或内容为空
                logger.debug(f"未找到 Key {proxy_key[:8]}... 的上下文。") # 未找到上下文
                return None # 返回 None

            last_used_str = row['last_used'] # 获取最后使用时间字符串
            contents_json = row['contents'] # 获取 JSON 字符串内容

            # 检查 TTL
            if await _is_context_expired(last_used_str, ttl_delta, proxy_key):
                 await delete_context_for_key(proxy_key) # 调用异步删除函数
                 return None # 已过期并删除，返回 None

            # 反序列化内容
            return await _deserialize_context_contents(contents_json, proxy_key)

    except aiosqlite.Error as e: # 捕获 aiosqlite 错误
        logger.error(f"为 Key {proxy_key[:8]}... 加载上下文失败: {e}", exc_info=True) # 加载上下文失败
        return None # 出错时返回 None


# 函数定义已移到前面
async def get_context_info(proxy_key: str) -> Optional[Dict[str, Any]]:
     """
     获取指定代理 Key 上下文的元信息。
     """
     if not proxy_key: return None
     try:
         # 延迟导入 db_utils
         from app.core.db_utils import get_db_connection
         async with get_db_connection() as conn: # 获取异步数据库连接
             async with conn.cursor() as cursor: # 使用异步游标
                 await cursor.execute("SELECT length(contents) as content_length, last_used FROM contexts WHERE proxy_key = ?", (proxy_key,)) # 使用 await
                 row = await cursor.fetchone() # 使用 await
             return dict(row) if row else None # 如果找到行则转换为字典并返回，否则返回 None
     except aiosqlite.Error as e: # 捕获 aiosqlite 错误
         logger.error(f"获取 Key {proxy_key[:8]}... 的上下文信息失败: {e}", exc_info=True) # 获取 Key 的上下文信息失败
         return None # 出错时返回 None

async def list_all_context_keys_info(user_key: Optional[str] = None, is_admin: bool = False) -> List[Dict[str, Any]]:
    """
    获取存储的上下文的 Key 和元信息。
    - 如果 is_admin 为 True，返回所有上下文信息。
    - 如果 is_admin 为 False 且提供了 user_key，仅返回该用户的上下文信息。
    - 否则返回空列表。

    Args:
        user_key: 当前用户的 Key。
        is_admin: 当前用户是否为管理员。

    Returns:
        包含上下文信息的字典列表。
    """
    contexts_info = []
    try:
        # 延迟导入 db_utils
        from app.core.db_utils import get_db_connection, DATABASE_PATH
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            async with conn.cursor() as cursor: # 使用异步游标 (Use asynchronous cursor)
                # 修改 SQL 查询语句，包含 contents 字段
                sql = "SELECT proxy_key, contents, length(contents) as content_length, last_used FROM contexts" # 构建 SQL 查询语句 (Build SQL query statement)
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

                await cursor.execute(sql, params) # 使用 await (Use await)
                rows = await cursor.fetchall() # 使用 await (Use await)
                # 修正日志记录，确保在 user_key 为 None 时不会出错
                log_key_info = 'admin' if is_admin else (user_key[:8]+'...' if user_key else 'unknown_user')
                # 限制日志中原始行的输出长度，避免过长
                raw_rows_str = str(rows)
                max_log_len = 500 # 设置日志中原始行内容的最大长度
                if len(raw_rows_str) > max_log_len:
                    raw_rows_str = raw_rows_str[:max_log_len] + f"... (truncated, total {len(rows)} rows)"
                logger.info(f"list_all_context_keys_info: Fetched {len(rows)} rows from DB for {log_key_info}. Raw rows: {raw_rows_str}") # Log number of rows fetched
                contexts_info = [dict(row) for row in rows] # 将结果转换为字典列表 (Convert results to list of dictionaries)
    except aiosqlite.Error as e: # 捕获 aiosqlite 错误 (Catch aiosqlite error)
        log_prefix = f"管理员" if is_admin else f"用户 {user_key[:8]}..." if user_key else "未知用户" # 构建日志前缀 (Build log prefix)
        logger.error(f"{log_prefix} 列出上下文信息失败 ({DATABASE_PATH}): {e}", exc_info=True) # 记录列出信息失败错误 (Log failure to list info error)
        contexts_info = [] # 出错时返回空列表 (Return empty list on error)
    return contexts_info # 返回上下文信息列表 (Return list of context info)

# --- 上下文格式转换函数 ---

def convert_openai_to_gemini_contents(history: List[Dict]) -> List[Dict]:
    """
    将 OpenAI 格式的对话历史转换为 Gemini 的 contents 格式。

    Args:
        history: OpenAI 格式的对话历史列表 (e.g., [{'role': 'user', 'content': '...'}, {'role': 'assistant', 'content': '...'}])。

    Returns:
        Gemini 格式的 contents 列表 (e.g., [{'role': 'user', 'parts': [{'text': '...'}]}, {'role': 'assistant', 'parts': [{'text': '...'}]}]).
    """
    gemini_contents = []
    for message in history: # 遍历 OpenAI 格式的历史记录 (Iterate through OpenAI format history)
        openai_role = message.get('role') # 获取 OpenAI 角色 (Get OpenAI role)
        openai_content = message.get('content') # 获取 OpenAI 内容 (Get OpenAI content)

        if openai_role and openai_content is not None: # 确保角色和内容存在 (Ensure role and content exist)
            # 映射角色：'user' -> 'user', 'assistant' -> 'model'
            # Map roles: 'user' -> 'user', 'assistant' -> 'model'
            gemini_role = 'user' if openai_role == 'user' else 'model' if openai_role == 'assistant' else openai_role # 映射角色 (Map role)

            # 将内容字符串转换为 Gemini 的 parts 格式
            # Convert content string to Gemini's parts format
            gemini_parts = [{'text': str(openai_content)}] # 假设内容是文本 (Assume content is text)

            gemini_contents.append({'role': gemini_role, 'parts': gemini_parts}) # 添加到 Gemini contents 列表 (Append to Gemini contents list)
        else:
            logger.warning(f"跳过无效的 OpenAI 历史消息: {message}") # 记录无效消息警告 (Log warning for invalid message)

    return gemini_contents # 返回转换后的 Gemini contents (Return converted Gemini contents)

async def load_context_as_gemini(proxy_key: str) -> Optional[List[Dict[str, Any]]]:
    """
    加载指定代理 Key 的上下文，并将其转换为 Gemini 的 contents 格式。

    Args:
        proxy_key: 代理 Key。

    Returns:
        Gemini 格式的 contents 列表，如果未找到上下文或加载失败则返回 None。
    """
    openai_context = await load_context(proxy_key)
    if openai_context is None:
        return None # 如果加载失败或未找到，返回 None (Return None if loading fails or not found)

    # 将加载的字典列表转换为 Message 对象列表
    # Convert the loaded list of dictionaries to a list of Message objects
    message_objects = []
    for i, msg_dict in enumerate(openai_context):
        # 确保字典包含 role 和 parts 字段，并且 parts 是一个列表
        # Ensure the dictionary contains role and parts fields, and parts is a list
        if 'role' in msg_dict and 'parts' in msg_dict and isinstance(msg_dict['parts'], list):
            role = msg_dict['role']
            parts_list = msg_dict['parts']

            # 构建 content 字段，它应该是 parts 列表本身
            # Construct the content field, which should be the parts list itself
            content = parts_list # Message model expects content to be Union[str, List[Dict]]

            # 构建符合 Message 模型期望的字典
            # Construct a dictionary that matches the Message model's expectation
            message_data = {'role': role, 'content': content}

            try:
                # 使用构建好的字典创建 Message 对象
                # Create Message object using the constructed dictionary
                message_objects.append(Message(**message_data))
                logger.debug(f"为 Key {proxy_key[:8]}... 成功将第 {i} 条上下文字典转换为 Message 对象。") # 添加调试日志
            except Exception as e:
                logger.error(f"为 Key {proxy_key[:8]}... 使用构建的字典创建 Message 对象失败: {e}. 跳过此消息。", exc_info=True)
        else:
            # 如果字典格式异常，记录错误并跳过此消息
            # If the dictionary format is abnormal, log error and skip this message
            logger.error(f"为 Key {proxy_key[:8]}... 第 {i} 条上下文字典格式异常，无法处理。跳过此消息: {msg_dict}", exc_info=True)


    # 检查转换后的消息列表是否为空
    # Check if the converted message list is empty
    if not message_objects:
        logger.warning(f"为 Key {proxy_key[:8]}... 加载的上下文为空或所有消息均无效。返回 None。") # Log warning if message_objects is empty
        return None

    # 检查第一条消息的角色是否为 'assistant', 这可能导致 Gemini API 错误
    # Check if the role of the first message is 'assistant', which might cause Gemini API errors
    if message_objects[0].role == 'assistant':
        logger.warning(f"为 Key {proxy_key[:8]}... 加载的上下文第一条消息角色为 'assistant', 这可能导致 Gemini API 错误。") # Log warning for first message role


    # 使用更通用的 convert_messages 函数将 Message 对象列表转换为 Gemini 格式
    # Use the more general convert_messages function to convert the list of Message objects to Gemini format
    # 注意：convert_messages 函数内部会处理角色映射 ('user', 'system' -> 'user', 'assistant' -> 'model')
    # Note: The convert_messages function internally handles role mapping ('user', 'system' -> 'user', 'assistant' -> 'model')
    conversion_result = convert_messages(message_objects, use_system_prompt=False) # 不将历史中的 system 消息视为系统指令
    if isinstance(conversion_result, list): # 如果转换失败，convert_messages 返回错误字符串列表
        logger.error(f"为 Key {proxy_key[:8]}... 转换 Message 对象列表为 Gemini 格式失败: {'; '.join(conversion_result)}") # 记录转换失败错误
        return None # 返回 None 表示加载和转换失败

    gemini_context, _ = conversion_result # 忽略系统指令，因为它应该只来自当前请求
    return gemini_context # 返回转换后的 Gemini 格式的上下文 (Return Gemini format context)


def convert_gemini_to_storage_format(request_content: Dict, response_content: Dict) -> List[Dict]:
    """
    将 Gemini 的请求内容 (用户) 和响应内容 (模型) 转换为内部存储格式 (OpenAI 格式)。
    """
    storage_format = []

    # 处理用户请求内容
    # Process user request content
    user_role = request_content.get('role') # 获取用户角色 (Get user role)
    user_parts = request_content.get('parts', []) # 获取用户 parts (Get user parts)
    user_text = "" # 初始化用户文本 (Initialize user text)
    if user_role == 'user' and user_parts: # 如果是用户角色且有 parts (If it's user role and has parts)
        # 提取文本内容 (假设第一个 part 是文本)
        # Extract text content (assuming the first part is text)
        first_part = user_parts[0] # 获取第一个 part (Get the first part)
        if 'text' in first_part: # 如果 part 中有文本 (If there is text in the part)
            user_text = first_part['text'] # 获取文本内容 (Get text content)
        # TODO: 未来可能需要处理其他类型的 parts (e.g., images)
        # TODO: May need to handle other types of parts in the future
        storage_format.append({'role': 'user', 'content': user_text}) # 添加到存储格式列表 (Append to storage format list)
    else:
        logger.warning(f"转换 Gemini 用户请求内容时发现无效格式: {request_content}") # Log warning for invalid Gemini user request format

    # 处理模型响应内容
    # Process model response content
    model_role = response_content.get('role') # 获取模型角色 (Get model role)
    model_parts = response_content.get('parts', []) # 获取模型 parts (Get model parts)
    model_text = "" # 初始化模型文本 (Initialize model text)
    if model_role == 'model' and model_parts: # 如果是模型角色且有 parts (If it's model role and has parts)
         # 提取文本内容 (假设第一个 part 是文本)
         # Extract text content (assuming the first part is text)
        first_part = model_parts[0] # 获取第一个 part (Get the first part)
        if 'text' in first_part: # 如果 part 中有文本 (If there is text in the part)
            model_text = first_part['text'] # 获取文本内容 (Get text content)
        # TODO: 未来可能需要处理其他类型的 parts
        # TODO: May need to handle other types of parts in the future
        storage_format.append({'role': 'assistant', 'content': model_text}) # 添加到存储格式列表 (Append to storage format list)
    else:
        logger.warning(f"转换 Gemini 模型响应内容时发现无效格式: {response_content}") # Log warning for invalid Gemini model response format


    return storage_format # 返回转换后的存储格式列表 (Return converted storage format list)


# --- 内存数据库清理 ---
from app.core.db_utils import IS_MEMORY_DB # 在函数开头导入

async def cleanup_memory_context(max_age_seconds: int):
    """
    清理内存数据库中超过指定时间的旧上下文记录。
    """
    if not IS_MEMORY_DB:
        return

    if max_age_seconds <= 0: # 如果最大年龄无效 (If max age is invalid)
        logger.warning("内存上下文清理间隔无效 (<= 0)，跳过清理。") # Log warning for invalid cleanup interval
        return

    cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds) # 计算截止时间 (Calculate cutoff time)
    # 使用 ISO 格式进行比较
    # Use ISO format for comparison
    cutoff_time_iso = cutoff_time.isoformat()

    try:
        # 延迟导入 db_utils
        from app.core.db_utils import get_db_connection
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            async with conn.cursor() as cursor: # 使用异步游标 (Use asynchronous cursor)
                await cursor.execute("DELETE FROM contexts WHERE last_used < ?", (cutoff_time_iso,)) # 使用 await (Use await)
                rowcount = cursor.rowcount # 获取 rowcount (Get rowcount)
                await conn.commit() # 使用 await (Use await)
            if rowcount > 0: # 如果删除了记录 (If records were deleted)
                logger.info(f"成功清理了 {rowcount} 条超过 {max_age_seconds} 秒的内存上下文记录。") # Log successful cleanup
            else:
                logger.debug("内存上下文清理完成，没有找到需要删除的记录。") # Log completion with no records deleted
    except aiosqlite.Error as e: # 捕获 aiosqlite 错误 (Catch aiosqlite error)
        logger.error(f"清理内存上下文记录失败: {e}", exc_info=True) # Log failure to cleanup memory context


async def update_ttl(context_key: str, ttl_seconds: int) -> Optional[bool]:
    """
    更新指定上下文记录的 TTL (通过更新 last_used 时间戳)。
    """
    if not context_key: return False
    try:
        # 延迟导入 db_utils
        from app.core.db_utils import get_db_connection
        async with get_db_connection() as conn:
            async with conn.cursor() as cursor:
                # 更新 last_used 为当前时间
                now_utc_iso = datetime.now(timezone.utc).isoformat()
                await cursor.execute("UPDATE contexts SET last_used = ?", (now_utc_iso, context_key))
                rowcount = cursor.rowcount
                await conn.commit()
            if rowcount > 0:
                logger.info(f"成功更新了 Key {context_key[:8]}... 的 last_used 时间戳。")
                return True
            else:
                logger.warning(f"尝试更新 Key {context_key[:8]}... 的 last_used 时间戳，但未找到记录。")
                return False
    except aiosqlite.Error as e:
        logger.error(f"更新 Key {context_key[:8]}... 的 last_used 时间戳失败: {e}", exc_info=True)
        return False

async def update_global_ttl(ttl_seconds: int) -> bool:
    """
    更新全局上下文 TTL 设置。
    """
    # 延迟导入 db_settings
    from app.core.db_settings import set_setting
    try:
        # 将 TTL 存储为字符串，以便兼容 SQLite
        await set_setting("context_ttl_seconds", str(ttl_seconds))
        logger.info(f"全局上下文 TTL 已更新为 {ttl_seconds} 秒。")
        return True
    except Exception as e:
        logger.error(f"更新全局上下文 TTL 失败: {e}", exc_info=True)
        return False
