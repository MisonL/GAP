# -*- coding: utf-8 -*-
"""
处理数据库中 'settings' 表的交互，用于存储和检索配置项。
"""
import sqlite3
import logging
from typing import Optional

# 导入共享的数据库连接函数和路径配置
from .db_utils import get_db_connection, DATABASE_PATH, DEFAULT_CONTEXT_TTL_DAYS

logger = logging.getLogger('my_logger')

# --- 设置管理 ---
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """获取指定键的设置值"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row['value'] if row else default
    except sqlite3.Error as e:
        logger.error(f"获取设置 '{key}' 失败: {e}", exc_info=True)
        return default

def set_setting(key: str, value: str):
    """设置或更新指定键的设置值"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
            logger.info(f"设置 '{key}' 已更新为 '{value}'")
    except sqlite3.Error as e:
        logger.error(f"设置 '{key}' 失败: {e}", exc_info=True)

def get_ttl_days() -> int:
    """获取上下文 TTL 天数设置"""
    value_str = get_setting('context_ttl_days', str(DEFAULT_CONTEXT_TTL_DAYS))
    try:
        val = int(value_str) if value_str else DEFAULT_CONTEXT_TTL_DAYS
        return val if val >= 0 else 0 # TTL 不能为负数，0 表示禁用 TTL
    except (ValueError, TypeError):
        logger.warning(f"无效的 TTL 设置值 '{value_str}'，将使用默认值 {DEFAULT_CONTEXT_TTL_DAYS}")
        return DEFAULT_CONTEXT_TTL_DAYS

def set_ttl_days(days: int):
    """设置上下文 TTL 天数"""
    if not isinstance(days, int) or days < 0: # 允许设置为 0
        logger.error(f"尝试设置无效的 TTL 天数: {days}")
        raise ValueError("TTL 天数必须是非负整数")
    set_setting('context_ttl_days', str(days))