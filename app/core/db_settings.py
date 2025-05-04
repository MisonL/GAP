# -*- coding: utf-8 -*-
"""
处理数据库中 'settings' 表的交互，用于存储和检索配置项。
"""
import sqlite3 # 导入 sqlite3 模块
import logging # 导入 logging 模块
import asyncio # 导入 asyncio
from typing import Optional # 导入 Optional 类型提示

# 导入共享的数据库连接函数和路径配置
from app.core.db_utils import get_db_connection, DATABASE_PATH, DEFAULT_CONTEXT_TTL_DAYS # 导入数据库连接、路径、默认 TTL

logger = logging.getLogger('my_logger') # 获取日志记录器实例

# --- 设置管理 ---
async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    从数据库中获取指定设置的值。

    Args:
        key: 设置的键。
        default: 如果设置不存在或获取失败时返回的默认值。

    Returns:
        设置的值（字符串）或默认值。
    """
    cursor = None # 初始化游标变量
    try:
        async with get_db_connection() as conn:
            cursor = await conn.cursor() # 正确 await 获取异步游标
            # 直接 await 执行异步查询
            await cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            # 直接 await 获取异步结果
            row = await cursor.fetchone()
            return row[0] if row else default # 如果找到行则返回值，否则返回默认值
    except sqlite3.Error as e:
        logger.error(f"获取设置 '{key}' 失败: {e}", exc_info=True) # 获取设置失败
        return default # 出错时返回默认值
    finally:
        if cursor:
            await cursor.close() # 确保游标在使用后关闭

async def set_setting(key: str, value: str):
    """
    在数据库中设置或更新指定设置的值。

    Args:
        key: 设置的键。
        value: 要设置的值（字符串）。
    """
    cursor = None # 初始化游标变量
    try:
        async with get_db_connection() as conn:
            cursor = await conn.cursor() # 正确 await 获取异步游标
            # 直接 await 执行异步插入或替换操作
            await cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            await conn.commit() # 直接 await 提交事务
            logger.info(f"设置 '{key}' 已更新为 '{value}'") # 设置已更新
    except sqlite3.Error as e:
        logger.error(f"设置 '{key}' 失败: {e}", exc_info=True) # 设置失败
    finally:
        if cursor:
            await cursor.close() # 确保游标在使用后关闭

async def get_ttl_days() -> int:
    """
    从数据库获取上下文 TTL (天数)，处理类型转换和无效值。

    Returns:
        上下文 TTL (天数)，如果设置无效或获取失败则返回 DEFAULT_CONTEXT_TTL_DAYS。
        返回的值保证是非负整数。
    """
    value_str = await get_setting('context_ttl_days', str(DEFAULT_CONTEXT_TTL_DAYS))
    try:
        # 尝试将获取到的字符串转换为整数
        val = int(value_str)
        # 确保 TTL 不是负数
        return max(0, val)
    except (ValueError, TypeError):
        # 如果转换失败或获取到的值不是有效的字符串，记录警告并返回默认值
        logger.warning(f"无效的 TTL 设置值 '{value_str}'，将使用默认值 {DEFAULT_CONTEXT_TTL_DAYS}") # 无效的 TTL 设置值
        return DEFAULT_CONTEXT_TTL_DAYS # 返回默认值


async def set_ttl_days(days: int):
    """
    在数据库中设置上下文 TTL (天数)。

    Args:
        days: 要设置的 TTL 天数（非负整数）。

    Raises:
        ValueError: 如果 days 不是非负整数。
    """
    if not isinstance(days, int) or days < 0:
        logger.error(f"尝试设置无效的 TTL 天数: {days}")
        raise ValueError("TTL 天数必须是非负整数") # 引发 ValueError
    await set_setting('context_ttl_days', str(days)) # 使用 await 调用
