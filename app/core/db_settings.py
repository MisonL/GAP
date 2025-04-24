# -*- coding: utf-8 -*-
"""
处理数据库中 'settings' 表的交互，用于存储和检索配置项。
Handles interactions with the 'settings' table in the database, used for storing and retrieving configuration items.
"""
import sqlite3 # 导入 sqlite3 模块 (Import sqlite3 module)
import logging # 导入 logging 模块 (Import logging module)
import asyncio # 导入 asyncio (Import asyncio)
from typing import Optional # 导入 Optional 类型提示 (Import Optional type hint)

# 导入共享的数据库连接函数和路径配置
# Import shared database connection function and path configuration
from .db_utils import get_db_connection, DATABASE_PATH, DEFAULT_CONTEXT_TTL_DAYS # 导入数据库连接、路径、默认 TTL (Import database connection, path, default TTL)

logger = logging.getLogger('my_logger') # 获取日志记录器实例 (Get logger instance)

# --- 设置管理 ---
# --- Settings Management ---
# 注意：此函数现在需要是 async
# Note: This function now needs to be async
async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    获取指定键的设置值。
    Gets the setting value for the specified key.
    """
    try:
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            cursor = conn.cursor() # 获取游标 (Get cursor)
            await asyncio.to_thread(cursor.execute, "SELECT value FROM settings WHERE key = ?", (key,)) # 在线程中执行查询 (Execute query in a thread)
            row = await asyncio.to_thread(cursor.fetchone) # 在线程中获取单行结果 (Fetch single row result in a thread)
            return row['value'] if row else default # 如果找到行则返回值，否则返回默认值 (Return value if row is found, otherwise return default value)
    except sqlite3.Error as e:
        logger.error(f"获取设置 '{key}' 失败: {e}", exc_info=True) # 记录获取设置失败错误 (Log failure to get setting error)
        return default # 出错时返回默认值 (Return default value on error)

# 注意：此函数现在需要是 async
# Note: This function now needs to be async
async def set_setting(key: str, value: str):
    """
    设置或更新指定键的设置值。
    Sets or updates the setting value for the specified key.
    """
    try:
        async with get_db_connection() as conn: # 获取异步数据库连接 (Get asynchronous database connection)
            cursor = conn.cursor() # 获取游标 (Get cursor)
            await asyncio.to_thread(cursor.execute, "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)) # 在线程中执行插入或替换操作 (Execute INSERT or REPLACE operation in a thread)
            await asyncio.to_thread(conn.commit) # 在线程中提交事务 (Commit transaction in a thread)
            logger.info(f"设置 '{key}' 已更新为 '{value}'") # 记录设置更新 (Log setting update)
    except sqlite3.Error as e:
        logger.error(f"设置 '{key}' 失败: {e}", exc_info=True) # 记录设置失败错误 (Log setting failure error)

# 注意：此函数现在需要是 async
# Note: This function now needs to be async
async def get_ttl_days() -> int:
    """
    获取上下文 TTL 天数设置。
    Gets the context TTL days setting.
    """
    value_str = await get_setting('context_ttl_days', str(DEFAULT_CONTEXT_TTL_DAYS)) # 使用 await 调用 (Call with await)
    try:
        val = int(value_str) if value_str else DEFAULT_CONTEXT_TTL_DAYS # 将值转换为整数，如果为空则使用默认值 (Convert value to integer, use default if empty)
        return val if val >= 0 else 0 # TTL 不能为负数，0 表示禁用 TTL (TTL cannot be negative, 0 means disable TTL)
    except (ValueError, TypeError):
        logger.warning(f"无效的 TTL 设置值 '{value_str}'，将使用默认值 {DEFAULT_CONTEXT_TTL_DAYS}") # 记录无效值警告 (Log warning for invalid value)
        return DEFAULT_CONTEXT_TTL_DAYS # 返回默认值 (Return default value)

# 注意：此函数现在需要是 async
# Note: This function now needs to be async
async def set_ttl_days(days: int):
    """
    设置上下文 TTL 天数。
    Sets the context TTL days.
    """
    if not isinstance(days, int) or days < 0: # 允许设置为 0 (Allow setting to 0)
        logger.error(f"尝试设置无效的 TTL 天数: {days}") # 记录无效天数错误 (Log error for invalid number of days)
        raise ValueError("TTL 天数必须是非负整数") # 引发 ValueError (Raise ValueError)
    await set_setting('context_ttl_days', str(days)) # 使用 await 调用 (Call with await)
